"use client";
import {useState} from "react";

export function MemoryReminder({reminders, onSchedule, needsConfirmation = false}: {
  needsConfirmation?: boolean;
  reminders?: {id: string; scheduled_at: string; status: string; delivery?: string}[];
  onSchedule: (time: string) => Promise<void>;
}) {
  const [time, setTime] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const upcoming = reminders?.filter(r => r.status === "pending") || [];
  return <section className="reminder-editor"><h3>{upcoming.length ? "I’ll remind you" : "Automatic reminders"}</h3>
    <p>{needsConfirmation ? "Confirm the missing event details above. I’ll choose the reminder time for you." : upcoming.length ? "I’ve chosen a time based on this memory. You can change it below." : "I’ll plan a reminder when there’s a clear future event or deadline. You can also choose your own time."}</p>
    <div aria-live="polite">{upcoming.map(r => <p key={r.id}>{new Date(r.scheduled_at).toLocaleString()}{r.delivery === "needs_setup" && <small>Reminder planned. Delivery is waiting for your reminder service to connect.</small>}</p>)}</div>
    {!needsConfirmation && <details><summary>{upcoming.length ? "Change reminder time" : "Choose a time instead"}</summary>
    <form onSubmit={async e => {
      e.preventDefault(); setBusy(true); setError("");
      try {
        const date = new Date(time);
        if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) throw new Error("Choose a future reminder time.");
        await onSchedule(date.toISOString()); setTime("");
      } catch (e) {setError(e instanceof Error ? e.message : "Could not schedule reminder.");}
      finally {setBusy(false);}
    }}>
      <label>Remind me at<input type="datetime-local" required value={time} onChange={e => setTime(e.target.value)}/></label>
      <small>Your timezone: {Intl.DateTimeFormat().resolvedOptions().timeZone}.</small>
      <button className="primary" disabled={busy}>{busy ? "Scheduling…" : "Set reminder"}</button>
    </form></details>}
    {error && <p role="alert">{error}</p>}

  </section>;
}
