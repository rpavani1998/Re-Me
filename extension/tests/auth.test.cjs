const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
  const external = [], internal = [];
  const event = () => ({addListener() {}});
  function storage(initial = {}) {
    return {data: initial,
      async get(keys) {return Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, this.data[key]]));},
      async set(value) {Object.assign(this.data, value);},
      async remove(keys) {for (const key of Array.isArray(keys) ? keys : [keys]) delete this.data[key];},
      async clear() {this.data = {};},
    };
  }
  const session = storage({pendingLogin: {state: 'random-state', createdAt: Date.now(), apiUrl: 'http://localhost:8000', webUrl: 'http://localhost:3000'}});
  const local = storage();
  const calls = [];
  const chrome = {
    runtime: {id: 'a'.repeat(32), onInstalled: event(), onStartup: event(),
      onMessageExternal: {addListener(fn) {external.push(fn);}}, onMessage: {addListener(fn) {internal.push(fn);}}},
    storage: {session, local, onChanged: event()},
    contextMenus: {onClicked: event()},
    tabs: {onActivated: event(), onUpdated: event()}, windows: {onFocusChanged: event()},
    notifications: {onClicked: event()},
    idle: {onStateChanged: event(), async queryState() {return "active";}},
    alarms: {onAlarm: event(), async clear() {}}, action: {async setBadgeText() {}, async setBadgeBackgroundColor() {}},
  };
  const context = vm.createContext({chrome, URL, Date, setTimeout, crypto: require("node:crypto"), fetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, status: 200, async json() {return options?.method === 'POST' ? {id: 'saved-image', title: 'Saved image'} : {email: 'person@example.com'};}};
  }});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  const send = (overrides = {}, url = 'http://localhost:3000/?extension=test') => new Promise(resolve => external[0]({type: 'reme-sign-in', state: 'random-state', token: 'session-token', ...overrides}, {url}, result => setImmediate(() => resolve(result))));
  return {send, local, session, calls, internal, chrome, context, remember: context.remember};
}

test('extension accepts only its initiated dashboard handshake and rejects replay', async () => {
  const {send, local, calls} = setup();
  assert.equal((await send()).ok, true);
  assert.equal(local.data.email, 'person@example.com');
  assert.equal(local.data.token, 'session-token');
  assert.equal(local.data.contextEnabled, false);
  assert.equal(calls[0].url, 'http://localhost:8000/api/auth/me');
  assert.equal((await send()).ok, false);
});
test('extension rejects wrong state and wrong origin without sending credentials', async () => {
  const {send, local, calls} = setup();
  assert.equal((await send({state: 'forged'})).ok, false);
  assert.equal((await send({}, 'https://untrusted.example/')).ok, false);
  assert.equal(calls.length, 0);
  assert.equal(local.data.token, undefined);
});
test('extension rejects expired sign-in and oversized tokens', async () => {
  const {send, session, calls} = setup();
  assert.equal((await send({token: 'x'.repeat(257)})).ok, false);
  session.data.pendingLogin.createdAt -= 11 * 60 * 1000;
  assert.equal((await send()).ok, false);
  assert.equal(calls.length, 0);
});

test('extension rejects concurrent replay of the same handshake', async () => {
  const {send, calls} = setup();
  const results = await Promise.all([send(), send()]);
  assert.equal(results.filter(result => result.ok).length, 1);
  assert.equal(calls.length, 1);
});


test('dashboard bridge connects without window.chrome and ignores foreign messages', async () => {
  const {internal, chrome, local, calls} = setup();
  let listener;
  const replies = [];
  const page = {
    addEventListener(type, handler) {assert.equal(type, 'message'); listener = handler;},
    postMessage(message, origin) {replies.push({message, origin});},
  };
  chrome.runtime.sendMessage = message => new Promise(resolve => {
    for (const handler of internal) {
      const returned = handler(message, {
        id: chrome.runtime.id, tab: {id: 12}, frameId: 0, url: 'http://localhost:3000/',
      }, resolve);
      if (returned?.then) returned.then(resolve);
    }
  });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../auth-bridge.js'), 'utf8'), {
    window: page, location: {origin: 'http://localhost:3000'}, chrome,
    localStorage: {getItem() {return "dashboard-session";}},
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 0, "Loading the dashboard must not silently replace the extension session");
  const event = {source: page, origin: 'http://localhost:3000', data: {
    type: 'reme-sign-in-request', extensionId: chrome.runtime.id, requestId: 'request-1',
    state: 'random-state', token: 'session-token',
  }};
  await listener({...event, origin: 'https://untrusted.example'});
  await listener({...event, source: {}});
  await listener({...event, data: {...event.data, extensionId: 'other'}});
  assert.equal(calls.length, 0);
  assert.equal(replies.length, 0);
  assert.equal(page.chrome, undefined);
  await listener(event);
  assert.equal(local.data.token, 'session-token');
  assert.equal(replies[0].message.ok, true);
  assert.equal(replies[0].message.requestId, 'request-1');
  assert.equal(replies[0].origin, 'http://localhost:3000');
});


