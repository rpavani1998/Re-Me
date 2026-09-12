const DEFAULTS = {apiUrl:"http://localhost:8000", token:"", webUrl:"http://localhost:3000", contextEnabled:true};
const BRIDGE_ID = "reme-login-bridge";
function isExtensionPage(sender) {
  if (sender.id !== chrome.runtime.id) return false;
  // An options page opened in a browser tab can have sender.tab too.
  return sender.url ? sender.url.startsWith(`chrome-extension://${chrome.runtime.id}/`) : !sender.tab;
}
async function ensureBridge(requestedWebUrl) {
  const {webUrl} = await chrome.storage.local.get("webUrl");
  const origin = new URL(requestedWebUrl || webUrl || "http://localhost:3000").origin;
  try {
    const registered = await chrome.scripting.getRegisteredContentScripts({ids:[BRIDGE_ID]});
    if (registered.length && registered[0].matches?.includes(origin + "/*")) return;
    if (registered.length) await chrome.scripting.unregisterContentScripts({ids:[BRIDGE_ID]});
    await chrome.scripting.registerContentScripts([{id:BRIDGE_ID, matches:[origin + "/*"], js:["auth-bridge.js"], runAt:"document_start", persistAcrossSessions:true}]);
  } catch (error) { await chrome.storage.local.set({lastError:"Extension bridge error: " + (error && error.message || error)}); throw error; }
}
async function failSave(error, tabId) {
  await chrome.storage.local.set({lastError:error.message});
  await chrome.action.setBadgeText({text:"!",tabId});
  if (/sign ?in|session expired/i.test(error.message)) chrome.runtime.openOptionsPage().catch(() => {});
}
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({...DEFAULTS, ...await chrome.storage.local.get(null)});
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({id:"remember-selection",title:"Remember selection with Re:Me",contexts:["selection"]});
    chrome.contextMenus.create({id:"remember-link",title:"Remember link with Re:Me",contexts:["link"]});
    chrome.contextMenus.create({id:"remember-image",title:"Remember image with Re:Me",contexts:["image"]});
  });
  await ensureBridge();
});
async function api(path, body, method) {
  const {apiUrl, token} = {...DEFAULTS, ...await chrome.storage.local.get(["apiUrl","token"])};
  if (!token) throw new Error("Sign in to Re:Me in extension settings.");
  const response = await fetch(apiUrl.replace(/\/$/,"") + path, {method:method || (body ? "POST":"GET"), headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"}, ...(body ? {body:JSON.stringify(body)} : {})});
  if (response.status === 401) {
    await stopContext();
    await chrome.storage.local.remove(["token", "email"]);
    throw new Error("Your session expired. Sign in again in extension settings.");
  }
  const data = response.status === 204 ? {} : await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(d => typeof d === "string" ? d : d.msg).filter(Boolean).join("; ")
      : typeof data.detail === "string" ? data.detail : data.detail?.message;
    throw new Error(detail || "Re:Me request failed");
  }
  return data;
}
async function remember(tab, note="", info=null) {
  if (!tab?.id || !/^https?:/.test(tab.url || "") || tab.incognito) throw new Error("Choose a normal webpage outside incognito mode.");
  let capture;
  if (info?.menuItemId === "remember-image") {
    if (!/^https?:\/\//i.test(info.srcUrl || "")) throw new Error("This image has no public web address. Try an image hosted on a website.");
    let caption = "";
    try {
      const [result] = await chrome.scripting.executeScript({
        target: {tabId: tab.id, ...(info.frameId ? {frameIds: [info.frameId]} : {})},
        func: source => {
          const image = [...document.images].find(item => item.currentSrc === source || item.src === source);
          return [image?.alt, image?.closest("figure")?.querySelector("figcaption")?.innerText].filter(Boolean).join("\n").slice(0, 2000);
        }, args: [info.srcUrl],
      });
      caption = result?.result || "";
    } catch { /* The selected image URL still works when frame text is inaccessible. */ }
    capture = {source_type: "image", source_url: info.pageUrl || tab.url, image_url: info.srcUrl,
      page_title: caption.slice(0, 500) || `Image from ${tab.title || new URL(tab.url).hostname}`.slice(0, 500),
      visible_text: caption, captured_at: new Date().toISOString()};
  } else if (info?.selectionText) {
    // Context-menu selection is already supplied by Chrome, including inside frames.
    // Saving it must not depend on script injection into the page.
    capture = {source_type:"selection", source_url:info.frameUrl || info.pageUrl || tab.url,
      page_title:(tab.title || "Saved selection").slice(0,500),
      selected_text:info.selectionText.slice(0,8000), visible_text:info.selectionText.slice(0,16000),
      captured_at:new Date().toISOString()};
  } else if (info?.linkUrl) capture = {source_url:info.linkUrl, page_title:info.linkUrl, source_type:"link", visible_text:"", captured_at:new Date().toISOString()};
  else {
    const [result] = await chrome.scripting.executeScript({target:{tabId:tab.id},files:["capture.js"]});
    capture = {...result.result, source_type:info?.selectionText ? "selection":"webpage"};
    if (info?.selectionText) capture.selected_text = info.selectionText.slice(0,8000);
  }
  const memory = await api("/api/captures?background=true", {...capture, user_note:note || null, request_id:crypto.randomUUID()});
  await chrome.action.setBadgeText({text:"✓",tabId:tab.id});
  await chrome.action.setBadgeBackgroundColor({color:"#698161",tabId:tab.id});
  await chrome.storage.local.set({lastError:"",lastSaved:memory.title});
  return memory;
}
chrome.contextMenus.onClicked.addListener((info, tab) => {
  remember(tab,"",info).catch(e => failSave(e, tab?.id));
});
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return;
  if (message.type === "capture") {
    chrome.tabs.query({active:true,currentWindow:true}).then(([tab]) => remember(tab,message.note))
      .then(memory => sendResponse({ok:true,memory})).catch(e => {sendResponse({ok:false,error:e.message}); failSave(e, undefined);});
    return true;
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!isExtensionPage(sender) || message?.type !== "ensure-bridge") return;
  ensureBridge(message.webUrl).then(() => sendResponse({ok: true}))
    .catch(error => sendResponse({ok: false, error: error.message}));
  return true;
});

