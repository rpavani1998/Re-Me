from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy import select
from app.api.dependencies import db_session, user
from app.domain.schemas import CaptureInput
from app.domain.models import Memory, RawCapture
from app.repositories.memories import owned, serialize
from app.services.capture_service import capture
from app.services.delete_memory import delete_memory
from app.services.capture_queue import enqueue, pending_card

router = APIRouter(prefix="/api")


@router.post("/captures", status_code=201)
def create_capture(body: CaptureInput, request: Request, response: Response, background: bool = False, db=Depends(db_session), user_id=Depends(user)):
    if background:
        result = enqueue(db, user_id, body)
        response.status_code = 202 if result.get("status") in ("queued", "processing") else 201
        return result
    return capture(db, user_id, body, request.app.state.ai, request.app.state.config)


@router.get("/captures/pending")
def pending(db=Depends(db_session), user_id=Depends(user)):
    rows = db.scalars(select(RawCapture).where(RawCapture.user_id == user_id,
        RawCapture.status.in_(["queued", "processing", "failed"])).order_by(RawCapture.created_at.desc()).limit(100))
    return [pending_card(raw) for raw in rows]


@router.post("/captures/{capture_id}/retry", status_code=202)
def retry(capture_id: str, db=Depends(db_session), user_id=Depends(user)):
    raw = owned(db, RawCapture, capture_id, user_id)
    if raw.status != "failed":
        raise HTTPException(409, "This save is not awaiting a retry.")
    raw.status, raw.error = "queued", None
    db.commit()
    return pending_card(raw)


@router.get("/captures/{capture_id}")
def get_capture(capture_id: str, db=Depends(db_session), user_id=Depends(user)):
    raw = owned(db, RawCapture, capture_id, user_id)
    return {"id": raw.id, "payload": raw.payload, "status": raw.status, "error": raw.error}


@router.get("/captures/pending")
def pending_captures(db=Depends(db_session), user_id=Depends(user)):
    rows = db.scalars(select(RawCapture).where(RawCapture.user_id == user_id, RawCapture.status != "completed")
                      .order_by(RawCapture.created_at.desc()).limit(50)).all()
    return [{"id": r.id, "status": r.status, "created_at": r.created_at, "error": r.error} for r in rows]


@router.get("/memories")
def memories(db=Depends(db_session), user_id=Depends(user), limit: int = 100, offset: int = 0):
    rows = db.scalars(select(Memory).where(Memory.user_id == user_id).order_by(Memory.created_at.desc())
                      .limit(max(1, min(limit, 200))).offset(max(offset, 0))).all()
    return [serialize(db, m) for m in rows]


@router.get("/memories/{memory_id}")
def memory(memory_id: str, db=Depends(db_session), user_id=Depends(user)):
    return serialize(db, owned(db, Memory, memory_id, user_id), detail=True)


@router.get("/memories/{memory_id}/episodes")
def episodes(memory_id: str, db=Depends(db_session), user_id=Depends(user)):
    return serialize(db, owned(db, Memory, memory_id, user_id), detail=True)["episodes"]


@router.delete("/memories/{memory_id}", status_code=204)
def remove_memory(memory_id: str, db=Depends(db_session), user_id=Depends(user)):
    delete_memory(db, user_id, memory_id)
