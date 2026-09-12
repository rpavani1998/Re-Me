"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import Script from "next/script";
import "./auth.css";
import { Logo } from "./logo";
import { Onboarding } from "./onboarding";

const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const storageKey = "reme-session";
type Identity = { token: string; email: string };
type GoogleAPI = { accounts: { id: {
  initialize: (options: {client_id: string; callback: (result: {credential: string}) => void}) => void;
  renderButton: (element: HTMLElement, options: Record<string, unknown>) => void;
} } };
declare global {
  interface Window {
    google?: GoogleAPI;
  }
}
async function authRequest(path: string, body?: unknown, token?: string) {
  const response = await fetch(base + "/api/auth/" + path, {
    method: body ? "POST" : "GET",
    headers: {"Content-Type": "application/json", ...(token ? {Authorization: `Bearer ${token}`} : {})},
    ...(body ? {body: JSON.stringify(body)} : {}),
  });
  const data = response.status === 204 ? {} : await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please check your email and password.");
  return data;
}

export function GoogleButton({onCredential, onError}: {onCredential: (credential: string) => void; onError: (message: string) => void}) {
  const [clientId, setClientId] = useState("");
  const [ready, setReady] = useState(false);
  const button = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  callback.current = onCredential;
  useEffect(() => { authRequest("config").then(data => setClientId(data.google_client_id)).catch(() => {}); }, []);
  useEffect(() => {
    if (!ready || !clientId || !button.current || !window.google) return;
    window.google.accounts.id.initialize({client_id: clientId, callback: result => callback.current(result.credential)});
    window.google.accounts.id.renderButton(button.current, {type: "standard", theme: "outline", size: "large", text: "continue_with", width: 300});
  }, [ready, clientId]);
  if (!clientId) return null;
  return <div className="google-login"><Script src="https://accounts.google.com/gsi/client" onReady={() => setReady(true)} onError={() => onError("Google sign-in could not load. You can still sign in with email.")}/><div ref={button}/></div>;
}

export function AccountSettings({token, email, onSignedOut}: Identity & {onSignedOut: () => void}) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function logout() {
    setBusy(true);
    try { await authRequest("logout", {}, token); onSignedOut(); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Could not sign out. Try again."); }
    finally { setBusy(false); }
  }
  return <><h2>Account settings</h2><p>Signed in as {email}</p><p>Link your Google account to use either sign-in method.</p><GoogleButton onCredential={credential => {
    authRequest("google/link", {credential}, token).then(() => setMessage("Google account linked.")).catch(e => setMessage(e.message));
  }} onError={setMessage}/>{message && <p role="status">{message}</p>}<button className="primary" disabled={busy} onClick={logout}>Sign out</button></>;
}

function ExtensionStatus({token}: {token: string}) {
  const [status, setStatus] = useState<{connected: boolean; email?: string | null; error?: string}>({connected: false});
  const query = () => window.postMessage({type: "reme-extension-query", requestId: crypto.randomUUID()}, window.location.origin);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin ||
          event.data?.type !== "reme-extension-status" || !event.data.requestId) return;
      setStatus({connected: event.data.connected === true, email: event.data.email, error: event.data.error});
    };
    window.addEventListener("message", receive);
    query();
    return () => window.removeEventListener("message", receive);
  }, []);
  async function connect() {
    const requestId = crypto.randomUUID();
    const result = await new Promise<{ok: boolean; error?: string}>((resolve) => {
      const receive = (event: MessageEvent) => {
        if (event.source !== window || event.origin !== window.location.origin ||
            event.data?.type !== "reme-connect-result" || event.data.requestId !== requestId) return;
        window.removeEventListener("message", receive);
        resolve(event.data);
      };
      window.addEventListener("message", receive);
      window.postMessage({type: "reme-connect-request", requestId, token}, window.location.origin);
      window.setTimeout(() => { window.removeEventListener("message", receive); resolve({ok: false, error: "Re:Me could not connect. Reload the extension, then try again."}); }, 10000);
    });
    if (!result.ok) setStatus(current => ({...current, error: result.error || "Could not connect the extension."}));
    else { setStatus(current => ({...current, error: ""})); query(); }
  }
  return <div className="ext-status" role="status">{status.error ? <span className="ext-error">{status.error}</span> : status.connected
    ? <><span className="ext-dot on"/>Synced with your Chrome extension{status.email ? ` as ${status.email}` : ""}</>
    : <><span className="ext-dot"/>Not connected to your Chrome extension. <button onClick={connect}>Connect extension</button></>}</div>;
}