// Keep the listener synchronous: an async listener can claim unrelated messages.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || message?.type !== "reme-status") return;
  chrome.storage.local.get(["token", "email"]).then(({token, email}) =>
    sendResponse({connected: !!token, email: token ? email || null : null}));
  return true;
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || message?.type !== "reme-open-settings") return;
  (async () => {
    const {webUrl} = await chrome.storage.local.get("webUrl");
    if (new URL(sender.url).origin !== new URL(webUrl || DEFAULTS.webUrl).origin) throw new Error("Open your Re:Me dashboard to connect.");
    await chrome.runtime.openOptionsPage();
    return {ok: true};
  })().then(sendResponse).catch(error => sendResponse({ok: false, error: error.message}));
  return true;
});

async function trackActive() {
  const {contextEnabled} = await chrome.storage.local.get("contextEnabled");
  if (!contextEnabled) return;
  const window = await chrome.windows.getLastFocused();
  if (!window.focused) {await chrome.storage.session.remove("activePage");return;}
  const [tab] = await chrome.tabs.query({active:true,lastFocusedWindow:true});
  if (!tab?.id || tab.incognito || !/^https?:/.test(tab.url || "")) {await chrome.storage.session.remove("activePage");return;}
  const previous = (await chrome.storage.session.get("activePage")).activePage;
  if (previous?.tabId !== tab.id || previous?.url !== tab.url) await chrome.storage.session.set({activePage:{tabId:tab.id,url:tab.url,since:Date.now()}});
}
chrome.tabs.onActivated.addListener(() => trackActive().catch(() => {}));
chrome.tabs.onUpdated.addListener((_id, change) => {if (change.status === "complete" || change.url) trackActive().catch(() => {});});
chrome.windows.onFocusChanged.addListener(() => trackActive().catch(() => {}));
chrome.runtime.onStartup.addListener(async () => {
  // Context Mode is on by default; users can still turn it off at any time.
  await chrome.storage.local.set({contextEnabled:true});
  await chrome.alarms.create("context-tick",{periodInMinutes:0.5});
  await ensureBridge();
});
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({contextEnabled:true});
  await chrome.alarms.create("context-tick",{periodInMinutes:0.5});
});
async function stopContext() {
  await chrome.storage.local.set({contextEnabled:false});
  await chrome.storage.session.remove(["activePage", "suggestion"]);
  await chrome.alarms.clear("context-tick");
  await chrome.action.setBadgeText({text:""});
}
async function contextTick() {
  const {contextEnabled, token} = await chrome.storage.local.get(["contextEnabled","token"]);
  if (!contextEnabled) return;
  let remote;
  try { remote = await api("/api/context/current", undefined, "GET"); }
  catch { return; }
  if (!remote.enabled) {
    try { await api("/api/context/mode",{enabled:true},"PUT"); }
    catch { return; }
    remote = await api("/api/context/current", undefined, "GET");
    if (!remote.enabled) return;
  }
  if (!token) return;
  await trackActive();
  const {activePage} = await chrome.storage.session.get("activePage");
  if (!activePage || Date.now()-activePage.since < 8000) return;
  const tab = await chrome.tabs.get(activePage.tabId);
  if (!tab.active || tab.url !== activePage.url) return;
  const [result] = await chrome.scripting.executeScript({target:{tabId:tab.id},func:() => {
    const query = new URL(location.href).searchParams;
    return {source_url:location.origin+location.pathname, page_title:document.title.slice(0,500),
      search_query:(query.get("q") || query.get("query") || "").slice(0,500),
      visible_text:(document.body?.innerText || "").slice(0,3000)};
  }}).catch(async error => {
    if (/Cannot access|host permission|not allowed/i.test(error?.message || "")) {
      // Reads pages as you browse. Requested once; revocable in extension settings.
      const granted = await chrome.permissions.request({origins:["https://*/*","http://*/*"]});
      if (granted) {
        return chrome.scripting.executeScript({target:{tabId:tab.id},func:() => {
          const query = new URL(location.href).searchParams;
          return {source_url:location.origin+location.pathname, page_title:document.title.slice(0,500),
            search_query:(query.get("q") || query.get("query") || "").slice(0,500),
            visible_text:(document.body?.innerText || "").slice(0,3000)};
        }});
      }
      await chrome.action.setBadgeText({text:"!"});
      await chrome.action.setBadgeBackgroundColor({color:"#c9652f"});
      await chrome.storage.local.set({lastError:"Context Mode needs permission to read the pages you browse. Grant page access in the extension popup."});
      chrome.runtime.openOptionsPage().catch(() => {});
      throw error;
    }
    throw error;
  });
  if (!(await chrome.storage.local.get("contextEnabled")).contextEnabled) return;
  const event = {...result.result,event_type:result.result.search_query ? "SEARCH_DETECTED":"PAGE_ENTERED",dwell_seconds:Math.min((Date.now()-activePage.since)/1000,3600)};
  const outcome = await api("/api/context/events",{events:[event]});
  if (outcome.reason === "context_mode_off") {await stopContext();return;}
  if (outcome.analyzed) {
    const evaluation = await api("/api/relevance/evaluate",{});
    if (evaluation.suggestion && (await chrome.storage.local.get("contextEnabled")).contextEnabled) {
      await chrome.storage.session.set({suggestion:evaluation.suggestion});
      await chrome.action.setBadgeText({text:"1"});
      await chrome.action.setBadgeBackgroundColor({color:"#698161"});
      await chrome.scripting.executeScript({target:{tabId:tab.id},func:showRecall,args:[evaluation.suggestion]});
      const {notifiedId} = await chrome.storage.session.get("notifiedId");
      if (evaluation.suggestion.id !== notifiedId) {
        await chrome.storage.session.set({notifiedId:evaluation.suggestion.id});
        chrome.notifications.create(`reme-recall-${evaluation.suggestion.id}`, {
          type:"basic", iconUrl:chrome.runtime.getURL("icons/logo128.png"), title:"Re:Me · A memory for this moment",
          message:`${evaluation.suggestion.memory.title} — ${evaluation.suggestion.reason}`, priority:1
        });
      }
    }
  }
}
chrome.notifications.onClicked.addListener(id => {
  chrome.notifications.clear(id);
  const memoryId = id.replace("reme-recall-", "");
  chrome.tabs.create({url:`${DEFAULTS.webUrl}/?memory=${memoryId}`});
});
function showRecall(suggestion, preview = false) {
  const hostId = preview ? "reme-recall-preview-host" : "reme-recall-host";
  const existing = document.getElementById(hostId);
  if (existing && !preview) return;
  existing?.remove();
  const host = document.createElement("div");host.id=hostId;
  const root = host.attachShadow({mode:"closed"});
  const style=document.createElement("style");
  style.textContent=":host{all:initial;position:fixed;right:24px;bottom:24px;z-index:2147483647}*{box-sizing:border-box}section{position:relative;background:#fffdf7;border:1px solid #e4dacb;border-radius:18px;padding:26px;width:min(390px,calc(100vw - 48px));box-shadow:0 16px 64px #42352126;color:#75624b;font:13px/1.8 -apple-system,BlinkMacSystemFont,Arial,sans-serif}h2{font:27px/1.25 Georgia,serif;letter-spacing:-.6px;margin:14px 0 10px;padding-right:8px}p{color:#a18f75;font-size:12px;line-height:1.9;margin:0 0 18px}small{font:8px Arial;letter-spacing:1.5px;color:#ae9879}button{cursor:pointer;background:#b77556;color:#fffaf3;border:0;border-radius:8px;padding:11px 16px;margin-right:10px;font-size:11px}button:last-child{background:#f2ecdf;color:#99856a}button:focus-visible{outline:2px solid #b88961;outline-offset:3px}";
  root.append(style);
  const card=document.createElement("section");card.setAttribute("role","status");
  const label=document.createElement("small");label.textContent=preview ? "RE:ME · PREVIEW · EXAMPLE MEMORY" : "RE:ME · A MEMORY FOR THIS MOMENT";
  const title=document.createElement("h2");title.textContent=suggestion.memory.title;
  const reason=document.createElement("p");reason.textContent=suggestion.reason;
  const open=document.createElement("button");open.textContent=preview ? "Got it" : "Open memory";
  open.onclick=() => preview ? host.remove() : chrome.runtime.sendMessage({type:"feedback",id:suggestion.id,outcome:"opened"}).then(r => {if(r.ok)host.remove();});
  const dismiss=document.createElement("button");dismiss.textContent="Not now";
  dismiss.onclick=() => {if (!preview) chrome.runtime.sendMessage({type:"feedback",id:suggestion.id,outcome:"dismissed"});host.remove();};
  card.append(label,title,reason,open,dismiss);root.append(card);document.documentElement.append(host);
  const remove = (_changes, area) => {if(area === "local")chrome.storage.local.get("contextEnabled").then(s=>{if(!s.contextEnabled){host.remove();chrome.storage.onChanged.removeListener(remove);}});};
  if (!preview) chrome.storage.onChanged.addListener(remove);
  setTimeout(()=>{host.remove();chrome.storage.onChanged.removeListener(remove);},60000);
}
chrome.alarms.onAlarm.addListener(alarm => {if (alarm.name === "context-tick") contextTick().catch(async e => {await chrome.storage.local.set({lastError:e.message});});});
chrome.runtime.onMessage.addListener((message,sender,respond) => {
  if (sender.id !== chrome.runtime.id) return;
  if (message.type === "context-mode" && isExtensionPage(sender)) {
    (async () => {
      if (!message.enabled) await stopContext();
      await api("/api/context/mode",{enabled:message.enabled},"PUT");
      if (message.enabled) {
        await chrome.storage.local.set({contextEnabled:true});
        await trackActive();
        await chrome.alarms.create("context-tick",{periodInMinutes:0.5});
      }
      return {ok:true};
    })().then(respond).catch(e=>respond({ok:false,error:e.message}));
    return true;
  }
  if (message.type === "feedback") {
    (async () => {
      const {suggestion}=await chrome.storage.session.get("suggestion");
      if (!suggestion || suggestion.id !== message.id) throw new Error("This suggestion has expired.");
      await api(`/api/relevance/${suggestion.id}/feedback`,{outcome:message.outcome});
      if (message.outcome === "opened" && /^https?:/.test(suggestion.memory.source_url || "")) await chrome.tabs.create({url:suggestion.memory.source_url});
      await chrome.storage.session.remove("suggestion");
      await chrome.action.setBadgeText({text:""});
      return {ok:true};
    })().then(respond).catch(e=>respond({ok:false,error:e.message}));
    return true;
  }
});


