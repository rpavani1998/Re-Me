"""Persist saves before doing slow provider work."""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy import select
from app.domain.models import Memory, RawCapture, User
from app.domain.schemas import CaptureInput
from app.repositories.memories import serialize
from app.services.capture_service import capture


def enqueue(db, user_id, body):
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    raw = db.scalar(select(RawCapture).where(RawCapture.user_id == user_id, RawCapture.request_id == body.request_id))
    if raw:
        memory = db.scalar(select(Memory).where(Memory.raw_capture_id == raw.id))
        if memory:
            return serialize(db, memory)
        if raw.status == 'failed':
            raw.status, raw.error = 'queued', None
    else:
        raw = RawCapture(user_id=user_id, request_id=body.request_id,
                         payload=body.model_dump(mode='json'), status='queued')
        db.add(raw)
    db.commit()
    return pending_card(raw)


def pending_card(raw):
    return {'id': raw.id, 'title': raw.payload.get('page_title') or raw.payload.get('source_url') or 'Saved thought',
            'status': raw.status, 'image_url': raw.payload.get('image_url'),
            'source_url': raw.payload.get('source_url'), 'created_at': raw.created_at}


def process_next(sessions, ai, config):
    with sessions() as db:
        # Interrupted provider work is retained and made explicitly retryable.
        for interrupted in db.scalars(select(RawCapture).where(RawCapture.status == 'processing')):
            started = interrupted.payload.get('processing_started_at')
            if started and datetime.fromisoformat(started) < datetime.now(timezone.utc) - timedelta(minutes=10):
                interrupted.status, interrupted.error = 'failed', 'ProcessingInterrupted'
        db.commit()
        raw = db.scalar(select(RawCapture).where(RawCapture.status == 'queued').order_by(RawCapture.created_at).limit(1))
        if not raw:
            return
        try:
            body = CaptureInput.model_validate({key: value for key, value in raw.payload.items() if key in CaptureInput.model_fields})
            capture(db, raw.user_id, body, ai, config)
        except HTTPException:
            # capture() preserves the original and records provider failures.
            pass
        except Exception:
            db.rollback()
            logging.getLogger('reme').exception('CAPTURE_QUEUE_FAILED')
