import secrets
import hashlib
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.domain.models import LoginSession, now


def db_session(request: Request):
    with request.app.state.sessions() as db:
        yield db


def user(request: Request, authorization: str = Header(default=""), db=Depends(db_session)):
    legacy_token = request.app.state.config.api_token
    if legacy_token and secrets.compare_digest(authorization, "Bearer " + legacy_token):
        return request.app.state.config.user_id
    if authorization.startswith("Bearer "):
        token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
        session = db.scalar(select(LoginSession).where(
            LoginSession.token_hash == token_hash, LoginSession.expires_at > now()))
        if session:
            return session.user_id
    raise HTTPException(401, "Please sign in to continue.")
