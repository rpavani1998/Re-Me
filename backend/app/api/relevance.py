from typing import Literal
from datetime import timedelta
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select, or_, and_
from app.api.dependencies import db_session, user
from app.domain.schemas import StrictModel
from app.domain.models import RelevanceEvent, Memory, Episode, User, now
from app.services.context_engine import current
from app.services.relevance_engine import evaluate, card
from app.repositories.memories import owned
from app.core.logging import event

router=APIRouter(prefix="/api/relevance")


@router.post("/evaluate")
def evaluate_now(request:Request,db=Depends(db_session),user_id=Depends(user)):
    try:
        return evaluate(db,user_id,request.app.state.ai)
    except Exception as exc:
        raise HTTPException(502,"Relevance evaluation unavailable; staying quiet") from exc


@router.get("/current")
def suggestion(db=Depends(db_session),user_id=Depends(user)):
    identity=db.get(User,user_id)
    session=current(db,user_id) if identity.context_enabled else None
    items=db.scalars(select(RelevanceEvent).where(RelevanceEvent.user_id==user_id,RelevanceEvent.outcome.is_(None),
        or_(and_(RelevanceEvent.trigger_id.is_not(None), RelevanceEvent.created_at>now()-timedelta(days=7)),
            RelevanceEvent.created_at>now()-timedelta(hours=6))).order_by(RelevanceEvent.created_at.desc()).limit(10)).all()
    for item in items:
        if item.trigger_id:
            from app.services.context_engine import utc
            memory = db.get(Memory, item.memory_id)
            cutoff = memory.deadline or memory.event_date
            if cutoff and utc(cutoff) < now():
                continue
        if item.trigger_id or (session and item.context_session_id==session.id):
            return {"suggestion":card(db,item)}
    return {"suggestion":None}


class Feedback(StrictModel):
    outcome:Literal["opened","dismissed","ignored","acted","saved_for_later"]


@router.post("/{event_id}/feedback")
def feedback(event_id:str,body:Feedback,db=Depends(db_session),user_id=Depends(user)):
    db.scalar(select(User).where(User.id==user_id).with_for_update())
    item=owned(db,RelevanceEvent,event_id,user_id)
    if item.outcome is not None:
        return {"outcome":item.outcome}
    item.outcome=body.outcome
    memory=owned(db,Memory,item.memory_id,user_id)
    memory.interaction_count+=1
    if body.outcome=="dismissed":
        memory.dismiss_count+=1
    if body.outcome=="opened":
        memory.last_accessed_at=now()
    db.add(Episode(user_id=user_id,memory_id=memory.id,event_type=body.outcome,context={"relevance_event_id":item.id}))
    db.commit()
    event("MEMORY_"+body.outcome.upper(),memory_id=memory.id)
    return {"outcome":item.outcome}