test('image menu saves the selected image even when it is also a link', async () => {
  const {remember, local, calls, chrome} = setup();
  local.data.token = 'session';
  local.data.apiUrl = 'http://localhost:8000';
  chrome.scripting = {async executeScript() {return [{result: 'A quiet garden'}];}};
  const result = await remember({id: 3, url: 'https://example.com/story', title: 'Story'}, '', {
    menuItemId: 'remember-image', srcUrl: 'https://example.com/photo.jpg', linkUrl: 'https://example.com/other',
  });
  const payload = JSON.parse(calls[0].options.body);
  assert.equal(result.id, 'saved-image');
  assert.equal(payload.source_type, 'image');
  assert.equal(payload.image_url, 'https://example.com/photo.jpg');
  assert.equal(payload.source_url, 'https://example.com/story');
  assert.equal(payload.visible_text, 'A quiet garden');
});
test('image menu rejects inline images without making an API request', async () => {
  const {remember, calls} = setup();
  await assert.rejects(remember({id: 3, url: 'https://example.com'}, '', {
    menuItemId: 'remember-image', srcUrl: 'blob:https://example.com/123',
  }), /public web address/);
  assert.equal(calls.length, 0);
});


test('suggestion preview injects an explicit example without tracking or API calls', async () => {
  const {internal, chrome, local, calls} = setup();
  let injection;
  chrome.tabs.query = async () => [{id: 7, url: 'https://example.com', incognito: false}];
  chrome.scripting = {async executeScript(options) {injection = options;}};
  const reply = await new Promise(resolve => {
    for (const handler of internal) handler({type: 'preview-suggestion'}, {id: chrome.runtime.id}, resolve);
  });
  assert.equal(reply.ok, true);
  assert.equal(injection.target.tabId, 7);
  assert.equal(injection.args[1], true);
  assert.equal(injection.args[0].memory.title, 'A quiet café in Tokyo');
  assert.equal(calls.length, 0);
  assert.equal(local.data.contextEnabled, undefined);
});
test('suggestion preview rejects restricted pages', async () => {
  const {internal, chrome} = setup();
  chrome.tabs.query = async () => [{id: 7, url: 'chrome://extensions', incognito: false}];
  const reply = await new Promise(resolve => {
    for (const handler of internal) handler({type: 'preview-suggestion'}, {id: chrome.runtime.id}, resolve);
  });
  assert.equal(reply.ok, false);
  assert.match(reply.error, /normal webpage/);
});


test('unrelated runtime listeners do not claim sign-in replies', () => {
  const {internal, chrome} = setup();
  for (const listener of internal) {
    const result = listener({type: 'unrelated'}, {id: chrome.runtime.id}, () => assert.fail('Unexpected response'));
    assert.equal(result, undefined);
  }
});

test('a failed account verification can retry the same pending connection', async () => {
  const {send, session, context} = setup();
  const originalFetch = context.fetch;
  context.fetch = async () => ({ok: false});
  assert.equal((await send()).ok, false);
  assert.equal(session.data.pendingLogin.state, 'random-state');
  context.fetch = originalFetch;
  assert.equal((await send()).ok, true);
  assert.equal(session.data.pendingLogin, undefined);
});

test('stopping suggestions preserves a pending sign-in', async () => {
  const {context, session} = setup();
  session.data.activePage = {tabId: 1};
  session.data.suggestion = {id: 'example'};
  await context.stopContext();
  assert.equal(session.data.pendingLogin.state, 'random-state');
  assert.equal(session.data.activePage, undefined);
  assert.equal(session.data.suggestion, undefined);
});

test('bridge registration uses the selected dashboard and reports errors', async () => {
  const {internal, chrome} = setup();
  let registered;
  chrome.scripting = {
    async getRegisteredContentScripts() {return [];},
    async registerContentScripts(scripts) {registered = scripts;},
  };
  const request = () => new Promise(resolve => {
    for (const handler of internal) handler({type: 'ensure-bridge', webUrl: 'https://memory.example'}, {id: chrome.runtime.id}, resolve);
  });
  assert.equal((await request()).ok, true);
  assert.equal(registered[0].matches[0], 'https://memory.example/*');
  chrome.scripting.registerContentScripts = async () => {throw new Error('Permission denied');};
  assert.equal((await request()).error, 'Permission denied');
});


