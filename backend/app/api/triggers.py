import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from app.api.dependencies import db_session
from app.domain.schemas import StrictModel
from app.domain.models import Trigger, Memory, Episode, RelevanceEvent
from app.services.relevance_engine import card
from app.core.logging import event
from app.integrations.trigger_client import callback_signature

router = APIRouter(prefix="/api/triggers")


class CallbackBody(StrictModel):
    memory_id: str
    trigger_id: str


def _require_callback_token(request: Request, authorization: str, body):
    if request.app.state.config.trigger_secret_key:
        expected = callback_signature(request.app.state.config, body.memory_id, body.trigger_id)
        if secrets.compare_digest(authorization, "Bearer " + expected):
            return
    token = request.app.state.config.trigger_callback_token
    if not token:
        raise HTTPException(401, "Invalid trigger callback token")
    if not secrets.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(401, "Invalid trigger callback token")


@router.post("/callback")
def callback(body: CallbackBody, request: Request, db=Depends(db_session),
             authorization: str = Header(default="")):
    _require_callback_token(request, authorization, body)
    from sqlalchemy import select
    trigger = db.scalar(select(Trigger).where(Trigger.id == body.trigger_id).with_for_update())
    if not trigger:
        raise HTTPException(404, "Unknown trigger")
    if trigger.memory_id != body.memory_id:
        raise HTTPException(404, "Unknown memory")
    memory = db.get(Memory, body.memory_id)
    if not memory or memory.user_id != trigger.user_id:
        raise HTTPException(404, "Unknown memory")
    if trigger.status in ("fired", "cancelled"):
        return {"status": trigger.status}
    from app.domain.models import now
    from datetime import timezone
    due = trigger.scheduled_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if due > now():
        raise HTTPException(409, "Reminder is not due yet")
    trigger.status = "fired"
    item = RelevanceEvent(user_id=trigger.user_id, memory_id=memory.id, trigger_id=trigger.id,
                          relevance_score=0.97, reason="It’s time for your saved event or reminder.",
                          suggested_action="open")
    db.add(item)
    db.add(Episode(user_id=trigger.user_id, memory_id=memory.id, event_type="deadline_fired",
                   context={"trigger_id": trigger.id}))
    db.commit()
    event("TRIGGER_FIRED", trigger_id=trigger.id)
    return {"status": "fired", "suggestion": card(db, item)}
