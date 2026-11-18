"""Identidad de terminal independiente; sin orquestación ni conversaciones persistentes."""

import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete, insert, select, update

from nexo import security
from nexo.database import pairing_codes, pairing_rate, terminal_permissions, terminals
from nexo.security import AdminIdentity, require_admin_permission

PERMISSIONS = frozenset({"terminal.chat", "terminal.status"})
CREDENTIAL_TTL = 30 * 86400
PAIRING_LIMIT = 10
PAIRING_WINDOW = 60


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PermissionsInput(Input):
    permissions: list[str] = Field(default_factory=lambda: ["terminal.status"], max_length=32)

    @field_validator("permissions")
    @classmethod
    def known_permissions(cls, value):
        if not set(value) <= PERMISSIONS or len(value) != len(set(value)):
            raise ValueError("Permisos no válidos")
        return sorted(value)


class PairInput(Input):
    code: SecretStr = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Nombre inválido")
        return value


class RenameInput(Input):
    name: str = Field(min_length=1, max_length=80)
    _clean_name = field_validator("name")(PairInput.clean_name.__func__)


class VoiceConfig(BaseModel):
    language: str = "es"
    voice_id: str | None = None


class TerminalView(BaseModel):
    id: str
    name: str
    state: Literal["linked", "expired", "revoked"]
    created_at: int
    last_activity: int
    revoked_at: int | None
    expires_at: int
    permissions: list[str]
    voice_config: VoiceConfig


class CodeView(BaseModel):
    id: str
    expires_at: int
    state: Literal["pending", "consumed", "revoked", "expired", "locked"]
    attempts_remaining: int


class NewCode(CodeView):
    code: str


class PairResult(BaseModel):
    credential: str
    token_type: Literal["Bearer"] = "Bearer"
    terminal: TerminalView


@dataclass(frozen=True)
class TerminalContextScope:
    """Clave de contexto efímero; nunca contiene mensajes.

    El almacén de interacción indexa por terminal_id y descarta al revocar/expirar.
    """
    terminal_id: str


@dataclass(frozen=True)
class TerminalIdentity:
    terminal: TerminalView

    @property
    def context_scope(self) -> TerminalContextScope:
        return TerminalContextScope(self.terminal.id)


def terminal_view(db, row) -> TerminalView:
    return TerminalView(
        **{key: row[key] for key in ("id", "name", "created_at", "last_activity", "revoked_at",
                                     "expires_at", "voice_config")},
        state=("revoked" if row.revoked_at is not None else
               "expired" if row.expires_at <= security.now() else "linked"),
        permissions=list(db.scalars(select(terminal_permissions.c.permission).where(
            terminal_permissions.c.terminal_id == row.id).order_by(terminal_permissions.c.permission))),
    )


def code_view(row) -> CodeView:
    state = ("revoked" if row.revoked_at is not None else "consumed" if row.consumed_at is not None
             else "expired" if row.expires_at <= security.now() else "locked" if row.attempts >= 5
             else "pending")
    return CodeView(id=row.id, expires_at=row.expires_at, state=state, attempts_remaining=5-row.attempts)


def browser_origin(request):
    # Android puede omitir Origin; todo Origin presente debe coincidir exactamente.
    if "origin" in request.headers and request.headers["origin"] != request.app.state.settings.origin:
        raise HTTPException(403, "Origen no autorizado")


def require_terminal(request: Request) -> TerminalIdentity:
    browser_origin(request)
    authorization = request.headers.get("authorization", "")
    match = re.fullmatch(r"Bearer (nt_[A-Za-z0-9_-]{43})", authorization)
    timestamp = security.now()
    # Una sola transacción valida credencial, permisos y actividad. Nunca acepta cookie admin.
    with request.app.state.database.transaction(write=True) as db:
        row = None
        if match:
            row = db.execute(select(terminals).where(
                terminals.c.credential_hash == security.digest(match[1]),
                terminals.c.revoked_at.is_(None), terminals.c.expires_at > timestamp,
            )).mappings().first()
        if row is None:
            security.record(db, "terminal_access_denied", "denied", reason="invalid_credential")
            identity = None
        else:
            # Presencia aproximada; evita escrituras de actividad en cada lectura.
            if row.last_activity <= timestamp - 60:
                db.execute(update(terminals).where(terminals.c.id == row.id).values(last_activity=timestamp))
                row = db.execute(select(terminals).where(terminals.c.id == row.id)).mappings().one()
            identity = TerminalIdentity(terminal_view(db, row))
    if identity is None:
        raise HTTPException(401, "Credencial de terminal inválida", headers={"WWW-Authenticate": "Bearer"})
    return identity


