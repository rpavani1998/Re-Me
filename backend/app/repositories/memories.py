from sqlalchemy import select
from fastapi import HTTPException
from app.domain.models import Memory, RawCapture, Entity, MemoryEntity, Episode


def owned(db, model, identity, user_id):
    value = db.scalar(select(model).where(model.id == identity, model.user_id == user_id))
    if value is None:
        raise HTTPException(404, "Not found")
    return value


def serialize(db, memory, detail=False):
    raw = db.get(RawCapture, memory.raw_capture_id)
    entities = db.scalars(select(Entity).join(MemoryEntity).where(
        MemoryEntity.memory_id == memory.id, Entity.user_id == memory.user_id)).all()
    result = {key: getattr(memory, key) for key in (
        "id", "type", "title", "summary", "intent", "topics", "possible_actions", "relevance_hints",
        "event_date", "deadline", "importance_score", "created_at", "updated_at", "last_accessed_at",
        "last_surfaced_at", "dismiss_count", "interaction_count", "raw_capture_id", "interpretation_provider")}
    result["event"] = raw.payload.get("event")
    result["source_type"] = raw.payload.get("source_type")
    result["saved_excerpt"] = (raw.payload.get("selected_text") or raw.payload.get("visible_text") or "")[:2000]
    result["source_url"] = raw.payload.get("source_url")
    result["image_url"] = raw.payload.get("image_url")
    result["reading_status"] = raw.payload.get("reading_status", "not_read")
    result["captured_at"] = raw.payload.get("captured_at")
    result["entities"] = [{"id": e.id, "name": e.name, "type": e.entity_type} for e in entities]
    if detail:
        from app.domain.models import Trigger
        result["reminders"] = [{"id": t.id, "scheduled_at": t.scheduled_at, "status": t.status, "delivery": "needs_setup" if t.external_reference == "awaiting-trigger" else "trigger.dev"}
            for t in db.scalars(select(Trigger).where(Trigger.memory_id == memory.id, Trigger.user_id == memory.user_id).order_by(Trigger.scheduled_at))]
        result["raw_capture"] = raw.payload
        result["episodes"] = [{"id": e.id, "event_type": e.event_type, "occurred_at": e.occurred_at,
                               "context": e.context, "user_intent": e.user_intent}
                              for e in db.scalars(select(Episode).where(Episode.memory_id == memory.id,
                              Episode.user_id == memory.user_id).order_by(Episode.occurred_at)).all()]
    return result
