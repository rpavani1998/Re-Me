document.getElementById("settings").onclick = () => chrome.runtime.openOptionsPage();
const status = document.getElementById("status");
const rememberButton = document.getElementById("remember");
let signedIn = false;
let validPage = false;
function showStatus(message, state = "info") {
  status.textContent = message;
  status.title = message;
  status.dataset.state = state;
}
async function initialize() {
  try {
    const [{token, lastError}, tabs] = await Promise.all([
      chrome.storage.local.get(["token", "lastError"]),
      chrome.tabs.query({active: true, currentWindow: true}),
    ]);
    signedIn = !!token;
    const tab = tabs[0];
    validPage = !!tab && /^https?:/.test(tab.url || "") && !tab.incognito;
    document.getElementById("page-title").textContent = validPage ? tab.title || "Untitled page" : "Open a webpage to save";
    document.getElementById("page-domain").textContent = validPage ? new URL(tab.url).hostname.replace(/^www\./, "") : "YOUR NEXT DISCOVERY";
    rememberButton.textContent = signedIn ? "Remember this page" : "Sign in to start saving ↗";
    rememberButton.disabled = signedIn && !validPage;
    if (!signedIn) showStatus("Connect your account to keep this in your space.");
    else if (!validPage) showStatus("Choose a normal webpage outside incognito mode.");
    else if (lastError) showStatus(lastError, "error");
  } catch(error) { showStatus(error.message, "error"); }
}
initialize();
document.getElementById("dashboard").onclick = async () => {
  try {
    const {webUrl} = await chrome.storage.local.get("webUrl");
    const url = new URL(webUrl || "http://localhost:3000");
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("Check your dashboard URL in Account settings.");
    await chrome.tabs.create({url: url.href});
  } catch(error) { showStatus(error.message, "error"); }
};
rememberButton.onclick = async () => {
  if (!signedIn) { await chrome.runtime.openOptionsPage(); return; }
  rememberButton.disabled = true;
  rememberButton.textContent = "Remembering…";
  showStatus("Saving this page to your space…", "saving");
  try {
    const result = await chrome.runtime.sendMessage({type:"capture",note:document.getElementById("note").value});
    if (!result || typeof result.ok !== "boolean") throw new Error("The extension did not confirm the save. Check your memories first, then reload Re:Me at chrome://extensions and reopen this popup.");
    if (!result.ok) throw new Error(result.error || "The save failed without an error description. Check the Re:Me backend logs.");
    showStatus(result.memory.status === "queued" || result.memory.status === "processing" ? `Saved: ${result.memory.title}. Understanding in the background.` : `Saved to your memories: ${result.memory.title}`, "success");
    rememberButton.textContent = "Saved to Re:Me ✓";
  } catch(error) {
    showStatus(error.message, "error");
    if (/sign ?in|session expired/i.test(error.message)) {
      signedIn = false;
      rememberButton.textContent = "Sign in again ↗";
    } else { rememberButton.textContent = "Try saving again"; }
  } finally { rememberButton.disabled = signedIn && !validPage; }
};
const contextControls=document.getElementById("context-controls");
const row=document.createElement("div");row.className="context";
const label=document.createElement("span");label.textContent="Context Mode";
const toggle=document.createElement("button");toggle.setAttribute("role","switch");toggle.setAttribute("aria-label","Context Mode");
row.append(label,toggle);contextControls.append(row);
const privacy=document.createElement("p");privacy.textContent="Opt in to suggestions based on active pages. Your full browsing history is never scanned.";contextControls.append(privacy);
let enabled=false;
chrome.storage.local.get("contextEnabled").then(s=>{enabled=!!s.contextEnabled;toggle.textContent=enabled?"ON":"OFF";toggle.setAttribute("aria-checked",String(enabled));});
toggle.onclick=async()=>{
  if (!signedIn) {await chrome.runtime.openOptionsPage(); return;}
  toggle.disabled=true;
  try {
    if (!enabled && !await chrome.permissions.request({origins:["https://*/*","http://*/*"]})) throw new Error("Context Mode remains off. Page access was not granted.");
    const result=await chrome.runtime.sendMessage({type:"context-mode",enabled:!enabled});
    if (!result.ok) throw new Error(result.error);
    enabled=!enabled;toggle.textContent=enabled?"ON":"OFF";toggle.setAttribute("aria-checked",String(enabled));
    status.textContent=enabled?"Context Mode is on for this browser session.":"Context Mode is off. Temporary context cleared.";
    if(!enabled){const card=document.getElementById("suggestion");card.replaceChildren();card.className="";document.getElementById("suggestion-example").hidden=false;}
  }catch(e){showStatus(e.message,"error");} finally {toggle.disabled=false;}
};
chrome.storage.session.get("suggestion").then(({suggestion})=>{
  if(!suggestion)return;
  document.getElementById("suggestion-example").hidden = true;
  const card=document.getElementById("suggestion");card.className="suggestion";
  const title=document.createElement("h2");title.textContent=suggestion.memory.title;
  const reason=document.createElement("p");reason.textContent=suggestion.reason;
  card.append(title,reason);
  for(const [outcome,label] of [["opened","Open memory"],["dismissed","Not now"]]){
    const button=document.createElement("button");button.textContent=label;
    button.onclick=async()=>{const r=await chrome.runtime.sendMessage({type:"feedback",id:suggestion.id,outcome});if(r.ok){card.replaceChildren();card.className="";document.getElementById("suggestion-example").hidden=false;}else showStatus(r.error,"error");};
    card.append(button);
  }
});


function showPanel(name) {
  for (const panel of ["save", "suggestions"]) {
    document.getElementById(panel + "-panel").hidden = panel !== name;
    document.getElementById(panel + "-tab").setAttribute("aria-selected", String(panel === name));
  }
}
for (const panel of ["save", "suggestions"]) {
  const button = document.getElementById(panel + "-tab");
  button.onclick = () => showPanel(panel);
  button.onkeydown = event => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const next = panel === "save" ? "suggestions" : "save";
    showPanel(next); document.getElementById(next + "-tab").focus();
  };
}
document.getElementById("preview-suggestion").onclick = async () => {
  const button = document.getElementById("preview-suggestion");
  button.disabled = true;
  try {
    const result = await chrome.runtime.sendMessage({type: "preview-suggestion"});
    if (!result?.ok) throw new Error(result?.error || "Could not show the preview.");
    showStatus("Preview shown at the bottom-right of the webpage. Close this popup to see it.", "success");
  } catch(error) { showStatus(error.message, "error"); }
  finally { button.disabled = false; }
};