def require_terminal_permission(permission: str):
    if permission not in PERMISSIONS:
        raise ValueError("Permiso no registrado")

    def check(request: Request, identity: TerminalIdentity = Depends(require_terminal)):
        if permission not in identity.terminal.permissions:
            with request.app.state.database.transaction(write=True) as db:
                security.record(db, "terminal_permission_denied", "denied", reason=permission,
                                subject_id=identity.terminal.id)
            raise HTTPException(403, "Permiso de terminal requerido")
        return identity
    return check


router = APIRouter(prefix="/api/v1", tags=["terminals"])


@router.post("/admin/pairing-codes", response_model=NewCode, status_code=201)
def create_code(payload: PermissionsInput, request: Request,
                admin: AdminIdentity = Depends(require_admin_permission)):
    identifier = uuid.uuid4().hex
    # 256 bits secretos además del selector público. Código completamente alfanumérico.
    code = identifier + secrets.token_hex(32)
    timestamp = security.now()
    with request.app.state.database.transaction(write=True) as db:
        # Limpieza acotada al generar códigos, sin crecimiento ilimitado de caducados.
        db.execute(delete(pairing_codes).where(pairing_codes.c.expires_at <= timestamp))
        db.execute(insert(pairing_codes).values(id=identifier, code_hash=security.digest(code),
                   created_at=timestamp, expires_at=timestamp+300, attempts=0,
                   permissions=payload.permissions))
        security.record(db, "pairing_created", "success", admin.administrator_id, subject_id=identifier)
        row = db.execute(select(pairing_codes).where(pairing_codes.c.id == identifier)).mappings().one()
        return NewCode(**code_view(row).model_dump(), code=code)


@router.get("/admin/pairing-codes/{code_id}", response_model=CodeView)
def pairing_status(code_id: str, request: Request, admin: AdminIdentity = Depends(require_admin_permission)):
    with request.app.state.database.transaction() as db:
        row = db.execute(select(pairing_codes).where(pairing_codes.c.id == code_id)).mappings().first()
        if row is None:
            raise HTTPException(404, "Código no encontrado")
        return code_view(row)


@router.delete("/admin/pairing-codes/{code_id}", status_code=204)
def revoke_code(code_id: str, request: Request, admin: AdminIdentity = Depends(require_admin_permission)):
    with request.app.state.database.transaction(write=True) as db:
        row = db.execute(select(pairing_codes).where(pairing_codes.c.id == code_id)).mappings().first()
        if row is None:
            raise HTTPException(404, "Código no encontrado")
        if row.revoked_at is None:
            db.execute(update(pairing_codes).where(pairing_codes.c.id == code_id).values(revoked_at=security.now()))
            security.record(db, "pairing_revoked", "success", admin.administrator_id, subject_id=code_id)


