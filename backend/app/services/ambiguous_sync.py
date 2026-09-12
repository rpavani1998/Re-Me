"""Account-scoped, durable Ambiguous synchronization."""
from fastapi import HTTPException
from sqlalchemy import select
from app.domain.models import Account, Action, Memory, RawCapture, User, now
from app.repositories.memories import owned
from app.integrations.ambiguous_client import AmbiguousClient
from app.services.event_service import timestamp

def require_owner(config, db, user_id):
    account = db.get(Account, user_id)
    if not config.ambiguous_owner_email or not account or account.email.casefold() != config.ambiguous_owner_email.casefold():
        raise HTTPException(403, 'This Ambiguous connection is not assigned to your Re:Me account.')
    if not config.ambiguous_api_key:
        raise HTTPException(503, 'Ambiguous is not configured.')


def sync_memory(db, user_id, memory_id, config):
    require_owner(config, db, user_id)
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    memory = owned(db, Memory, memory_id, user_id)
    existing = db.scalar(select(Action).where(Action.memory_id == memory_id, Action.type == 'ambiguous_sync'))
    if existing:
        return {'status':existing.status, 'result':existing.result}
    raw = db.get(RawCapture, memory.raw_capture_id)
    event = raw.payload.get('event')
    marker = f'ReMe memory {memory.id}'
    if event:
        if event.get('needs_confirmation') or not timestamp(event.get('starts_at')) or not timestamp(event.get('ends_at')):
            raise HTTPException(422, 'Confirm the event start and end times before syncing to Ambiguous.')
        if not config.ambiguous_calendar_id:
            raise HTTPException(503, 'Configure the Re:Me calendar first.')
        tool = 'create_event'
        args = {'calendar_id':config.ambiguous_calendar_id, 'title':event['title'],
                'start_at':event['starts_at'], 'end_at':event['ends_at'],
                'description':memory.summary+'\n\n'+marker, 'location':event.get('location'),
                'visibility':'private', 'attendees':[], 'auto_conference':False, 'auto_meeting_notes':False}
    elif memory.deadline:
        tool = 'create_task'
        args = {'title':memory.title[:255], 'description':memory.summary+'\n\n'+marker,
                'due_date':memory.deadline.date().isoformat()}
    else:
        raise HTTPException(422, 'This memory has no confirmed event or deadline to sync.')
    action = Action(user_id=user_id, memory_id=memory_id, type='ambiguous_sync', status='sending', payload={'tool':tool})
    db.add(action)
    db.commit()  # Prevent duplicate writes after a timeout or service restart.
    try:
        with AmbiguousClient(config.ambiguous_api_key) as client:
            result = client.call(tool, args)
        action.status, action.result, action.completed_at = 'completed', result, now()
        db.commit()
        return {'status':action.status,'result':result}
    except Exception:
        action.status = 'needs_review'
        db.commit()
        raise HTTPException(502, 'Ambiguous did not confirm the write. Check the workspace before retrying to avoid duplicates.')


def sync_pending_events(sessions, config):
    if not config.ambiguous_api_key or not config.ambiguous_calendar_id or not config.ambiguous_owner_email:
        return
    with sessions() as db:
        from sqlalchemy import func
        account = db.scalar(select(Account).where(func.lower(Account.email) == config.ambiguous_owner_email.casefold()))
        if not account:
            return
        done = select(Action.memory_id).where(Action.type == 'ambiguous_sync')
        memories = db.scalars(select(Memory).join(Action, Action.memory_id == Memory.id).where(
            Memory.user_id == account.user_id, Action.type == 'add_to_calendar', Action.status == 'ready',
            Memory.id.not_in(done)).order_by(Memory.created_at).limit(20)).all()
        for memory in memories:
            try:
                sync_memory(db, account.user_id, memory.id, config)
            except HTTPException:
                db.rollback()  # Saved content and any needs_review receipt remain intact.
