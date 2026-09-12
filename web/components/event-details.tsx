"use client";
import {useState} from "react";
export type SavedEvent = {title: string; date_text: string; location: string | null; starts_at: string | null; ends_at: string | null; needs_confirmation: boolean; clarification: string | null};
export function EventDetails({event, onConfirm}: {event: SavedEvent; onConfirm: (event: SavedEvent) => Promise<void>}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  return <section className="reminder-editor"><h3>{event.title}</h3><p>{event.date_text}{event.location ? ` · ${event.location}` : ""}</p>
    {event.needs_confirmation ? <><p>{event.clarification || "Confirm the event date, year, and timezone."}</p>
      <form onSubmit={async e => {e.preventDefault(); const form = new FormData(e.currentTarget); setBusy(true); setError("");
        try {await onConfirm({...event, starts_at: new Date(String(form.get("start"))).toISOString(), ends_at: form.get("end") ? new Date(String(form.get("end"))).toISOString() : null, needs_confirmation: false, clarification: null});}
        catch(e) {setError(e instanceof Error ? e.message : "Could not confirm event.");} finally {setBusy(false);}
      }}><label>Event starts<input name="start" type="datetime-local" required/></label><label>Event ends (optional)<input name="end" type="datetime-local"/></label><small>Timezone: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Choose times in this timezone.</small><button className="primary" disabled={busy}>Confirm event & reminder</button></form></> : <p>Ready for your Re:Me Events calendar. Future events get a reminder one hour before they start, or immediately if sooner.</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
