// Runs in the extension's isolated world on the dashboard selected at sign-in.
// Keep the ID while this content script is valid; reloading the extension invalidates its runtime.
const bridgeExtensionId = chrome.runtime.id;
async function sendToExtension(message) {
  try {
    const result = await chrome.runtime.sendMessage(message);
    if (!result) throw new Error("No extension response");
    return result;
  } catch {
    // sendMessage can throw synchronously before returning a Promise.
    return {ok: false, connected: false, email: null,
      error: "Refresh this Re:Me tab to reconnect to the extension. If you were signing in, start again from extension settings."};
  }
}
async function postStatus() {
  const {connected, email, error} = await sendToExtension({type: "reme-status"});
  window.postMessage({type: "reme-extension-status", connected: connected === true, email, error}, location.origin);
}

window.addEventListener("message", async event => {
  const message = event.data;
  if (event.source !== window || event.origin !== location.origin || !message?.type) return;
  if (message.type === "reme-extension-query" && message.requestId) {
    const connected = await sendToExtension({type: "reme-status"});
    window.postMessage({type: "reme-extension-status", requestId: message.requestId, connected: connected?.connected === true, email: connected?.email, error: connected?.error}, location.origin);
    return;
  }
  if (message.type === "reme-connect-request" && message.requestId && typeof message.token === "string") {
    const result = await sendToExtension({type: "reme-open-settings"});
    window.postMessage({type: "reme-connect-result", requestId: message.requestId, ok: result?.ok === true, error: result?.error}, location.origin);
    postStatus();
    return;
  }
  const request = message;
  if (request?.type !== "reme-sign-in-request" || request.extensionId !== bridgeExtensionId ||
      typeof request.requestId !== "string" || request.requestId.length > 100) return;
  const result = await sendToExtension({type: "reme-sign-in", state: request.state, token: request.token});
  window.postMessage({type: "reme-sign-in-result", extensionId: bridgeExtensionId,
    requestId: request.requestId, ok: result?.ok === true, error: result?.error}, location.origin);
});
