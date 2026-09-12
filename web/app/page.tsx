"use client";
import { useEffect, useRef, useState } from "react";
import "./dashboard.css";
import { EventDetails, type SavedEvent } from "../components/event-details";
import { MemoryReminder } from "../components/memory-reminder";
import { MemoryCard } from "../components/memory-card";
import { MemoryPreview } from "../components/memory-preview";
import { Logo } from "../components/logo";
import { AuthGate, AccountSettings } from "../components/auth";
import { ArrowUpRight, Plus, Sparkles, Clock3, Layers3, BookOpen, Settings, X, Check, Search, Link as LinkIcon, Leaf, ChevronRight, ChevronLeft, CircleDot, Grid2X2, LayoutGrid, SlidersHorizontal, Trash2, AlarmClock } from "lucide-react";

type Memory = { event?: SavedEvent | null; reminders?: {id: string; scheduled_at: string; status: string}[]; source_type?: string; saved_excerpt?: string; image_url?: string | null; reading_status?: string; id: string; type: string; title: string; summary: string; intent: string | null; topics: string[]; possible_actions: {type: string; label: string}[]; source_url: string | null; created_at: string; captured_at: string; deadline: string | null; event_date: string | null; entities: {id: string; name: string; type: string}[]; interpretation_provider: string; raw_capture?: Record<string, unknown>; episodes?: {id: string; event_type: string; occurred_at: string; context: Record<string, unknown>}[] };
type Suggestion = {id: string; reason: string; suggested_action: string; memory: Memory; matches?: Memory[]};
type Discovery = {title: string; url: string; summary: string; external: true};
type DraftAction = {id: string; status: "awaiting_approval" | "completed"; result: {subject: string; body: string} | null};
const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const stamp = (s: string) => new Date(s).toLocaleDateString(undefined, {month:"short",day:"numeric"});
const icons: Record<string, string> = {restaurant:"↗", opportunity:"✧", place:"⌁", article:"≋"};

export default function Home() {
  return <AuthGate>{(identity, signOut) => <Dashboard key={identity.token} {...identity} onSignedOut={signOut}/>}</AuthGate>;
}

