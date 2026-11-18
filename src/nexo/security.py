"""Autenticación administrativa y auditoría compartida sin secretos."""

import hashlib
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from argon2.profiles import RFC_9106_LOW_MEMORY
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, func, insert, or_, select, update

from nexo.database import Database, administrators, audit, sessions

HASHER = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
# No es una credencial: trabajo equivalente para identidades inexistentes.
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
HASH_GATE = threading.Lock()
LOGIN_EVENTS = ("login_success", "login_failure")
AUDIT_LIMIT = 10_000
AUDIT_DAYS = 90
LOGIN_LIMIT = 5
LOGIN_WINDOW = 60


def now() -> int:
    return int(time.time())


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def csrf_token(token: str) -> str:
    return hmac.new(token.encode("ascii"), b"nexo-admin-csrf-v1", hashlib.sha256).hexdigest()


def record(db, event: str, result: str, administrator_id=None, reason=None, subject_id=None):
    timestamp = now()
    db.execute(delete(audit).where(audit.c.occurred_at < timestamp - AUDIT_DAYS * 86400))
    db.execute(insert(audit).values(occurred_at=timestamp, event=event,
                                   administrator_id=administrator_id, result=result, reason=reason,
                                   subject_id=subject_id))
    # Mantener los eventos usados por el limitador, aunque haya una ráfaga de rechazos.
    removable = or_(audit.c.event.not_in(LOGIN_EVENTS), audit.c.occurred_at <= timestamp - LOGIN_WINDOW)
    excess = (db.scalar(select(func.count()).select_from(audit)) or 0) - AUDIT_LIMIT
    if excess > 0:
        oldest = select(audit.c.id).where(removable).order_by(audit.c.id).limit(excess)
        db.execute(delete(audit).where(audit.c.id.in_(oldest)))


def validate_credentials(username: str, password: str):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username):
        raise ValueError("Usuario: 3–64 caracteres ASCII en minúsculas, números, _, . o -")
    if (not 12 <= len(password) <= 128 or not any(c.isalpha() for c in password)
            or not any(c.isdigit() for c in password)):
        raise ValueError("Contraseña: 12–128 caracteres, con letras y números")


def initialize_admin(database: Database, username: str, password: str):
    validate_credentials(username, password)
    with database.transaction(write=True) as db:
        if db.scalar(select(administrators.c.id)) is not None:
            raise ValueError("Ya existe un administrador; inicialización rechazada")
        db.execute(insert(administrators).values(
            id=1, username=username, password_hash=HASHER.hash(password), active=True,
            created_at=now(), updated_at=now()))
        record(db, "admin_initialized", "success", 1)


def revoke_session(db, session_id: int, administrator_id: int, reason: str):
    changed = db.execute(update(sessions).where(
        sessions.c.id == session_id, sessions.c.revoked == False  # noqa: E712
    ).values(revoked=True)).rowcount
    if changed:
        record(db, "session_revoked", "success", administrator_id, reason)


@dataclass(frozen=True)
class AdminIdentity:
    administrator_id: int
    username: str
    session_id: int
    expires_at: int


def deny(request: Request, reason: str, status=401, administrator_id=None):
    with request.app.state.database.transaction(write=True) as db:
        record(db, "admin_access_denied", "denied", administrator_id, reason)
    raise HTTPException(status, "Acceso administrativo no autorizado")


def require_admin_session(request: Request) -> AdminIdentity:
    if request.headers.get("authorization"):
        deny(request, "authorization_header")
    token = request.cookies.get(request.app.state.settings.cookie_name, "")
    row = None
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        with request.app.state.database.transaction() as db:
            row = db.execute(select(
                sessions.c.id, sessions.c.administrator_id, sessions.c.expires_at,
                administrators.c.username,
            ).join(administrators).where(
                sessions.c.token_hash == digest(token), sessions.c.revoked == False,  # noqa: E712
                sessions.c.expires_at > now(), administrators.c.active == True,  # noqa: E712
            )).mappings().first()
    if row is None:
        deny(request, "invalid_session")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") != request.app.state.settings.origin:
            deny(request, "origin", 403, row.administrator_id)
        supplied = request.headers.get("x-csrf-token", "")
        if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not secrets.compare_digest(supplied, csrf_token(token)):
            deny(request, "csrf", 403, row.administrator_id)
    return AdminIdentity(row.administrator_id, row.username, row.id, row.expires_at)


