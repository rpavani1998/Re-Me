from sqlalchemy import select, or_
from app.domain.models import Memory, MemoryEntity, Relationship
from app.integrations.exa_client import ExaClient
from app.repositories.memories import owned


def _memory_context(memory):
    return {"id": memory.id, "title": memory.title, "summary": memory.summary,
            "intent": memory.intent, "topics": memory.topics, "deadline": memory.deadline}


def connected_memories(db, user_id, memory):
    """Selected memory plus memories connected through direct or one-hop entities."""
    entity_ids = set(db.scalars(select(MemoryEntity.entity_id).where(MemoryEntity.memory_id == memory.id)).all())
    expanded = set(entity_ids)
    if entity_ids:
        edges = db.scalars(select(Relationship).where(Relationship.user_id == user_id,
            Relationship.source_type == "entity", Relationship.target_type == "entity",
            or_(Relationship.source_id.in_(entity_ids), Relationship.target_id.in_(entity_ids))).limit(100)).all()
        expanded.update(identifier for edge in edges for identifier in (edge.source_id, edge.target_id))
    ids = {memory.id}
    if expanded:
        ids.update(db.scalars(select(MemoryEntity.memory_id).join(Memory).where(
            Memory.user_id == user_id, MemoryEntity.entity_id.in_(expanded))).all())
    return db.scalars(select(Memory).where(Memory.user_id == user_id, Memory.id.in_(ids)).limit(25)).all()


def discover(db, user_id, memory_id, config, ai, exa_client_factory=ExaClient):
    memory = owned(db, Memory, memory_id, user_id)
    if not config.exa_api_key:
        raise ValueError("EXA_API_KEY is required for discovery")
    memories = connected_memories(db, user_id, memory)
    grounded = [_memory_context(item) for item in memories]
    query = "\n".join(" ".join(filter(None, [item["title"], item["summary"], " ".join(item["topics"])]))
                      for item in grounded)[:4000]
    results = exa_client_factory(config.exa_api_key).search(query, limit=6)
    if not results:
        return {"memory_id": memory.id, "suggestions": [], "grounded_memory_ids": [item.id for item in memories]}
    ranking = ai.rank_discovery(_memory_context(memory), results)
    selected = []
    for index in ranking.ordered_indices:
        if isinstance(index, int) and 0 <= index < len(results) and index not in selected:
            selected.append(index)
        if len(selected) == 3:
            break
    if not selected:
        selected = list(range(min(3, len(results))))
    return {"memory_id": memory.id, "suggestions": [{**results[index], "external": True} for index in selected],
            "grounded_memory_ids": [item.id for item in memories]}
