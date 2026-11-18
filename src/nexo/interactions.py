"""Interacción local determinista y contexto efímero acotado por terminal."""

import asyncio
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from nexo import security
from nexo.database import terminals
from nexo.terminals import TerminalIdentity, require_terminal_permission
from nexo.orchestration import (Capability, CapabilityRegistry, CapabilityResult,
    ExecutionContext, IntentRouter, Orchestrator, normalized)

PATH = "/api/v1/terminal/interact"
MAX_INPUT = 2000
MAX_BODY = 32768  # Incluye 2000 caracteres escapados como pares Unicode en JSON.
MAX_MESSAGES = 20
MAX_CONTEXT_BYTES = 16384
MAX_CONTEXTS = 128
RATE_LIMIT = 20


class InteractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_INPUT, repr=False)

    @field_validator("text")
    @classmethod
    def clean(cls, value):
        value = value.strip()
        if not value or any(unicodedata.category(c) == "Cs" or
                            (ord(c) < 32 and c not in "\n\t") for c in value):
            raise ValueError("Texto inválido")
        return value


class InteractionError(BaseModel):
    code: str


class InteractionResponse(BaseModel):
    request_id: str
    terminal_id: str | None
    status: Literal["completed", "failed"]
    message: str
    response_type: Literal["text", "unavailable", "error"]
    error: InteractionError | None = None


def failure(request, status, code, message, headers=None):
    body = InteractionResponse(request_id=request.state.interaction_id,
        terminal_id=getattr(request.state, "terminal_id", None), status="failed",
        message=message, response_type="error", error=InteractionError(code=code))
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


@dataclass(frozen=True, repr=False)
class Message:
    role: Literal["user", "assistant"]
    text: str


@dataclass(repr=False)
class Context:
    touched: float
    window: float
    attempts: int = 0
    messages: tuple[Message, ...] = ()
    busy: bool = False


def local_orchestrator():
    async def respond(payload, context):
        # Adaptador exclusivo para el procesador puro heredado; ninguna E/S ni acción.
        message, kind = await asyncio.to_thread(process, payload.text, context.messages)
        return CapabilityResult(message=message, response_type=kind)

    phrases = {
        "greeting": ("hola", "buenos dias", "buenas tardes", "buenas noches"),
        "status": ("estado", "estado del servicio", "como estas"),
        "help": ("ayuda", "help"),
        "unavailable": (),
    }
    registry = CapabilityRegistry(Capability("local." + name, name,
        frozenset({"terminal.chat"}), frozenset(), InteractionInput, respond)
        for name in phrases)
    router = IntentRouter(registry, [(phrase, "local." + name)
        for name, aliases in phrases.items() for phrase in aliases], fallback="local.unavailable")
    return Orchestrator(registry, router)


def process(text: str, context: tuple[Message, ...]) -> tuple[str, str]:
    """Contrato puro sustituible por el orquestador; no ejecuta acciones."""
    command = normalized(text)
    if command in {"hola", "buenos dias", "buenas tardes", "buenas noches"}:
        return ("Hola de nuevo." if context else "Hola. Soy NEXO Home."), "text"
    if command in {"estado", "estado del servicio", "como estas"}:
        return "El servicio local de interacción está disponible.", "text"
    if command in {"ayuda", "help"}:
        return "Puedes escribir hola, estado o ayuda. IA, voz y acciones todavía no están disponibles.", "text"
    return "Solicitud no reconocida. IA, voz, acciones e integraciones todavía no están disponibles. Escribe ayuda.", "unavailable"


class InteractionService:
    def __init__(self, ttl, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._lock = threading.Lock()
        self._contexts: dict[str, Context] = {}
        self.orchestrator = local_orchestrator()

    def discard(self, terminal_id):
        with self._lock:
            self._contexts.pop(terminal_id, None)

    def clear(self):
        with self._lock:
            self._contexts.clear()

    def cleanup(self, database):
        # Ciclo diferido por acceso, incluso si la autenticación posterior falla.
        # Consulta acotada; SQLite nunca recibe mensajes.
        with self._lock:
            identifiers = tuple(self._contexts)
        if not identifiers:
            return
        with database.transaction() as db:
            valid = set(db.scalars(select(terminals.c.id).where(
                terminals.c.id.in_(identifiers), terminals.c.revoked_at.is_(None),
                terminals.c.expires_at > security.now())))
        with self._lock:
            now = self.clock()
            for key in identifiers:
                entry = self._contexts.get(key)
                if entry and (key not in valid or (not entry.busy and now-entry.touched >= self.ttl)):
                    self._contexts.pop(key, None)

    async def interact(self, terminal_id, text, permissions):
        with self._lock:
            now = self.clock()
            entry = self._contexts.get(terminal_id)
            if entry is None:
                if len(self._contexts) >= MAX_CONTEXTS:
                    raise HTTPException(503, "Capacidad temporal agotada")
                entry = self._contexts[terminal_id] = Context(now, now)
            if entry.busy:
                raise HTTPException(409, "Este terminal ya está procesando una solicitud")
            if now-entry.window >= 60:
                entry.window, entry.attempts = now, 0
            if entry.attempts >= RATE_LIMIT:
                raise HTTPException(429, "Demasiadas solicitudes; espera 60 segundos", headers={"Retry-After": "60"})
            entry.attempts += 1
            entry.busy = True
            snapshot = entry.messages
        try:
            outcome = await self.orchestrator.execute(text, permissions, ExecutionContext(terminal_id, snapshot))
            if outcome.code:
                return outcome
            message = outcome.message
            messages = snapshot + (Message("user", text), Message("assistant", message))
            while len(messages) > MAX_MESSAGES or sum(len(m.text.encode("utf-8")) for m in messages) > MAX_CONTEXT_BYTES:
                messages = messages[2:]
            with self._lock:
                # Una revocación concurrente no debe resucitar el contexto.
                if self._contexts.get(terminal_id) is entry:
                    entry.messages = messages
                    entry.touched = self.clock()
            return outcome
        finally:
            with self._lock:
                entry.busy = False


def cleanup(request: Request):
    request.app.state.interactions.cleanup(request.app.state.database)


router = APIRouter(tags=["interaction"], dependencies=[Depends(cleanup)])


@router.post(PATH, response_model=InteractionResponse, responses={
    status: {"model": InteractionResponse}
    for status in (401, 403, 409, 413, 422, 429, 500, 503, 504)
})
async def interact(payload: InteractionInput, request: Request,
             identity: TerminalIdentity = Depends(require_terminal_permission("terminal.chat"))):
    identifier = identity.context_scope.terminal_id
    request.state.terminal_id = identifier
    try:
        outcome = await request.app.state.interactions.interact(identifier, payload.text,
            frozenset(identity.terminal.permissions))
    except HTTPException:
        raise
    except Exception:
        # Nunca registrar excepción de un procesador: podría contener el mensaje.
        return failure(request, 500, "processing_error", "No se pudo procesar la solicitud")
    if outcome.code:
        return failure(request, outcome.http_status, outcome.code, outcome.message)
    return InteractionResponse(request_id=request.state.interaction_id, terminal_id=identifier,
                               status="completed", message=outcome.message, response_type=outcome.response_type)


async def prepare(request):
    request.state.interaction_id = uuid.uuid4().hex
    # Leer por fragmentos ANTES del parser JSON. No confiar en Content-Length.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            return failure(request, 413, "input_too_large", "Solicitud demasiado grande")
        body.extend(chunk)
    request._body = bytes(body)
    return None
