from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import HTTPException
from app.domain.models import Action, Memory, RawCapture
from app.repositories.memories import owned


def serialize(action):
    return {"id": action.id, "memory_id": action.memory_id, "type": action.type, "status": action.status,
            "payload": action.payload, "result": action.result, "created_at": action.created_at,
            "approved_at": action.approved_at, "completed_at": action.completed_at}


def create_draft_email(db, user_id, memory_id):
    memory = owned(db, Memory, memory_id, user_id)
    raw = db.get(RawCapture, memory.raw_capture_id)
    action = Action(user_id=user_id, memory_id=memory.id, type="draft_email", status="awaiting_approval",
                    payload={"memory_title": memory.title, "memory_summary": memory.summary,
                             "intent": memory.intent, "source_url": raw.payload.get("source_url") if raw else None})
    db.add(action)
    db.commit()
    db.refresh(action)
    return serialize(action)


def approve_draft_email(db, user_id, action_id, ai):
    action = db.scalar(select(Action).where(Action.id == action_id, Action.user_id == user_id))
    if action is None:
        raise HTTPException(404, "Not found")
    if action.type != "draft_email":
        raise HTTPException(400, "Only draft_email actions can be approved")
    if action.status == "completed":
        return serialize(action)
    if action.status != "awaiting_approval":
        raise HTTPException(409, "Action is not awaiting approval")
    memory = owned(db, Memory, action.memory_id, user_id)
    draft = ai.draft_email({"title": memory.title, "summary": memory.summary, "intent": memory.intent,
                            "topics": memory.topics, "source_url": action.payload.get("source_url")})
    action.result = draft.model_dump()
    action.status = "completed"
    action.approved_at = action.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(action)
    return serialize(action)
