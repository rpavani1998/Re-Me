import { task, wait } from "@trigger.dev/sdk/v3";

type ReminderPayload = {
  memory_id: string;
  trigger_id: string;
  scheduled_at: string;
  callback_url: string;
  callback_token: string;
};

export const deadlineWakeup = task({
  id: "deadline-wakeup",
  run: async (payload: ReminderPayload) => {
    const url = new URL(payload.callback_url);
    if (url.protocol !== "https:") throw new Error("Reminder callback must use HTTPS");
    const date = new Date(payload.scheduled_at);
    if (!Number.isFinite(date.getTime())) throw new Error("Invalid reminder time");
    await wait.until({ date, idempotencyKey: payload.trigger_id });
    const response = await fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json", Authorization: `Bearer ${payload.callback_token}`},
      body: JSON.stringify({memory_id: payload.memory_id, trigger_id: payload.trigger_id}),
    });
    // Deleted memories no longer need reminders.
    if (response.status === 404) return {cancelled: true};
    if (!response.ok) throw new Error(`Reminder callback failed: ${response.status}`);
    return {ok: true};
  },
});
