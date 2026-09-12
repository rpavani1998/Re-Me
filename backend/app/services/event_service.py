"""Grounded event details and durable reminder scheduling."""
from datetime import datetime, timedelta, timezone
from app.domain.models import Action, Trigger, now


def timestamp(value):
    if not value:
        return None
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value if value.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def prepare_event(db, memory, raw, event, *, user_confirmed=False):
    if not event:
        return
    details = event.model_dump()
    metadata = details.get('metadata')
    if metadata:
        missing = list(metadata['missing_fields'])
        for field in ('year', 'month', 'day', 'start_time', 'end_time', 'timezone'):
            if not metadata.get(field) and field not in missing:
                missing.append(field)
        metadata['missing_fields'] = missing
    if not user_confirmed and metadata and metadata.get('missing_fields'):
        details['needs_confirmation'] = True
        details['clarification'] = details['clarification'] or ('Confirm: ' + ', '.join(metadata['missing_fields']) + '.')
    start, end = timestamp(details['starts_at']), timestamp(details['ends_at'])
    if not start or (details['ends_at'] and (not end or end <= start)):
        details['needs_confirmation'] = True
        details['clarification'] = details['clarification'] or 'Confirm the date, year, time, and timezone.'
    raw.payload = {**raw.payload, 'event': details}
    memory.event_date = start if not details['needs_confirmation'] else None
    db.add(Action(user_id=memory.user_id, memory_id=memory.id, type='add_to_calendar',
                  status='needs_confirmation' if details['needs_confirmation'] else 'ready', payload=details))
    if not details['needs_confirmation'] and start > now():
        # Default: one hour before; near-term events are surfaced immediately.
        reminder_at = max(start - timedelta(hours=1), now())
        db.add(Trigger(user_id=memory.user_id, memory_id=memory.id, scheduled_at=reminder_at,
                       external_reference='awaiting-trigger'))
