import httpx
import hmac
import hashlib
from urllib.parse import urlparse

TRIGGER_API = "https://api.trigger.dev"


def hosted_trigger_ready(config):
    """Return whether this process can safely ask Trigger.dev to call it back.

    Trigger.dev runs outside the local network.  Scheduling it without a public
    HTTPS callback URL creates a reminder that can never
    be delivered, so a key and reachable HTTPS URL are required.
    """
    callback_url = (config.public_api_url or "").strip()
    parsed = urlparse(callback_url)
    return bool(
        (config.trigger_secret_key or "").strip()
        and parsed.scheme == "https"
        and parsed.netloc
    )


def schedule_wakeup(config, task="deadline-wakeup", *, memory_id, trigger_id, scheduled_at):
    if not hosted_trigger_ready(config):
        return None
    body = {
        "payload": {"memory_id": memory_id, "trigger_id": trigger_id, "scheduled_at": scheduled_at.isoformat(),
                    "callback_url": config.public_api_url.rstrip("/") + "/api/triggers/callback",
                    "callback_token": callback_signature(config, memory_id, trigger_id)},
        "options": {"idempotencyKey": trigger_id},
    }
    response = httpx.post(f"{TRIGGER_API}/api/v1/tasks/{task}/trigger", json=body,
                          headers={"Authorization": "Bearer " + config.trigger_secret_key}, timeout=15)
    response.raise_for_status()
    data = response.json()
    return data.get("runId") or data.get("id") or (data.get("run") or {}).get("id")


def callback_signature(config, memory_id, trigger_id):
    return hmac.new(config.trigger_secret_key.encode(),
                    f"reme-reminder:{memory_id}:{trigger_id}".encode(), hashlib.sha256).hexdigest()