export function AuthGate({children}: {children: (identity: Identity, signOut: () => void) => ReactNode}) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [loading, setLoading] = useState(true);
  const [signup, setSignup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pairing, setPairing] = useState<{id: string; state: string} | null>(null);
  const [paired, setPaired] = useState(false);
  const [onboarding, setOnboarding] = useState(() => typeof window !== "undefined" && localStorage.getItem("reme-onboarding") === "1");
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const id = query.get("extension"), state = query.get("state");
    if (id && /^[a-p]{32}$/.test(id) && state) setPairing({id, state});
    sessionStorage.removeItem("reme-token");
    const token = localStorage.getItem(storageKey);
    if (!token) { setLoading(false); return; }
    authRequest("me", undefined, token).then(me => setIdentity({token, email: me.email || ""}))
      .catch(() => {localStorage.removeItem(storageKey);})
      .finally(() => setLoading(false));
    const sync = (event: StorageEvent) => { if (event.key === storageKey) window.location.reload(); };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  function signOut() { localStorage.removeItem(storageKey); localStorage.removeItem("reme-onboarding"); setIdentity(null); setPassword(""); setError(""); }
  async function authenticate(path: string, body: unknown) {
    setBusy(true); setError("");
    try {
      const result = await authRequest(path, body);
      localStorage.setItem(storageKey, result.token);
      if (path === "signup") { localStorage.setItem("reme-onboarding", "1"); setOnboarding(true); }
      else localStorage.removeItem("reme-onboarding");
      setIdentity({token: result.token, email: result.email}); setPassword("");
    } catch(e) { setError(e instanceof Error ? e.message : "Could not sign in. Check that the backend is running."); }
    finally { setBusy(false); }
  }
  async function connectExtension() {
    if (!identity || !pairing) return;
    setBusy(true); setError("");
    let extensionToken = "";
    try {
      const result = await authRequest("extension-session", {}, identity.token);
      extensionToken = result.token;
      await new Promise<void>((resolve, reject) => {
        const requestId = crypto.randomUUID();
        const timeout = window.setTimeout(() => {
          window.removeEventListener("message", receive);
          reject(new Error("Re:Me could not connect. Reload the extension at chrome://extensions, then open its settings and click Sign in to Re:Me again."));
        }, 10000);
        function receive(event: MessageEvent) {
          if (event.source !== window || event.origin !== window.location.origin ||
              event.data?.type !== "reme-sign-in-result" || event.data.requestId !== requestId ||
              event.data.extensionId !== pairing?.id) return;
          window.clearTimeout(timeout);
          window.removeEventListener("message", receive);
          if (event.data.ok) resolve();
          else reject(new Error(event.data.error || "Start sign-in again from the extension settings."));
        }
        window.addEventListener("message", receive);
        window.postMessage({type: "reme-sign-in-request", extensionId: pairing.id,
          requestId, state: pairing.state, token: result.token}, window.location.origin);
      });
      setPaired(true);
    } catch(e) {
      if (extensionToken) await authRequest("logout", {}, extensionToken).catch(() => {});
      setError(e instanceof Error ? e.message : "Could not connect the extension.");
    } finally { setBusy(false); }
  }
  if (loading) return <div className="auth-shell"><p>Opening your space…</p></div>;
  if (identity && !pairing) return <>{onboarding && <Onboarding email={identity.email} onDone={() => {localStorage.removeItem("reme-onboarding"); setOnboarding(false);}}/>}<ExtensionStatus token={identity.token}/>{children(identity, signOut)}</>;
  return <div className={`auth-shell ${pairing ? "pairing-screen" : ""}`}><aside className="auth-story" aria-label="Welcome to Re:Me"><div className="auth-wordmark"><Logo/></div><div className="auth-story-copy"><div className="eyebrow">YOUR LIFE. A LITTLE MORE CONNECTED.</div><h1>Good things deserve<br/>a second <em>thought.</em></h1><p>The article. The tiny café. That next big idea.<br/>Keep what matters, and find it when it does.</p><div className="auth-art" aria-hidden="true"><div className="auth-orbit"/><div className="floating-memory"><span>↗</span><div>A place to come back to<small>Saved for someday</small></div><b>✳</b></div><div className="floating-memory second"><span>✧</span><div>Your next big idea<small>Closer than you think</small></div></div><span className="art-dot"/></div></div><p className="auth-story-footer">Less searching. More living.</p></aside><section className="modal auth-card"><div className="brand brand-logo"><Logo/></div>
    {identity ? <><div className="pairing-eyebrow">YOUR BROWSER COMPANION</div><div className={`pairing-mark ${paired ? "connected" : ""}`} aria-hidden="true">{paired ? "✓" : "↗"}</div><h2>{paired ? "You’re connected." : "Your memories, a little closer."}</h2><p>{paired ? "Return to the extension and remember your first page." : "Save the things you find on the web straight to your personal space."}</p><div className="pairing-account"><span className="pairing-avatar">{identity.email.charAt(0).toUpperCase()}</span><div><small>CONNECTING AS</small><span>{identity.email}</span></div></div>{!paired && <button className="primary" disabled={busy} onClick={connectExtension}>{busy ? "Connecting…" : "Connect extension"}</button>}<button className="text-button" onClick={() => {setPairing(null); window.history.replaceState({}, "", "/");}}>Open my memories ↗</button><p className="pairing-footer">Just for you. Always within reach.</p></> : <>
    <h2>{signup ? "Make room for what matters." : "Welcome back."}</h2><p>{signup ? "Create your account to start remembering." : "Sign in to your personal space."}</p>
    <form onSubmit={event => {event.preventDefault(); void authenticate(signup ? "signup" : "login", {email, password});}}>
      <label>Email<input type="email" autoComplete="username" required maxLength={254} value={email} onChange={event => setEmail(event.target.value)}/></label>
      <label>Password<input type="password" autoComplete={signup ? "new-password" : "current-password"} required minLength={signup ? 12 : 1} maxLength={128} value={password} onChange={event => setPassword(event.target.value)}/></label>
      {signup && <small>Use at least 12 characters.</small>}
      <button className="primary" disabled={busy} type="submit">{busy ? "Please wait…" : signup ? "Create account" : "Sign in"}</button>
    </form>
    <GoogleButton onCredential={credential => {void authenticate("google", {credential});}} onError={setError}/>
    <button className="text-button" disabled={busy} onClick={() => {setSignup(!signup); setError("");}}>{signup ? "Already have an account? Sign in" : "New here? Create an account"}</button>
    </>}{error && <p role="alert" className="auth-error">{error}</p>}
  </section></div>;
}
