from fastapi import APIRouter, Depends, HTTPException, Request
from app.api.dependencies import db_session, user
from app.services.discovery import discover

router = APIRouter(prefix="/api")


@router.post("/memories/{memory_id}/discover")
def memory_discovery(memory_id: str, request: Request, db=Depends(db_session), user_id=Depends(user)):
    try:
        return discover(db, user_id, memory_id, request.app.state.config, request.app.state.ai)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "External discovery is unavailable") from exc
