"""Email/password accounts with revocable, thirty-day sessions."""
import hashlib
import secrets
import time
from collections import OrderedDict
from datetime import timedelta
from threading import Lock

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import db_session, user
from app.domain.models import Account, LoginSession, User, now, uid
from app.domain.schemas import StrictModel

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


DUMMY_HASH = password_hash("unused-password")


class Credentials(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address")
        local, domain = value.split("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Enter a valid email address")
        return value


class AuthLimiter:
    """Bound expensive password checks per client, per API process."""
    def __init__(self):
        self.attempts = OrderedDict()
        self.lock = Lock()

    def check(self, client):
        with self.lock:
            current = time.monotonic()
            start, count = self.attempts.pop(client, (current, 0))
            if current - start >= 60:
                start, count = current, 0
            self.attempts[client] = (start, count + 1)
            if len(self.attempts) > 4096:
                self.attempts.popitem(last=False)
            if count >= 10:
                raise HTTPException(429, "Too many attempts. Try again in a minute.", headers={"Retry-After": "60"})


def limit_auth(request: Request):
    request.app.state.auth_limiter.check(request.client.host if request.client else "unknown")


def issue_session(db, account, response):
    token = secrets.token_urlsafe(32)
    expires_at = now() + timedelta(days=30)
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                        user_id=account.user_id, expires_at=expires_at))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "expires_at": expires_at, "email": account.email}


@router.post("/signup", status_code=201, dependencies=[Depends(limit_auth)])
def signup(body: Credentials, response: Response, db=Depends(db_session)):
    if len(body.password) < 12:
        raise HTTPException(422, "Use a password with at least 12 characters.")
    account = Account(user_id=uid(), email=body.email, password_hash=password_hash(body.password))
    db.add(User(id=account.user_id))
    db.flush()
    db.add(account)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Unable to create this account. Try signing in.")
    return issue_session(db, account, response)


@router.post("/login", dependencies=[Depends(limit_auth)])
def login(body: Credentials, response: Response, db=Depends(db_session)):
    account = db.scalar(select(Account).where(Account.email == body.email))
    expected = account.password_hash if account and account.password_hash else DUMMY_HASH
    actual = password_hash(body.password, expected.split(":", 1)[0])
    if not secrets.compare_digest(actual, expected) or not account or not account.password_hash:
        raise HTTPException(401, "Incorrect email or password.")
    return issue_session(db, account, response)


@router.get("/me")
def me(response: Response, db=Depends(db_session), user_id=Depends(user)):
    account = db.get(Account, user_id)
    response.headers["Cache-Control"] = "no-store"
    return {"id": user_id, "email": account.email if account else None}


@router.get("/config")
def auth_config(request: Request):
    return {"google_client_id": request.app.state.config.google_client_id}


class GoogleCredential(StrictModel):
    credential: str = Field(min_length=1, max_length=16384)


def verify_google(credential, client_id):
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token
    return verify_oauth2_token(credential, GoogleRequest(), client_id)


def google_identity(body, request):
    client_id = request.app.state.config.google_client_id
    if not client_id:
        raise HTTPException(503, "Google sign-in is not configured yet. Use email and password.")
    try:
        claims = verify_google(body.credential, client_id)
    except ValueError:
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.")
    except Exception:
        raise HTTPException(503, "Google sign-in is temporarily unavailable.")
    if not claims.get("sub") or not claims.get("email") or claims.get("email_verified") is not True:
        raise HTTPException(401, "A verified Google email is required.")
    return claims


@router.post("/google", dependencies=[Depends(limit_auth)])
def google_login(body: GoogleCredential, request: Request, response: Response, db=Depends(db_session)):
    claims = google_identity(body, request)
    account = db.scalar(select(Account).where(Account.google_sub == claims["sub"]))
    if not account:
        email = claims["email"].strip().lower()
        if db.scalar(select(Account).where(Account.email == email)):
            raise HTTPException(409, "Sign in with your password, then link Google in Account settings.")
        account = Account(user_id=uid(), email=email, google_sub=claims["sub"])
        db.add(User(id=account.user_id))
        db.flush()
        db.add(account)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Account already exists. Please sign in again.")
    return issue_session(db, account, response)


@router.post("/google/link", dependencies=[Depends(limit_auth)])
def link_google(body: GoogleCredential, request: Request, db=Depends(db_session), user_id=Depends(user)):
    claims = google_identity(body, request)
    account = db.get(Account, user_id)
    if not account or account.email != claims["email"].strip().lower():
        raise HTTPException(409, "Choose the Google account with the same email as your Re:Me account.")
    account.google_sub = claims["sub"]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This Google account is already linked.")
    return {"linked": True}


@router.post("/extension-session")
def extension_session(response: Response, db=Depends(db_session), user_id=Depends(user)):
    account = db.get(Account, user_id)
    if not account:
        raise HTTPException(401, "Sign in to your account first.")
    return issue_session(db, account, response)


@router.post("/logout", status_code=204)
def logout(db=Depends(db_session), authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ")
    db.execute(delete(LoginSession).where(LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    db.commit()
