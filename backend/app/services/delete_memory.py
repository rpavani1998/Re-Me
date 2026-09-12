"""Delete one owned memory and its stored content in a single transaction."""
from sqlalchemy import delete, or_, select

from app.domain.models import (
    Action, Entity, Episode, Memory, MemoryEntity, RawCapture, Relationship,
    RelevanceEvent, SemanticFact, Trigger, User,
)
from app.repositories.memories import owned


def delete_memory(db, user_id, memory_id):
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    memory = owned(db, Memory, memory_id, user_id)
    raw_id = memory.raw_capture_id
    episode_ids = set(db.scalars(select(Episode.id).where(Episode.memory_id == memory_id)))
    entity_ids = list(db.scalars(select(MemoryEntity.entity_id).where(MemoryEntity.memory_id == memory_id)))
    # Derived facts must not retain information from deleted evidence.
    for fact in db.scalars(select(SemanticFact).where(SemanticFact.user_id == user_id)):
        if episode_ids.intersection(fact.source_episode_ids):
            db.delete(fact)
    db.execute(delete(Relationship).where(Relationship.user_id == user_id, or_(
        Relationship.source_episode_id.in_(episode_ids),
        (Relationship.source_type == "memory") & (Relationship.source_id == memory_id),
        (Relationship.target_type == "memory") & (Relationship.target_id == memory_id),
    )))
    for model in (RelevanceEvent, Action, Trigger, MemoryEntity, Episode):
        db.execute(delete(model).where(model.memory_id == memory_id))
    db.execute(delete(Memory).where(Memory.id == memory_id))
    db.execute(delete(RawCapture).where(RawCapture.id == raw_id, RawCapture.user_id == user_id))
    # Shared entities remain available to other memories.
    for entity_id in entity_ids:
        linked = db.scalar(select(MemoryEntity.entity_id).where(MemoryEntity.entity_id == entity_id).limit(1))
        related = db.scalar(select(Relationship.id).where(or_(
            Relationship.source_id == entity_id, Relationship.target_id == entity_id)).limit(1))
        if not linked and not related:
            db.execute(delete(Entity).where(Entity.id == entity_id, Entity.user_id == user_id))
    db.commit()
