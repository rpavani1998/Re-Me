from datetime import timedelta
from sqlalchemy import select, or_, func
from app.domain.models import Memory, Entity, MemoryEntity, Relationship, Episode, now
from app.services.capture_service import canonical
from app.services.context_engine import utc
from app.core.logging import event


def cosine(a, b):
    import math
    denominator = math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0


def candidates(db, user_id, state):
    names = [canonical(x) for x in state.get("entities", []) + state.get("topics", [])]
    direct = set(db.scalars(select(Entity.id).where(Entity.user_id == user_id, Entity.canonical_name.in_(names))).all())
    connected, frontier = set(direct), set(direct)
    for _ in range(2):
        if not frontier:
            break
        edges = db.scalars(select(Relationship).where(Relationship.user_id == user_id,
            Relationship.source_type == "entity", Relationship.target_type == "entity", Relationship.confidence >= 0.7,
            or_(Relationship.source_id.in_(frontier), Relationship.target_id.in_(frontier))).limit(200)).all()
        next_ids = {x for e in edges for x in (e.source_id, e.target_id)} - connected
        connected |= next_ids
        frontier = next_ids
    links = db.execute(select(MemoryEntity.memory_id, MemoryEntity.entity_id).join(Memory).where(
        Memory.user_id == user_id, MemoryEntity.entity_id.in_(connected))).all()
    direct_memories = {mid for mid, eid in links if eid in direct}
    graph_memories = {mid for mid, eid in links if eid not in direct}
    ranked = {}
    embedding = state.get("embedding")
    if embedding:
        query = select(Memory).where(Memory.user_id == user_id, Memory.embedding_model == state.get("embedding_model"))
        if db.bind.dialect.name == "postgresql":
            query = query.order_by(Memory.embedding.cosine_distance(embedding)).limit(30)
            ranked = {m.id: (m, cosine(list(m.embedding), embedding)) for m in db.scalars(query).all()}
        else:  # Explicit test/demo alternative; never used in production.
            rows = db.scalars(query).all()
            ranked = {m.id: (m, score) for m, score in sorted(((m, cosine(m.embedding, embedding)) for m in rows), key=lambda p:p[1], reverse=True)[:30]}
    extra = db.scalars(select(Memory).where(Memory.user_id == user_id, or_(Memory.id.in_(direct_memories | graph_memories),
        Memory.deadline.between(now(), now() + timedelta(days=3))))).all()
    for m in extra:
        ranked.setdefault(m.id, (m, 0))
    scored = []
    for m, similarity in ranked.values():
        # Suppression lives outside the model and cannot be overridden by it.
        if m.last_surfaced_at and utc(m.last_surfaced_at) > now() - timedelta(hours=6):
            continue
        if m.dismiss_count >= 3:
            continue
        dismissed = db.scalar(select(Episode.occurred_at).where(Episode.user_id == user_id,
            Episode.memory_id == m.id, Episode.event_type == "dismissed").order_by(Episode.occurred_at.desc()))
        if dismissed and utc(dismissed) > now() - timedelta(days=7):
            continue
        intent = ((m.intent == "want_to_try" and state.get("intent") == "restaurant_selection") or
                  (m.intent == "want_to_visit" and state.get("intent") == "travel_planning") or
                  (m.intent == "want_to_apply" and state.get("intent") == "job_search"))
        episode_count = db.scalar(select(func.count()).select_from(Episode).where(Episode.user_id == user_id, Episode.memory_id == m.id))
        time_signal = bool(m.deadline and now() < utc(m.deadline) < now() + timedelta(days=3))
        score = .35*max(similarity,0) + .25*(m.id in direct_memories) + .2*(m.id in graph_memories) + .15*intent + .1*m.importance_score + .08*time_signal + .03*min(episode_count/5,1) - .12*m.dismiss_count
        if similarity < .2 and m.id not in direct_memories | graph_memories:
            continue
        scored.append({"id":m.id,"title":m.title,"summary":m.summary,"type":m.type,"topics":m.topics,
                       "intent":m.intent,"deadline":m.deadline,"candidate_score":round(score,4),
                       "signals":{"vector":round(similarity,4),"entity":m.id in direct_memories,"graph":m.id in graph_memories,"intent":bool(intent)}})
    scored.sort(key=lambda c:c["candidate_score"], reverse=True)
    event("CANDIDATES_RETRIEVED", user_id=user_id, count=len(scored))
    return scored[:10]
