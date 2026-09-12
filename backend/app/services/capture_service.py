import http.client
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import HTTPException
from app.domain.models import RawCapture, Memory, Episode, Entity, MemoryEntity, Relationship, User
from app.core.config import settings
from app.core.logging import event
from app.integrations.article_reader import read_article, image_url
from app.repositories.memories import serialize
from app.services.trigger_service import schedule_if_deadline


def canonical(value):
    return " ".join(value.casefold().split())


def date(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def capture(db, user_id, payload, ai, config=None):
    config = config or settings()
    event("CAPTURE_RECEIVED", user_id=user_id)
    # Serialize per-user idempotency checks on PostgreSQL.
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    raw = db.scalar(select(RawCapture).where(RawCapture.user_id == user_id, RawCapture.request_id == payload.request_id).execution_options(populate_existing=True))
    if raw:
        existing = db.scalar(select(Memory).where(Memory.raw_capture_id == raw.id))
        if existing:
            return serialize(db, existing)
        if raw.status == "processing":
            raise HTTPException(409, {"message": "Capture is processing; retry later", "capture_id": raw.id})
    else:
        raw = RawCapture(user_id=user_id, request_id=payload.request_id, payload=payload.model_dump(mode="json"))
        db.add(raw)
    raw.status, raw.error = "processing", None
    raw.payload = {**raw.payload, "processing_started_at": datetime.now(timezone.utc).isoformat()}
    db.commit()  # Original content survives all downstream failures.
    event("RAW_CAPTURE_STORED", capture_id=raw.id)
    try:
        original = dict(raw.payload)
        original["image_url"] = image_url(original.get("image_url"))
        understanding = dict(original)
        # Browser captures already carry rendered article text. URL-only saves
        # need a public-page read; inaccessible sites still retain the saved link.
        if original.get("source_type") != "image" and original.get("source_url") and not original.get("visible_text", "").strip() and not config.demo_mode:
            try:
                article = read_article(original["source_url"])
                original["article"] = article
                original["reading_status"] = "read"
                original["image_url"] = original["image_url"] or article["image_url"]
                understanding.update(visible_text=article["text"],
                                     page_title=article["title"] or original.get("page_title", ""),
                                     meta_description=article["description"])
            except (ValueError, OSError, TimeoutError, http.client.HTTPException, LookupError):
                original["reading_status"] = "unavailable"
        else:
            original["reading_status"] = "provided_text" if original.get("visible_text", "").strip() else "not_read"
        raw.payload = original
        db.commit()
        result = ai.extract(understanding)
        event("MEMORY_EXTRACTED", capture_id=raw.id)
        embedding_text = "\n".join([result.title, result.summary, result.intent or "", ", ".join(result.topics),
                                    ", ".join(e.name for e in result.entities),
                                    " ".join(h.description for h in result.relevance_hints)])
        embedding = ai.embed(embedding_text)
        memory = Memory(user_id=user_id, raw_capture_id=raw.id, type=result.type, title=result.title,
                        summary=result.summary, intent=result.intent, topics=result.topics,
                        possible_actions=[a.model_dump() for a in result.possible_actions],
                        relevance_hints=[h.model_dump() for h in result.relevance_hints],
                        event_date=date(result.event_date), deadline=date(result.deadline),
                        importance_score=result.importance_score, embedding=embedding,
                        embedding_model=ai.embedding_model, interpretation_provider=ai.name)
        db.add(memory)
        db.flush()
        episode = Episode(user_id=user_id, memory_id=memory.id, event_type="saved_content",
                          occurred_at=date(raw.payload["captured_at"]), user_intent=result.intent,
                          importance=result.importance_score, context={"source": raw.payload["source_type"], "page": raw.payload["page_title"]})
        db.add(episode)
        db.flush()
        event("EPISODE_CREATED", episode_id=episode.id)
        db.scalar(select(User).where(User.id == user_id).with_for_update())
        entities = {}
        for item in result.entities:
            name = canonical(item.name)
            if not name or name in entities:
                continue
            entity = db.scalar(select(Entity).where(Entity.user_id == user_id, Entity.canonical_name == name, Entity.entity_type == item.type))
            if entity is None:
                entity = Entity(user_id=user_id, name=item.name[:300], canonical_name=name[:300], entity_type=item.type)
                db.add(entity)
                db.flush()
            entities[name] = entity
            db.add(MemoryEntity(memory_id=memory.id, entity_id=entity.id, relationship_type=item.relationship[:40], confidence=item.confidence))
            db.add(Relationship(user_id=user_id, source_type="memory", source_id=memory.id,
                                relationship=item.relationship[:80], target_type="entity", target_id=entity.id,
                                confidence=item.confidence, source_episode_id=episode.id))
            event("ENTITY_EXTRACTED", entity_id=entity.id)
        for link in result.relationships:
            source, target = entities.get(canonical(link.source)), entities.get(canonical(link.target))
            if source and target and source.id != target.id:
                db.add(Relationship(user_id=user_id, source_type="entity", source_id=source.id,
                                    relationship=link.relationship[:80], target_type="entity", target_id=target.id,
                                    confidence=link.confidence, source_episode_id=episode.id))
        event("RELATIONSHIP_CREATED", memory_id=memory.id)
        event("EMBEDDING_CREATED", memory_id=memory.id)
        from app.services.event_service import prepare_event
        prepare_event(db, memory, raw, result.event)
        if not result.event:
            schedule_if_deadline(db, user_id, memory, config)
        raw.status = "complete"
        db.commit()
        return serialize(db, memory)
    except Exception as exc:
        db.rollback()
        raw = db.get(RawCapture, raw.id)
        raw.status, raw.error = "failed", type(exc).__name__
        db.commit()
        event("CAPTURE_PROCESSING_FAILED", capture_id=raw.id, error_type=type(exc).__name__)
        raise HTTPException(502, {"message": "Understanding failed; original capture is preserved. Retry with the same request_id.", "capture_id": raw.id}) from exc