function Dashboard({token, email, onSignedOut}: {token: string; email: string; onSignedOut: () => void}) {
  const [calendarFeed, setCalendarFeed] = useState<{url: string; public: boolean} | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pendingSaves, setPendingSaves] = useState<{id: string; title: string; status: string}[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [selected, setSelected] = useState<Memory | null>(null);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [demo, setDemo] = useState(false);
  const [healthy, setHealthy] = useState(false);
  const [compact, setCompact] = useState(false);
  const [sort, setSort] = useState("newest");
  const [filter, setFilter] = useState("All memories");
  const [query, setQuery] = useState("");
  const [section, setSection] = useState("Your space");
  const [contextEnabled, setContextEnabled] = useState(false);
  const [activity, setActivity] = useState("");
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [recallIndex, setRecallIndex] = useState(0);
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [draftAction, setDraftAction] = useState<DraftAction | null>(null);
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [reminderDraft, setReminderDraft] = useState<{scheduledAt: string} | null>(null);
  const [reminderNote, setReminderNote] = useState("");

  async function api(path: string, body?: unknown, method?: string) {
    const response = await fetch(base + path, {method: method || (body ? "POST" : "GET"), headers: {Authorization: `Bearer ${token}`, "Content-Type":"application/json"}, ...(body ? {body:JSON.stringify(body)} : {})});
    if (response.status === 401) { onSignedOut(); throw new Error("Your session expired. Please sign in again."); }
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map((item: {msg: string}) => item.msg).join("; ") : typeof data.detail === "string" ? data.detail : data.detail?.message || "The request could not be completed.");
    return data;
  }
  async function refresh() {
    const [memories, pending] = await Promise.all([api("/api/memories"), api("/api/captures/pending")]);
    setMemories(memories); setPendingSaves(pending.filter((item: {id: string}) => !memories.some((memory: {raw_capture_id: string}) => memory.raw_capture_id === item.id)));
  }
  async function refreshContext() {
    const [ctx, relevance] = await Promise.all([api("/api/context/current"), api("/api/relevance/current")]);
    setContextEnabled(ctx.enabled); setActivity(ctx.session?.activity || ""); setSuggestion(relevance.suggestion); setRecallIndex(0);
  }
  useEffect(() => {if (!token) return; refreshContext().catch(e => setError(e.message)); const interval = setInterval(() => refreshContext().catch(() => {}), 15000); return () => clearInterval(interval);}, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!token) return;
    api("/api/context/current").then(ctx => {
      if (!ctx.enabled) api("/api/context/mode", {enabled:true}, "PUT").then(() => refreshContext()).catch(() => {});
      else setContextEnabled(true);
    }).catch(() => {});
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  async function simulate(kind: string) {
    await api("/api/context/mode", {enabled:true}, "PUT");
    const title = kind === "restaurant" ? "Best Korean restaurants Hyderabad" : "Planning a Japan trip Tokyo Kyoto itinerary";
    await api("/api/context/events", {events:[0,1].map(i => ({event_type:"PAGE_ENTERED", source_url:`https://example.com/demo-context/${kind}/${i}`, page_title:title, dwell_seconds:20}))});
    await api("/api/relevance/evaluate", {}); await refreshContext();
  }
  async function feedback(outcome: string) {
    if (!suggestion) return;
    const items = [suggestion.memory, ...(suggestion.matches || [])];
    const memory = items[Math.min(recallIndex, items.length - 1)];
    await api(`/api/relevance/${suggestion.id}/feedback`, {outcome}); setSuggestion(null);
    if (outcome === "opened") await inspect(memory);
  }
  useEffect(() => { if (!token) return; refresh().catch(e => setError(e.message)); fetch(base + "/health").then(r => r.json()).then(h => {setDemo(h.demo_mode); setHealthy(true);}).catch(() => setError("Cannot reach Re:Me. Start the backend and check the API URL.")); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  const deepLinked = useRef(false);
  useEffect(() => {
    if (deepLinked.current || !token) return;
    const id = new URLSearchParams(window.location.search).get("memory");
    if (!id) return;
    const match = memories.find(m => m.id === id);
    if (!match) return;
    deepLinked.current = true;
    inspect(match).catch(() => setError("Could not open the recalled memory."));
    history.replaceState(null, "", "/");
  }, [memories, token]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!token) return;
    let pending = false;
    const update = async () => {
      if (document.visibilityState !== "visible" || pending) return;
      pending = true;
      try { await refresh(); }
      catch (error) { setError(error instanceof Error ? error.message : "Could not refresh your memories."); }
      finally { pending = false; }
    };
    // Extension captures happen outside this tab. Refresh when users return,
    // and keep a visible dashboard current when both windows remain open.
    window.addEventListener("focus", update);
    document.addEventListener("visibilitychange", update);
    const interval = window.setInterval(update, 5000);
    return () => {
      window.removeEventListener("focus", update);
      document.removeEventListener("visibilitychange", update);
      window.clearInterval(interval);
    };
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  async function perform(fn: () => Promise<void>) { setBusy(true); setError(""); try { await fn(); } catch(e) {setError(e instanceof Error ? e.message : "Something went wrong.");} finally {setBusy(false);} }
  async function inspect(m: Memory) { await perform(async () => { setDone({}); setReminderDraft(null); setReminderNote(""); setSelected(await api(`/api/memories/${m.id}`)); }); }
  async function runAction(memory: Memory, action: {type: string; label: string}) {
    if (action.type === "open" && memory.source_url) { window.open(memory.source_url, "_blank", "noopener"); return; }
    if (action.type === "draft_email") { await requestDraft(memory); return; }
    if (action.type === "reminder") {
      const target = memory.deadline || memory.event_date || (memory.raw_capture?.captured_at ? new Date(new Date(memory.raw_capture.captured_at as string).getTime() + 86400000).toISOString() : new Date(Date.now() + 86400000).toISOString());
      setReminderDraft({scheduledAt: toLocalInput(new Date(target))});
      return;
    }
    setDone(current => ({...current, [action.label]: !current[action.label]}));
  }
  const toLocalInput = (d: Date) => { const p = (n: number) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
  async function confirmReminder(memory: Memory) {
    if (!reminderDraft?.scheduledAt) return;
    await perform(async () => {
      const when = new Date(reminderDraft.scheduledAt);
      const reminder = await api(`/api/memories/${memory.id}/reminders`, {scheduled_at: when.toISOString()});
      setDone(current => ({...current, "Remind me": true}));
      setReminderNote(`Reminder set for ${when.toLocaleString(undefined, {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"})}`);
      setReminderDraft(null);
    });
  }
  async function deleteSelected() {
    if (!selected || !window.confirm(`Delete “${selected.title}”? Its saved content, reminders, and related history will be permanently removed.`)) return;
    const memoryId = selected.id;
    await perform(async () => {
      await api(`/api/memories/${memoryId}`, undefined, "DELETE");
      setMemories(current => current.filter(memory => memory.id !== memoryId));
      setSuggestion(current => current?.memory.id === memoryId ? null : current);
      setSelected(null); setDiscoveries([]); setDraftAction(null);
      setFilter("All memories");
      await refresh();
    });
  }
  async function discover(memory: Memory) { await perform(async () => setDiscoveries((await api(`/api/memories/${memory.id}/discover`)).suggestions)); }
  async function requestDraft(memory: Memory) { await perform(async () => setDraftAction(await api(`/api/memories/${memory.id}/actions`))); }
  async function approveDraft() { if (!draftAction) return; await perform(async () => setDraftAction(await api(`/api/actions/${draftAction.id}/approve`))); }
  const topics = Array.from(new Set(memories.flatMap(m => m.topics)));
  const visible = memories.filter(m => (filter === "All memories" || m.topics.includes(filter)) && `${m.title} ${m.summary} ${m.topics.join(" ")} ${m.entities.map(e => e.name).join(" ")}`.toLowerCase().includes(query.toLowerCase()) && (section !== "Events" || !!m.event) && (section !== "Coming up" || (m.deadline && new Date(m.deadline) > new Date()))).sort((a, b) => (sort === "newest" ? -1 : 1) * (new Date(a.captured_at || a.created_at).getTime() - new Date(b.captured_at || b.created_at).getTime()));
  return <div className={`app-shell mind-dashboard ${compact ? "compact-board" : ""}`}>
    <header className="board-header">
      <a className="board-logo" href="/" aria-label="Re:Me home"><Logo/></a>
      <label className="board-search"><Search size={20}/><input aria-label="Search memories" placeholder="Search for something on your mind…" value={query} onChange={e => setQuery(e.target.value)}/>{query && <button aria-label="Clear search" onClick={() => setQuery("")}><X size={17}/></button>}</label>
      <div className="board-actions"><button className="board-save" onClick={() => setCaptureOpen(true)}><Plus size={19}/><span>Save something</span></button><button className="board-account" aria-label="Account settings" title={email} onClick={() => setSettingsOpen(true)}>{email.charAt(0).toUpperCase() || "Y"}</button></div>
    </header>
    <main>
      <div className="page-content">
        <div className="board-intro"><div><div className="eyebrow">A SPACE THAT’S ENTIRELY YOURS</div><h1>{query ? "A little closer to what you’re looking for." : section === "Coming up" ? "Good things on the horizon." : section === "Contexts" ? "See where your ideas connect." : <>Everything you didn’t want to <em>forget.</em></>}</h1><p>Little discoveries, big ideas, and everything in between.</p></div><span className="board-private"><span/>Only for you</span></div>
        <div className="board-toolbar"><nav aria-label="Memory views">{[["Your space", "Everything"], ["All memories", "All memories"], ["Events", "Events"], ["Coming up", "Coming up"], ["Contexts", "Spaces"]].map(([value, label]) => <button key={value} aria-current={section === value ? "page" : undefined} className={section === value ? "active" : ""} onClick={() => {setSection(value); setFilter("All memories");}}>{label}</button>)}</nav><div className="board-view-controls"><label><span className="sr-only">Sort memories</span><select value={sort} onChange={e => setSort(e.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label><button aria-label={compact ? "Use spacious cards" : "Use compact cards"} aria-pressed={compact} onClick={() => setCompact(!compact)}>{compact ? <LayoutGrid size={18}/> : <Grid2X2 size={18}/>}</button></div></div>
        {error && <div role="alert" className="error">{error}<button aria-label="Dismiss error" onClick={() => setError("")}><X size={16}/></button></div>}
        <details className="recall-settings"><summary><SlidersHorizontal size={14}/>Recall settings{contextEnabled && <span className="recall-active">Context on</span>}{demo && <span className="board-demo">Demo</span>}</summary><div className="recall-settings-body">
        <div className="context-bar"><span>{activity || "Your memories can wait for the right moment."}</span><button className={`context-toggle ${contextEnabled ? "on" : ""}`} role="switch" aria-checked={contextEnabled} onClick={() => perform(async () => {await api("/api/context/mode", {enabled:!contextEnabled}, "PUT"); await refreshContext();})}>Context Mode <strong>{contextEnabled ? "ON" : "OFF"}</strong></button></div>
        <p className="context-privacy">Re:Me uses the pages you’re actively viewing to understand what you’re currently doing. It does not scan your complete browser history. Enable collection in the extension too.</p>
        {healthy && <div className="demo-controls"><span>DEMO · NOTIFICATIONS</span><button disabled={busy} onClick={() => perform(() => simulate("restaurant"))}>Context: choosing a restaurant</button><button disabled={busy} onClick={() => perform(() => simulate("japan"))}>Context: planning Japan</button><button disabled={busy} onClick={() => perform(async () => {await api("/api/demo/reminder", {}); await refreshContext();})}>Scheduled reminder</button>{demo && <button disabled={busy} onClick={() => {if (window.confirm("Reset all memories in this development demo?")) perform(async () => {await api("/api/demo/reset", {}); await api("/api/demo/seed", {}); await refresh(); await refreshContext();});}}>Reset & seed demo</button>}</div>}
        </div></details>
        {suggestion && (() => { const items = [suggestion.memory, ...(suggestion.matches || [])]; const active = items[Math.min(recallIndex, items.length - 1)]; return <section className="recall-card"><div className="eyebrow">A MEMORY FOR THIS MOMENT</div><h2>{active.title}</h2><p>{recallIndex === 0 ? suggestion.reason : `You saved ${active.title} earlier. It fits what you’re exploring now.`}</p><div className="recall-actions"><button className="primary" disabled={busy} onClick={() => perform(() => feedback("opened"))}>Rediscover this<ArrowUpRight size={15}/></button><button disabled={busy} onClick={() => perform(() => feedback("dismissed"))}>Not now</button></div>{items.length > 1 && <div className="recall-carousel"><div className="recall-steps">{items.map((item, i) => <button key={item.id} aria-label={`Show ${item.title}`} aria-current={i === recallIndex ? "step" : undefined} onClick={() => setRecallIndex(i)}/>)}</div><div className="recall-nav"><button aria-label="Previous suggestion" disabled={recallIndex === 0} onClick={() => setRecallIndex(i => Math.max(0, i - 1))}><ChevronLeft size={16}/></button><span>{recallIndex + 1} of {items.length}</span><button aria-label="Next suggestion" disabled={recallIndex >= items.length - 1} onClick={() => setRecallIndex(i => Math.min(items.length - 1, i + 1))}><ChevronRight size={16}/></button></div></div>}</section>; })()}
        {section === "Events" && <section className="reminder-editor"><h3>Re:Me Events</h3><p>Events found in your images, links, and notes. Confirm missing dates before they reach your calendar.</p><button className="secondary" disabled={busy} onClick={() => perform(async () => setCalendarFeed(await api("/api/calendar/subscription")))}>Connect Apple Calendar</button>{calendarFeed && <div><p>In Apple Calendar, choose File → New Calendar Subscription and paste this private URL. Name the calendar Re:Me Events.</p><input readOnly aria-label="Private calendar subscription URL" value={calendarFeed.url} onFocus={e => e.target.select()}/><p>{calendarFeed.public ? "Events update when Apple Calendar refreshes this subscription." : "This localhost feed works only on this Mac while the backend runs. A public HTTPS URL is needed for other devices and Trigger.dev reminders."}</p></div>}</section>}
        {section === "Contexts" && <div className="collections">{topics.map(t => <button key={t} onClick={() => {setFilter(t); setSection("All memories");}}><Layers3 size={21}/><h3>{t}</h3><p>{memories.filter(m => m.topics.includes(t)).length} connected memories</p><ChevronRight size={18}/></button>)}{topics.length === 0 && <p>Connections will emerge from the things you remember.</p>}</div>}
        <section className="memory-section" aria-label="Saved memories"><div className="board-results"><span>{query ? `${visible.length} ${visible.length === 1 ? "match" : "matches"}` : `${visible.length} things worth keeping`}</span>{(query || filter !== "All memories") && <button onClick={() => {setQuery(""); setFilter("All memories");}}>Clear filters<X size={12}/></button>}</div>
        <div className="filters">{["All memories", ...topics.slice(0, 6)].map(t => <button key={t} className={filter === t ? "selected" : ""} onClick={() => setFilter(t)}>{t}</button>)}</div>
        {pendingSaves.length > 0 && <div className="pending-saves" aria-live="polite">{pendingSaves.map(item => <div className="pending-save" key={item.id}><div><strong>{item.title}</strong><p>{item.status === "failed" ? "Saved safely. Understanding failed; try again." : "Saved. Reading and understanding in the background…"}</p></div>{item.status === "failed" ? <button disabled={busy} onClick={() => perform(async () => {await api(`/api/captures/${item.id}/retry`, {}); await refresh();})}>Retry</button> : <Clock3 size={17}/>}</div>)}</div>}
        <div className="memory-grid">{visible.map((m, index) => <MemoryCard key={m.id} memory={m} index={index} onOpen={() => inspect(m)}/>)}</div>
        {visible.length === 0 && pendingSaves.length === 0 && <div className="empty"><BookOpen size={32}/><h3>{memories.length ? "Nothing here just yet." : "It starts with something you care about."}</h3><p>Save a page, a place, or a thought. A little collection of you starts here.</p><button className="secondary" onClick={() => setCaptureOpen(true)}>Keep your first thing<Plus size={15}/></button>{demo && <button className="text-button" disabled={busy} onClick={() => perform(async () => {await api("/api/demo/seed", {}); await refresh();})}>Load the demo memories</button>}</div>}
        </section><footer><span className="mini-brand"><Logo/></span><span>Remembered with intention. Returned with care.</span><span>Made for a life beyond tabs.</span></footer>
      </div>
    </main>
    {settingsOpen && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Account settings"><button className="close" aria-label="Close settings" onClick={() => setSettingsOpen(false)}><X/></button><AccountSettings token={token} email={email} onSignedOut={onSignedOut}/></section></div>}
    {captureOpen && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="capture-title"><button className="close" aria-label="Close capture" onClick={() => setCaptureOpen(false)}><X/></button><div className="eyebrow">MAKE A LITTLE ROOM</div><h2 id="capture-title">Keep this.</h2><p>Anything worth keeping — a link, a photo, a video, an audio clip, a tweet, a thought. No folders to choose.</p><form onSubmit={e => {e.preventDefault(); const form = new FormData(e.currentTarget); perform(async () => {await api("/api/captures?background=true", {source_type: form.get("url") ? "webpage" : "thought", source_url: form.get("url") || null, page_title: form.get("title"), visible_text: form.get("text") || form.get("title"), user_note: form.get("note") || null}); await refresh(); setCaptureOpen(false);});}}><label>Title<input name="title" maxLength={500} placeholder="What caught your eye?" required/></label><label>Link, photo, video, or audio <span>optional</span><input name="url" type="url" placeholder="https://…"/></label><label>Article, tweet, note, or a description<textarea name="text" maxLength={16000} placeholder="Paste the article or tweet text, or describe what you’re keeping and why it matters."/></label><label>Why it matters <span>optional</span><input name="note" maxLength={2000} placeholder="I’d love to try this sometime"/></label><button className="primary" disabled={busy || !token}>{busy ? "Keeping…" : "Keep this for me"}<Sparkles size={17}/></button></form></section></div>}
    {selected && <div className="modal-backdrop"><section className="modal detail" role="dialog" aria-modal="true" aria-labelledby="detail-title"><button className="close" aria-label="Close memory" onClick={() => {setSelected(null);setDiscoveries([]);setDraftAction(null);}}><X/></button><div className="eyebrow">{selected.type} · REMEMBERED {stamp(selected.captured_at || selected.created_at)}</div><MemoryPreview url={selected.image_url}/><h2 id="detail-title">{selected.title}</h2><p>{selected.summary}</p>{selected.reading_status === "unavailable" && <p className="reading-notice">This website could not be read. This memory uses only the link and details you supplied.</p>}{selected.intent && <div className="intent-note">{selected.intent.replace("want_to_", "You wanted to ").replaceAll("_", " ")}</div>}<div className="tags">{selected.entities.map(e => <span key={e.id}>{e.name}</span>)}</div>{selected.deadline && <p>Deadline: {stamp(selected.deadline)}</p>}{selected.source_url && <a className="primary" href={selected.source_url} target="_blank" rel="noopener noreferrer">Open original<ArrowUpRight size={17}/></a>}{selected.possible_actions?.length > 0 && <section className="actionables"><div className="eyebrow">ACTIONABLE ITEMS</div><ul>{selected.possible_actions.filter(action => action.type !== "reminder").map((action, i) => <li key={`${selected.id}-${i}`} className={done[action.label] ? "done" : ""}><button disabled={busy} onClick={() => runAction(selected, action)}><span className="action-check" aria-hidden="true">{done[action.label] ? <Check size={13}/> : ""}</span>{action.label}</button><small>{action.type.replaceAll("_", " ")}</small></li>)}</ul>{reminderDraft && <div className="reminder-row"><label>Remind me<AlarmClock size={14}/><input type="datetime-local" aria-label="Reminder time" value={reminderDraft.scheduledAt} onChange={e => setReminderDraft({scheduledAt: e.target.value})}/></label><button className="primary" disabled={busy || !reminderDraft.scheduledAt} onClick={() => confirmReminder(selected)}>Set reminder<Check size={15}/></button></div>}{reminderNote && <p className="reminder-note">{reminderNote} — a reminder card will surface on the dashboard.</p>}</section>}<div className="detail-actions"><button className="secondary" disabled={busy} onClick={() => discover(selected)}>Find related ideas</button>{selected.possible_actions?.some?.((a: {type: string}) => a.type === "draft_email") && !draftAction && <button className="secondary" disabled={busy} onClick={() => requestDraft(selected)}>Help me apply</button>}</div>{discoveries.length > 0 && <section className="external-results"><div className="eyebrow">EXTERNAL SUGGESTIONS</div>{discoveries.map(item => <a className="discovery-result" key={item.url} href={item.url} target="_blank" rel="noopener noreferrer"><strong>{item.title}</strong><p>{item.summary}</p><small>External source <ArrowUpRight size={12}/></small></a>)}</section>}{draftAction && <section className="draft-card"><div className="eyebrow">APPROVAL REQUIRED</div>{draftAction.status === "awaiting_approval" ? <><p>Create an editable email draft from this saved opportunity. Nothing will be sent.</p><button className="primary" disabled={busy} onClick={approveDraft}>Create draft<Check size={15}/></button></> : <><h3>{draftAction.result?.subject}</h3><textarea aria-label="Editable email draft" defaultValue={draftAction.result?.body}/><small>This is a draft only. Re:Me has not sent anything.</small></>}</section>}{selected.event && <EventDetails key={selected.id + String(selected.event.needs_confirmation)} event={selected.event} onConfirm={async event => {await api(`/api/calendar/events/${selected.id}`, event, "PUT"); setSelected(await api(`/api/memories/${selected.id}`)); await refresh();}}/>}{(!!selected.event || !!selected.deadline || selected.source_type === "image" || selected.possible_actions.some(a => a.type === "reminder")) && <MemoryReminder key={selected.id} needsConfirmation={selected.event?.needs_confirmation} reminders={selected.reminders} onSchedule={async scheduled_at => {await api(`/api/memories/${selected.id}/reminders`, {scheduled_at}); setSelected(await api(`/api/memories/${selected.id}`));}}/>}<h3>The story so far</h3><div className="timeline">{selected.episodes?.map(e => <div key={e.id}><span/><div><strong>{e.event_type.replaceAll("_", " ")}</strong><small>{stamp(e.occurred_at)}</small></div></div>)}</div><details><summary>Original capture</summary><pre>{JSON.stringify(selected.raw_capture, null, 2)}</pre></details><small>Understanding: {selected.interpretation_provider}</small><div className="delete-memory-row"><button className="delete-memory" disabled={busy} onClick={deleteSelected}><Trash2 size={15}/>Delete memory</button><span>This cannot be undone.</span></div></section></div>}
  </div>;
}
