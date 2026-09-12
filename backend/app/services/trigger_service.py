from datetime import timedelta
from sqlalchemy import select
from app.domain.models import Trigger, now
from app.integrations.trigger_client import hosted_trigger_ready, schedule_wakeup
from app.core.logging import event


def schedule_if_deadline(db, user_id, memory, config):
    if not memory.deadline or memory.deadline <= now():
        return None
    existing = db.scalar(select(Trigger).where(Trigger.memory_id == memory.id, Trigger.status == "pending"))
    if existing:
        return existing
    trigger = Trigger(user_id=user_id, memory_id=memory.id, scheduled_at=max(memory.deadline - timedelta(days=1), now()))
    db.add(trigger)
    db.flush()
    # Persist an outbox entry; network failures must not roll back the memory.
    trigger.external_reference = "awaiting-trigger" if not getattr(config, "demo_mode", False) else f"simulated:{trigger.id}"
    db.flush()
    return trigger


def deliver_due_reminders(db):
    """Deliver explicitly scheduled reminders even when context observation is off."""
    from app.domain.models import RelevanceEvent, Episode
    reminders = db.scalars(select(Trigger).where(
        Trigger.status == "pending", Trigger.external_reference == "local-reminder",
        Trigger.scheduled_at <= now()).with_for_update(skip_locked=True)).all()
    for reminder in reminders:
        reminder.status = "fired"
        db.add(RelevanceEvent(user_id=reminder.user_id, memory_id=reminder.memory_id,
            trigger_id=reminder.id, relevance_score=1,
            reason="It’s time for the reminder you scheduled.", suggested_action="open"))
        db.add(Episode(user_id=reminder.user_id, memory_id=reminder.memory_id,
            event_type="reminder_fired", context={"trigger_id": reminder.id}))
    db.commit()


def dispatch_reminders(db, config):
    if not hosted_trigger_ready(config):
        return
    pending = db.scalars(select(Trigger).where(Trigger.status == "pending",
        Trigger.external_reference.in_(["awaiting-trigger", "local-reminder"])).with_for_update(skip_locked=True)).all()
    for reminder in pending:
        try:
            run_id = schedule_wakeup(config, memory_id=reminder.memory_id,
                trigger_id=reminder.id, scheduled_at=reminder.scheduled_at)
            if run_id:
                reminder.external_reference = run_id
        except Exception:
            # A stable trigger ID makes retrying safe after timeouts or restarts.
            event("TRIGGER_DISPATCH_RETRY", trigger_id=reminder.id)
    db.commit()
