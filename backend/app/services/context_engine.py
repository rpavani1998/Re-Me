from datetime import timedelta, timezone
from sqlalchemy import select, delete
from app.domain.models import User, ContextSession, ContextEvent, now
from app.core.logging import event


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def purge_expired(db):
    ids = select(ContextSession.id).where(ContextSession.expires_at <= now())
    db.execute(delete(ContextEvent).where(ContextEvent.session_id.in_(ids)))
    db.execute(delete(ContextSession).where(ContextSession.expires_at <= now()))
    db.commit()


def clear_context(db, user_id):
    db.execute(delete(ContextEvent).where(ContextEvent.user_id == user_id))
    db.execute(delete(ContextSession).where(ContextSession.user_id == user_id))


def current(db, user_id):
    return db.scalar(select(ContextSession).where(ContextSession.user_id == user_id,
        ContextSession.status == "active", ContextSession.expires_at > now()).order_by(ContextSession.created_at.desc()))


def ingest(db, user_id, items, ai, config):
    purge_expired(db)
    identity = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not identity.context_enabled:
        return {"accepted": 0, "analyzed": False, "reason": "context_mode_off"}
    session = current(db, user_id)
    if not session:
        session = ContextSession(user_id=user_id, state={"recent_pages": []}, expires_at=now() + timedelta(minutes=config.context_ttl_minutes))
        db.add(session)
        db.flush()
        event("CONTEXT_SESSION_STARTED", session_id=session.id)
    pages = list(session.state.get("recent_pages", []))
    for item in items:
        # Only active, meaningful browsing contributes. Lifecycle events carry no content.
        if item.event_type not in ("PAGE_ENTERED", "TAB_ACTIVATED", "TAB_UPDATED", "SEARCH_DETECTED") or item.dwell_seconds < 8:
            continue
        page = item.model_dump(mode="json")
        pages = [p for p in pages if p["source_url"] != page["source_url"]]
        pages.append(page)
        pages = pages[-5:]
        db.add(ContextEvent(user_id=user_id, session_id=session.id, event_type=item.event_type, payload=page))
    state = dict(session.state)
    state["recent_pages"] = pages
    session.state = state
    session.expires_at = now() + timedelta(minutes=config.context_ttl_minutes)
    analyze = len(pages) >= 1 and (session.last_analyzed_at is None or utc(session.last_analyzed_at) < now() - timedelta(seconds=30))
    if analyze:
        session.last_analyzed_at = now()  # Claim the throttle window before the external call.
    sid = session.id
    db.flush()
    retained = select(ContextEvent.id).where(ContextEvent.session_id == sid).order_by(ContextEvent.created_at.desc()).limit(25)
    db.execute(delete(ContextEvent).where(ContextEvent.session_id == sid, ContextEvent.id.not_in(retained)))
    db.commit()
    if not analyze:
        return {"accepted": len(items), "analyzed": False, "session_id": sid}
    understanding = ai.context(pages)
    embedding = ai.embed(" ".join([understanding.activity, understanding.intent or "", *understanding.topics, *understanding.entities]))
    identity = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    session = current(db, user_id)
    if not identity.context_enabled or not session or session.id != sid:
        return {"accepted": 0, "analyzed": False, "reason": "context_ended"}
    session.state = {**session.state, **understanding.model_dump(), "embedding": embedding, "embedding_model": ai.embedding_model}
    db.commit()
    event("CONTEXT_UPDATED", session_id=sid)
    return {"accepted": len(items), "analyzed": True, "session_id": sid}
