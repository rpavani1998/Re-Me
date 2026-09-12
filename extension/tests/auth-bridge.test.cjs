const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

for (const failure of ['synchronous', 'rejected', 'missing']) {
  test(`bridge handles ${failure} runtime failures for every dashboard request`, async () => {
    let listener;
    const replies = [];
    const page = {addEventListener(_type, fn) {listener = fn;}, postMessage(message) {replies.push(message);}};
    const runtime = {id: 'a'.repeat(32), sendMessage() {
      if (failure === 'synchronous') throw new Error('Extension context invalidated.');
      if (failure === 'rejected') return Promise.reject(new Error('Receiving end does not exist.'));
      return Promise.resolve(undefined);
    }};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../auth-bridge.js'), 'utf8'), {
      window: page, location: {origin: 'http://localhost:3000'}, chrome: {runtime},
    });
    const extensionId = runtime.id;
    runtime.id = undefined; // A tab can outlive its extension's runtime.
    for (const type of ['reme-extension-query', 'reme-connect-request', 'reme-sign-in-request']) {
      await listener({source: page, origin: 'http://localhost:3000', data: {
        type, extensionId, requestId: type, state: 'state', token: 'token',
      }});
      const reply = replies.find(item => item.requestId === type);
      assert.ok(reply);
      assert.match(reply.error, /Refresh this Re:Me tab/);
      if (type === 'reme-extension-query') assert.equal(reply.connected, false);
      else assert.equal(reply.ok, false);
    }
  });
}
