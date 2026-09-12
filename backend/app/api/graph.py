from fastapi import APIRouter,Depends
from sqlalchemy import select,or_
from app.api.dependencies import db_session,user
from app.domain.models import Entity,Memory,MemoryEntity,Relationship
from app.repositories.memories import owned

router=APIRouter(prefix="/api")


@router.get("/entities")
def entities(db=Depends(db_session),user_id=Depends(user)):
    return [{"id":e.id,"name":e.name,"type":e.entity_type} for e in db.scalars(select(Entity).where(Entity.user_id==user_id).limit(500)).all()]


@router.get("/memories/{memory_id}/connections")
def connections(memory_id:str,db=Depends(db_session),user_id=Depends(user)):
    owned(db,Memory,memory_id,user_id)
    ids=db.scalars(select(MemoryEntity.entity_id).where(MemoryEntity.memory_id==memory_id)).all()
    rows=db.scalars(select(Relationship).where(Relationship.user_id==user_id,or_(Relationship.source_id==memory_id,
        Relationship.source_id.in_(ids),Relationship.target_id.in_(ids))).limit(200)).all()
    return [{"id":r.id,"source_id":r.source_id,"source_type":r.source_type,"relationship":r.relationship,
             "target_id":r.target_id,"target_type":r.target_type,"confidence":r.confidence,"source_episode_id":r.source_episode_id} for r in rows]
