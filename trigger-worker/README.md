# Re:Me event reminders

Re:Me extracts event details from saved text and images and places them in the dashboard's Events category. Missing years, timezones, or contradictory dates require confirmation. Confirmed future events queue one reminder one hour before their start (immediately for events starting sooner). Apple Calendar subscriptions contain events without alarms: Re:Me delivers reminders.

## Trigger.dev setup

1. Set the backend `TRIGGER_SECRET_KEY` to the environment-specific Trigger.dev API key.
2. Set backend `PUBLIC_API_URL` to the public HTTPS backend or tunnel URL. Trigger.dev Cloud cannot call `localhost`.
3. In this directory run `npm install`, then set `TRIGGER_PROJECT_REF` to the matching project reference.
4. Run `npx trigger.dev@latest dev` for that project's development environment, or `npx trigger.dev@latest deploy` for production. Match the backend API key's environment to the worker environment.
5. Restart the backend after changing configuration. Its dispatcher retries queued reminders every minute. Failed dispatch does not lose a memory.

The worker receives the callback URL and a per-reminder HMAC credential. No separate `TRIGGER_CALLBACK_TOKEN` configuration is needed for new tasks. Do not log task payloads: they contain callback credentials. Callbacks are checked for ownership, due time, cancellation, and duplicate delivery. A deployment is required; an API key by itself does not install the task.

## Apple Calendar

Open dashboard **Events → Connect Apple Calendar**. In Apple Calendar choose **File → New Calendar Subscription**, paste the private URL, and name it **Re:Me Events**. Set its refresh interval to pick up new events. A localhost subscription works only on the same Mac while Re:Me runs; use the public URL for other devices. Keep the URL private: it grants read-only access to event titles, locations, summaries and dates, not other memories. Rotating the backend signing key invalidates old subscription URLs.

The backend surfaces due reminders in the dashboard. While Chrome and the backend are available, the extension checks every minute, shows a badge and places the reminder in Suggestions even with Context Mode off. This is not an email, phone push, or macOS notification service. If the backend is unavailable when due, Trigger.dev retries callbacks; delivery remains subject to retry limits. Re:Me retains fired reminders for the dashboard's current-suggestion window.