test('popup save receives the capture reply through all background listeners', async () => {
  const {internal, chrome, local, calls} = setup();
  local.data.token = 'extension-session';
  local.data.apiUrl = 'http://localhost:8000';
  const tab = {id: 12, url: 'https://example.com/article', title: 'An article', incognito: false};
  chrome.tabs.query = async () => [tab];
  chrome.scripting = {async executeScript() {return [{result: {
    source_url: tab.url, page_title: tab.title, visible_text: 'The article content',
  }}];}};
  chrome.runtime.sendMessage = message => new Promise(resolve => {
    for (const listener of internal) {
      const result = listener(message, {id: chrome.runtime.id}, resolve);
      // Chrome accepts Promise replies too, including accidental async undefined replies.
      if (result?.then) result.then(resolve);
    }
  });
  const elements = {};
  const element = () => ({textContent: '', value: '', dataset: {}, append() {}, setAttribute() {}, replaceChildren() {}});
  const document = {getElementById(id) {return elements[id] ||= element();}, createElement: element};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../popup.js'), 'utf8'), {document, chrome, URL});
  await new Promise(resolve => setImmediate(resolve));
  await elements.remember.onclick();
  assert.equal(elements.status.dataset.state, 'success');
  assert.equal(elements.remember.textContent, 'Saved to Re:Me ✓');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://localhost:8000/api/captures?background=true');
  assert.equal(JSON.parse(calls[0].options.body).visible_text, 'The article content');
});


test('right-click selection saves without script access, including inside a linked frame', async () => {
  const {remember, local, calls, chrome} = setup();
  local.data.token = 'session'; local.data.apiUrl = 'http://localhost:8000';
  chrome.scripting = {executeScript() {assert.fail('Selected text must not require injection');}};
  await remember({id: 4, url: 'https://example.com', title: 'Page'}, '', {
    menuItemId: 'remember-selection', selectionText: 'Keep this passage',
    frameUrl: 'https://example.com/frame', linkUrl: 'https://example.com/link',
  });
  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.source_type, 'selection');
  assert.equal(body.selected_text, 'Keep this passage');
  assert.equal(body.source_url, 'https://example.com/frame');
});


test('settings in an extension tab can prepare sign-in; website tabs cannot', async () => {
  const {internal, chrome} = setup();
  let registrations = 0;
  chrome.scripting = {
    async getRegisteredContentScripts() {return [];},
    async registerContentScripts() {registrations++;},
  };
  const message = {type: 'ensure-bridge', webUrl: 'http://localhost:3000'};
  const result = await new Promise(resolve => {
    for (const listener of internal) listener(message, {
      id: chrome.runtime.id, tab: {id: 42}, frameId: 0,
      url: `chrome-extension://${chrome.runtime.id}/options.html`,
    }, resolve);
  });
  assert.equal(result.ok, true);
  assert.equal(registrations, 1);
  for (const listener of internal) {
    assert.equal(listener(message, {id: chrome.runtime.id, tab: {id: 43}, frameId: 0,
      url: 'http://localhost:3000/'}, () => assert.fail('Website cannot configure bridge')), undefined);
  }
  assert.equal(registrations, 1);
});


test('due reminders wait until Chrome is focused and the user is active', async () => {
  const {context, chrome, local, session} = setup();
  local.data.token = 'session'; local.data.apiUrl = 'http://localhost:8000';
  let requests = 0, focused = false, state = 'active';
  chrome.windows.getLastFocused = async () => ({focused});
  chrome.idle.queryState = async () => state;
  chrome.tabs.query = async () => [{id: 1, incognito: false}];
  context.fetch = async () => {requests++; return {ok: true, status: 200, json: async () => ({suggestion: {
    id: 'due-reminder', trigger_id: 'trigger', memory: {title: 'Application deadline'},
  }})};};
  await context.checkReminders();
  focused = true; state = 'idle';
  await context.checkReminders();
  state = 'locked'; await context.checkReminders();
  assert.equal(requests, 0);
  assert.equal(session.data.suggestion, undefined);
  state = 'active'; await context.checkReminders();
  assert.equal(requests, 1);
  assert.equal(session.data.suggestion.id, 'due-reminder');
});
