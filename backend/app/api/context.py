from typing import Literal
from pydantic import Field, HttpUrl
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from app.domain.schemas import StrictModel
from app.domain.models import User
from app.api.dependencies import db_session, user
from app.services.context_engine import ingest, current, clear_context, purge_expired

router = APIRouter(prefix="/api/context")


class Mode(StrictModel):
    enabled: bool


class BrowsingEvent(StrictModel):
    event_type: Literal["PAGE_ENTERED", "PAGE_LEFT", "TAB_ACTIVATED", "TAB_UPDATED", "WINDOW_BLURRED", "WINDOW_FOCUSED", "SEARCH_DETECTED"]
    source_url: HttpUrl
    page_title: str = Field(default="", max_length=500)
    search_query: str = Field(default="", max_length=500)
    visible_text: str = Field(default="", max_length=3000)
    dwell_seconds: float = Field(default=0, ge=0, le=3600)


class Events(StrictModel):
    events: list[BrowsingEvent] = Field(max_length=10)


@router.put("/mode")
def set_mode(body: Mode, db=Depends(db_session), user_id=Depends(user)):
    identity = db.scalar(select(User).where(User.id == user_id).with_for_update())
    identity.context_enabled = body.enabled
    if not body.enabled:
        clear_context(db, user_id)
    db.commit()
    return {"enabled": body.enabled}


@router.get("/current")
def get_current(db=Depends(db_session), user_id=Depends(user)):
    purge_expired(db)
    enabled = db.get(User, user_id).context_enabled
    session = current(db, user_id) if enabled else None
    return {"enabled": enabled, "session": {"id": session.id, "expires_at": session.expires_at,
            **{k: v for k, v in session.state.items() if k not in ("embedding", "recent_pages")}} if session else None}


@router.post("/events")
def events(body: Events, request: Request, db=Depends(db_session), user_id=Depends(user)):
    try:
        return ingest(db, user_id, body.events, request.app.state.ai, request.app.state.config)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, "Context understanding unavailable; no suggestion generated") from exc