// The extension initiates this handshake; unrelated websites cannot provide a session.
let loginInProgress = false;
function receiveSignIn(message, sender, respond) {
  if (message?.type !== "reme-sign-in") return;
  if (loginInProgress) { respond({ok: false, error: "Sign-in is already in progress."}); return; }
  loginInProgress = true;
  (async () => {
    const {pendingLogin} = await chrome.storage.session.get("pendingLogin");
    const stored = {...DEFAULTS, ...await chrome.storage.local.get(["apiUrl","webUrl"])};
    const expectedWeb = pendingLogin?.webUrl || stored.webUrl;
    const probableApi = pendingLogin?.apiUrl || stored.apiUrl;
    if (!pendingLogin || typeof message.token !== "string" || message.token.length > 256 ||
        new URL(sender?.url || "").origin !== new URL(expectedWeb).origin ||
        (pendingLogin && (message.state !== pendingLogin.state || Date.now() - pendingLogin.createdAt > 10 * 60 * 1000))) {
      throw new Error("Sign-in expired. Start again from the extension settings.");
    }
    const response = await fetch(probableApi + "/api/auth/me", {headers: {Authorization: `Bearer ${message.token}`}});
    if (!response.ok) throw new Error("Could not verify your account. Check the backend URL in extension settings.");
    const account = await response.json();
    if (!account.email) throw new Error("Sign in with email or Google first.");
    await stopContext();
    await chrome.storage.local.set({token: message.token, email: account.email, apiUrl: probableApi, webUrl: expectedWeb, lastError: ""});
    await chrome.action.setBadgeText({text:""});
    await chrome.storage.session.remove("pendingLogin");
    return {ok: true};
  })().then(respond).catch(error => respond({ok: false, error: error.message})).finally(() => {loginInProgress = false;});
  return true;
}
chrome.runtime.onMessageExternal.addListener(receiveSignIn);
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || !sender.tab || sender.frameId !== 0) return;
  return receiveSignIn(message, sender, respond);
});
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!isExtensionPage(sender) || message.type !== "sign-out") return;
  (async () => {
    await api("/api/auth/logout", {});
    await stopContext();
    await chrome.storage.local.remove(["token", "email", "lastSaved", "lastError"]);
    return {ok: true};
  })().then(respond).catch(error => respond({ok: false, error: error.message}));
  return true;
});


chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!isExtensionPage(sender) || message.type !== "preview-suggestion") return;
  (async () => {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.id || tab.incognito || !/^https?:/.test(tab.url || "")) throw new Error("Open a normal webpage, then try the preview again.");
    const example = {memory: {title: "A quiet café in Tokyo"}, reason: "Planning a trip to Japan? That little café you saved could be just the place to stop. This is an example of how a memory can reappear."};
    await chrome.scripting.executeScript({target: {tabId: tab.id}, func: showRecall, args: [example, true]});
    return {ok: true};
  })().then(respond).catch(error => respond({ok: false, error: error.message}));
  return true;
});


// Scheduled reminders are independent of optional browsing observation.
async function checkReminders() {
  if (!(await chrome.storage.local.get("token")).token) return;
  const [window, activity] = await Promise.all([chrome.windows.getLastFocused(), chrome.idle.queryState(60)]);
  if (!window.focused || activity !== "active") return;
  const [tab] = await chrome.tabs.query({active:true,lastFocusedWindow:true});
  if (!tab || tab.incognito) return;
  const {suggestion} = await api("/api/relevance/current");
  if (!suggestion?.trigger_id) return;
  const {lastReminderId} = await chrome.storage.local.get("lastReminderId");
  if (lastReminderId === suggestion.id) return;
  await chrome.storage.session.set({suggestion});
  await chrome.action.setBadgeText({text:"1"});
  await chrome.action.setBadgeBackgroundColor({color:"#698161"});
  await chrome.storage.local.set({lastReminderId:suggestion.id});
}
chrome.runtime.onInstalled.addListener(() => chrome.alarms.create("reminder-tick", {periodInMinutes:1}));
chrome.runtime.onStartup.addListener(() => chrome.alarms.create("reminder-tick", {periodInMinutes:1}));
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "reminder-tick") checkReminders().catch(() => {});
});

chrome.windows.onFocusChanged.addListener(() => checkReminders().catch(() => {}));
chrome.idle.onStateChanged.addListener(state => {
  if (state === "active") checkReminders().catch(() => {});
});