def require_admin_permission(identity: AdminIdentity = Depends(require_admin_session)) -> AdminIdentity:
    # Solo el principal puede administrar. Los terminales tendrán otra dependencia.
    if identity.administrator_id != 1:
        raise HTTPException(403, "Permiso administrativo requerido")
    return identity


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


router = APIRouter(prefix="/api/v1", tags=["administrative security"])


@router.post("/auth/login")
def login(payload: LoginInput, request: Request, response: Response):
    settings = request.app.state.settings
    if request.headers.get("origin") != settings.origin:
        deny(request, "origin", 403)
    if not HASH_GATE.acquire(blocking=False):
        raise HTTPException(503, "Autenticación ocupada", headers={"Retry-After": "1"})
    try:
        with request.app.state.database.transaction(write=True) as db:
            count = db.scalar(select(func.count()).select_from(audit).where(
                audit.c.event.in_(LOGIN_EVENTS), audit.c.occurred_at > now() - LOGIN_WINDOW))
            if count >= LOGIN_LIMIT:
                record(db, "login_limited", "denied")
                outcome = "limited"
            else:
                admin = db.execute(select(administrators).where(
                    administrators.c.username == payload.username)).mappings().first()
                try:
                    valid = HASHER.verify(admin.password_hash if admin else DUMMY_HASH,
                                          payload.password.get_secret_value())
                except (VerificationError, InvalidHashError):
                    valid = False
                if not valid or admin is None or not admin.active:
                    record(db, "login_failure", "failure")
                    outcome = "invalid"
                else:
                    for previous in db.execute(select(sessions.c.id).where(
                            sessions.c.revoked == False)).scalars().all():  # noqa: E712
                        revoke_session(db, previous, admin.id, "new_login")
                    # Limita también el crecimiento de sesiones ya expiradas.
                    db.execute(delete(sessions).where(sessions.c.expires_at <= now()))
                    if HASHER.check_needs_rehash(admin.password_hash):
                        db.execute(update(administrators).where(administrators.c.id == admin.id).values(
                            password_hash=HASHER.hash(payload.password.get_secret_value()), updated_at=now()))
                    token = secrets.token_urlsafe(32)
                    timestamp = now()
                    expiry = timestamp + 3600
                    db.execute(insert(sessions).values(token_hash=digest(token), administrator_id=admin.id,
                                                       created_at=timestamp, expires_at=expiry, revoked=False))
                    record(db, "login_success", "success", admin.id)
                    outcome = "success"
    finally:
        HASH_GATE.release()
    if outcome == "limited":
        raise HTTPException(429, "Demasiados intentos; espera 60 segundos", headers={"Retry-After": "60"})
    if outcome == "invalid":
        raise HTTPException(401, "Credenciales inválidas")
    response.set_cookie(settings.cookie_name, token, max_age=3600, httponly=True,
                        secure=settings.secure_cookie, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"username": admin.username, "expires_at": expiry, "csrf_token": csrf_token(token)}


@router.get("/auth/me")
def me(request: Request, response: Response, identity: AdminIdentity = Depends(require_admin_permission)):
    response.headers["Cache-Control"] = "no-store"
    return {"username": identity.username, "expires_at": identity.expires_at,
            "csrf_token": csrf_token(request.cookies[request.app.state.settings.cookie_name])}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, identity: AdminIdentity = Depends(require_admin_permission)):
    with request.app.state.database.transaction(write=True) as db:
        revoke_session(db, identity.session_id, identity.administrator_id, "logout")
        record(db, "logout", "success", identity.administrator_id)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    settings = request.app.state.settings
    response.delete_cookie(settings.cookie_name, httponly=True, secure=settings.secure_cookie,
                           samesite="strict", path="/")
    return response


@router.get("/admin/status")
def admin_status(response: Response, identity: AdminIdentity = Depends(require_admin_permission)):
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "username": identity.username}
