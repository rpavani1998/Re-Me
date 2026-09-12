from fastapi import APIRouter, Depends, Request
from app.api.dependencies import db_session, user
from app.services.action_service import create_draft_email, approve_draft_email

router = APIRouter(prefix="/api")


@router.post("/memories/{memory_id}/actions", status_code=201)
def create_action(memory_id: str, db=Depends(db_session), user_id=Depends(user)):
    return create_draft_email(db, user_id, memory_id)


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: str, request: Request, db=Depends(db_session), user_id=Depends(user)):
    return approve_draft_email(db, user_id, action_id, request.app.state.ai)


from datetime import datetime
from fastapi import HTTPException
from pydantic import field_validator
from app.domain.schemas import StrictModel
from app.domain.models import Trigger, Memory, now
from app.repositories.memories import owned


class ReminderInput(StrictModel):
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("Include the reminder timezone")
        return value


@router.post("/memories/{memory_id}/reminders", status_code=201)
def create_reminder(memory_id: str, body: ReminderInput, db=Depends(db_session), user_id=Depends(user)):
    from sqlalchemy import select
    from app.domain.models import User
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    owned(db, Memory, memory_id, user_id)
    if body.scheduled_at <= now():
        raise HTTPException(422, "Choose a future reminder time.")
    for old in db.scalars(select(Trigger).where(Trigger.memory_id == memory_id, Trigger.user_id == user_id, Trigger.status == "pending")):
        old.status = "cancelled"
    reminder = Trigger(user_id=user_id, memory_id=memory_id, scheduled_at=body.scheduled_at,
                       external_reference="awaiting-trigger")
    db.add(reminder)
    db.commit()
    return {"id": reminder.id, "scheduled_at": reminder.scheduled_at, "status": reminder.status}
