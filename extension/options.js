const status = document.getElementById("status");
async function refresh() {
  const settings = await chrome.storage.local.get(["apiUrl", "webUrl", "token", "email"]);
  document.getElementById("url").value = settings.apiUrl || "http://localhost:8000";
  document.getElementById("web-url").value = settings.webUrl || "http://localhost:3000";
  document.getElementById("account").textContent = settings.token && settings.email ? `Signed in as ${settings.email}` : "Sign in to keep your memories close.";
  document.getElementById("signin").hidden = !!(settings.token && settings.email);
  document.getElementById("signout").hidden = !(settings.token && settings.email);
}
refresh();
chrome.storage.onChanged.addListener((_changes, area) => {if (area === "local") refresh();});
function connectionUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) throw new Error("Use HTTPS, or localhost for development.");
  return url;
}
document.getElementById("signin").onclick = async () => {
  const button = document.getElementById("signin");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const api = connectionUrl(document.getElementById("url").value);
    const web = connectionUrl(document.getElementById("web-url").value);
    if (!await chrome.permissions.request({origins: [api.origin + "/*", web.origin + "/*"]})) throw new Error("Backend access was not granted.");
    const bridge = await chrome.runtime.sendMessage({type: "ensure-bridge", webUrl: web.origin});
    if (!bridge?.ok) throw new Error(bridge?.error || "Could not prepare the connection. Reload the extension and try again.");
    const state = crypto.randomUUID();
    await chrome.storage.session.set({pendingLogin: {state, apiUrl: api.origin, webUrl: web.origin, createdAt: Date.now()}});
    web.pathname = "/";
    web.search = new URLSearchParams({extension: chrome.runtime.id, state}).toString();
    web.hash = "";
    await chrome.tabs.create({url: web.href});
    status.textContent = "Finish signing in in the new tab, then click Connect extension.";
  } catch (error) {status.textContent = error.message;}
  finally {button.disabled = false;}
};
document.getElementById("signout").onclick = async () => {
  try {
    const result = await chrome.runtime.sendMessage({type: "sign-out"});
    if (!result.ok) throw new Error(result.error);
    status.textContent = "Signed out.";
    await refresh();
  } catch (error) {status.textContent = error.message;}
};