@router.post("/terminal/pair", response_model=PairResult, status_code=201)
def pair(payload: PairInput, request: Request):
    browser_origin(request)
    timestamp = security.now()
    code = payload.code.get_secret_value()
    with request.app.state.database.transaction(write=True) as db:
        rate = db.execute(select(pairing_rate)).mappings().one()
        attempts = rate.attempts if rate.window_start > timestamp-PAIRING_WINDOW else 0
        window = rate.window_start if attempts else timestamp
        if attempts >= PAIRING_LIMIT:
            security.record(db, "pairing_limited", "denied")
            outcome = "limited"
        else:
            db.execute(update(pairing_rate).values(attempts=attempts+1, window_start=window))
            row = db.execute(select(pairing_codes).where(pairing_codes.c.id == code[:32])).mappings().first()
            valid_format = re.fullmatch(r"[a-f0-9]{96}", code) is not None
            if row is None or code_view(row).state != "pending":
                outcome = "invalid"
            else:
                db.execute(update(pairing_codes).where(pairing_codes.c.id == row.id).values(attempts=row.attempts+1))
                outcome = ("success" if valid_format and secrets.compare_digest(
                    row.code_hash, security.digest(code)) else "invalid")
            if outcome == "invalid":
                security.record(db, "pairing_failed", "denied", reason="invalid_code")
            else:
                # BEGIN IMMEDIATE ya adquirido: consumo, identidad, permisos y auditoría atómicos.
                identifier = uuid.uuid4().hex
                credential = "nt_" + secrets.token_urlsafe(32)
                db.execute(update(pairing_codes).where(pairing_codes.c.id == row.id).values(consumed_at=timestamp))
                db.execute(insert(terminals).values(id=identifier, name=payload.name,
                           created_at=timestamp, last_activity=timestamp,
                           voice_config=VoiceConfig().model_dump(), credential_hash=security.digest(credential),
                           expires_at=timestamp+CREDENTIAL_TTL))
                for permission in row.permissions:
                    db.execute(insert(terminal_permissions).values(terminal_id=identifier, permission=permission))
                security.record(db, "terminal_linked", "success", subject_id=identifier)
                linked = db.execute(select(terminals).where(terminals.c.id == identifier)).mappings().one()
                result = PairResult(credential=credential, terminal=terminal_view(db, linked))
    # Errores después del commit: intentos fallidos no se revierten.
    if outcome == "limited":
        raise HTTPException(429, "Demasiados intentos; espera 60 segundos", headers={"Retry-After": "60"})
    if outcome == "invalid":
        raise HTTPException(401, "Código de vinculación inválido")
    return result


@router.get("/terminal/me", response_model=TerminalView)
def terminal_me(identity: TerminalIdentity = Depends(require_terminal)):
    return identity.terminal


@router.get("/terminal/status", response_model=TerminalView)
def terminal_status(identity: TerminalIdentity = Depends(require_terminal_permission("terminal.status"))):
    return identity.terminal


@router.get("/admin/terminals", response_model=list[TerminalView])
def list_terminals(request: Request, admin: AdminIdentity = Depends(require_admin_permission)):
    with request.app.state.database.transaction() as db:
        return [terminal_view(db, row) for row in db.execute(select(terminals).order_by(
            terminals.c.created_at, terminals.c.id)).mappings()]


def find_terminal(db, terminal_id):
    row = db.execute(select(terminals).where(terminals.c.id == terminal_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "Terminal no encontrado")
    return row


@router.patch("/admin/terminals/{terminal_id}/name", response_model=TerminalView)
def rename_terminal(terminal_id: str, payload: RenameInput, request: Request,
                    admin: AdminIdentity = Depends(require_admin_permission)):
    with request.app.state.database.transaction(write=True) as db:
        find_terminal(db, terminal_id)
        db.execute(update(terminals).where(terminals.c.id == terminal_id).values(name=payload.name))
        security.record(db, "terminal_renamed", "success", admin.administrator_id, subject_id=terminal_id)
        return terminal_view(db, find_terminal(db, terminal_id))


@router.put("/admin/terminals/{terminal_id}/permissions", response_model=TerminalView)
def set_permissions(terminal_id: str, payload: PermissionsInput, request: Request,
                    admin: AdminIdentity = Depends(require_admin_permission)):
    with request.app.state.database.transaction(write=True) as db:
        find_terminal(db, terminal_id)
        db.execute(delete(terminal_permissions).where(terminal_permissions.c.terminal_id == terminal_id))
        for permission in payload.permissions:
            db.execute(insert(terminal_permissions).values(terminal_id=terminal_id, permission=permission))
        security.record(db, "terminal_permissions", "success", admin.administrator_id, subject_id=terminal_id)
        return terminal_view(db, find_terminal(db, terminal_id))


@router.delete("/admin/terminals/{terminal_id}", status_code=204)
def revoke_terminal(terminal_id: str, request: Request, admin: AdminIdentity = Depends(require_admin_permission)):
    with request.app.state.database.transaction(write=True) as db:
        row = find_terminal(db, terminal_id)
        if row.revoked_at is None:
            db.execute(update(terminals).where(terminals.c.id == terminal_id).values(revoked_at=security.now()))
            security.record(db, "terminal_revoked", "success", admin.administrator_id, subject_id=terminal_id)

    request.app.state.interactions.discard(terminal_id)
