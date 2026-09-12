"""Private read-only Apple Calendar subscription and confirmed event dates."""
import hashlib
import hmac
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from app.api.dependencies import db_session, user
from app.domain.models import Memory, RawCapture, User, Action, Trigger
from app.domain.schemas import EventDetails
from app.repositories.memories import owned
from app.services.event_service import timestamp, prepare_event

router = APIRouter(prefix='/api/calendar')


def feed_token(config, user_id):
    key = config.trigger_secret_key or config.api_token
    if not key:
        raise HTTPException(503, 'Configure the Trigger.dev API key before connecting Apple Calendar.')
    return hmac.new(key.encode(), f'reme-calendar:{user_id}'.encode(), hashlib.sha256).hexdigest()


def escape(text):
    return str(text or '').replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold(line):
    chunks, current = [], ''
    for char in line:
        if len((current + char).encode('utf-8')) > 73:
            chunks.append(current)
            current = ' '
        current += char
    return '\r\n'.join(chunks + [current])


def calendar_text(db, user_id):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ReMe//Events//EN',
             'X-WR-CALNAME:Re:Me Events', 'CALSCALE:GREGORIAN']
    rows = db.execute(select(Memory, RawCapture).join(RawCapture, Memory.raw_capture_id == RawCapture.id).where(Memory.user_id == user_id))
    stamp = lambda dt: dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for memory, raw in rows:
        event = raw.payload.get('event')
        if not event or event.get('needs_confirmation'):
            continue
        start, end = timestamp(event.get('starts_at')), timestamp(event.get('ends_at'))
        if not start:
            continue
        lines += ['BEGIN:VEVENT', f'UID:{memory.id}@reme', 'DTSTAMP:' + stamp(datetime.now(timezone.utc)),
                  'DTSTART:' + stamp(start), 'SUMMARY:' + escape(event.get('title') or memory.title),
                  'DESCRIPTION:' + escape(memory.summary), 'LOCATION:' + escape(event.get('location')),
                  'CATEGORIES:ReMe Events']
        if end and end > start:
            lines.append('DTEND:' + stamp(end))
        lines.append('END:VEVENT')
    return '\r\n'.join(fold(line) for line in lines + ['END:VCALENDAR']) + '\r\n'


@router.get('/subscription')
def subscription(request: Request, user_id=Depends(user)):
    from urllib.parse import quote
    config = request.app.state.config
    url = f'{config.public_api_url.rstrip("/")}/api/calendar/feed/{quote(user_id, safe="")}.ics?token={feed_token(config, user_id)}'
    return {'url': url, 'name': 'Re:Me Events', 'public': config.public_api_url.startswith('https://')}


@router.get('/feed/{user_id}.ics')
def feed(user_id: str, token: str, request: Request, db=Depends(db_session)):
    if not hmac.compare_digest(token, feed_token(request.app.state.config, user_id)) or not db.get(User, user_id):
        raise HTTPException(401, 'Invalid calendar subscription')
    return Response(calendar_text(db, user_id), media_type='text/calendar', headers={'Cache-Control': 'private, no-store'})


@router.put('/events/{memory_id}')
def confirm_event(memory_id: str, body: EventDetails, db=Depends(db_session), user_id=Depends(user)):
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    memory = owned(db, Memory, memory_id, user_id)
    if body.needs_confirmation or not timestamp(body.starts_at):
        raise HTTPException(422, 'Confirm a full date and timezone.')
    if body.ends_at and (not timestamp(body.ends_at) or timestamp(body.ends_at) <= timestamp(body.starts_at)):
        raise HTTPException(422, 'Event end must be after its start.')
    raw = db.get(RawCapture, memory.raw_capture_id)
    if raw.payload.get('event') == body.model_dump():
        return {'event': raw.payload['event']}
    # Supersede old reminders; their cloud callbacks must not fire.
    for reminder in db.scalars(select(Trigger).where(Trigger.memory_id == memory_id, Trigger.status == 'pending')):
        reminder.status = 'cancelled'
    for action in db.scalars(select(Action).where(Action.memory_id == memory_id, Action.type == 'add_to_calendar')):
        db.delete(action)
    prepare_event(db, memory, raw, body, user_confirmed=True)
    db.commit()
    return {'event': raw.payload['event']}
