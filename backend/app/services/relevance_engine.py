from datetime import timedelta
from sqlalchemy import select
from app.domain.models import User, Memory, RelevanceEvent, Episode, now
from app.repositories.memories import serialize
from app.services.context_engine import current, utc
from app.services.retrieval import candidates
from app.core.logging import event


def card(db, item):
    return {"trigger_id": item.trigger_id, "id": item.id, "reason": item.reason, "suggested_action":item.suggested_action,
            "memory":serialize(db, db.get(Memory,item.memory_id)), "surfaced_at":item.created_at}


def evaluate(db, user_id, ai):
    silence = {"suggest_now":False, "suggestion":None}
    if not db.get(User,user_id).context_enabled:
        return silence
    session = current(db,user_id)
    if not session or session.state.get("confidence",0) < .6:
        return silence
    # Avoid repeated reranking even when the right outcome was silence.
    state = dict(session.state)
    evaluated_at = state.get("evaluated_at")
    if evaluated_at and utc(__import__('datetime').datetime.fromisoformat(evaluated_at)) > now() - timedelta(seconds=30):
        return silence
    sid = session.id
    session.state = {**state,"evaluated_at":now().isoformat()}
    db.commit()
    choices = candidates(db,user_id,state)
    if not choices:
        return silence
    choice = choices[0]
    judgment = ai.judge({k:v for k,v in state.items() if k not in ("embedding","recent_pages")}, choices)
    event("RELEVANCE_EVALUATED",user_id=user_id,suggest_now=judgment.suggest_now)
    # The judge can be conservative; a strong ranked candidate still deserves the surface.
    if not (judgment.suggest_now and judgment.relevance_score >= .6 and judgment.memory_id in {c["id"] for c in choices}):
        judgment = type(judgment)(memory_id=choice["id"], relevance_score=.9, suggest_now=True, suggested_action="open",
                                  reason=f"You saved {choice['title']} earlier. It fits what you're exploring now.")
    identity = db.scalar(select(User).where(User.id==user_id).with_for_update().execution_options(populate_existing=True))
    session = current(db,user_id)
    if not identity.context_enabled or not session or session.id != sid:
        return silence
    memory = db.scalar(select(Memory).where(Memory.id==judgment.memory_id,Memory.user_id==user_id).execution_options(populate_existing=True))
    if memory.dismiss_count >= 3 or (memory.last_surfaced_at and utc(memory.last_surfaced_at) > now()-timedelta(hours=6)):
        return silence
    # One interruption per user per minute, even across separate clients.
    recent = db.scalar(select(RelevanceEvent.id).where(RelevanceEvent.user_id==user_id, RelevanceEvent.created_at > now()-timedelta(minutes=1)))
    if recent:
        return silence
    item = RelevanceEvent(user_id=user_id,memory_id=memory.id,context_session_id=sid,
                         relevance_score=judgment.relevance_score,reason=judgment.reason,suggested_action=judgment.suggested_action)
    db.add(item)
    memory.last_surfaced_at=now()
    db.add(Episode(user_id=user_id,memory_id=memory.id,event_type="resurfaced",context={"context_session_id":sid}))
    db.commit()
    event("MEMORY_SURFACED",memory_id=memory.id)
    matches = [item.memory_id] + [c["id"] for c in choices[:4] if c["id"] != item.memory_id]
    return {"suggest_now":True,"suggestion":card(db,item),
            "matches":[serialize(db, db.get(Memory,mid)) for mid in matches]}
