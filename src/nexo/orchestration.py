"""Registro local explícito y exclusión operativa en un único proceso.

Solo código de confianza registra capacidades al arrancar; nunca el cliente.
Los manejadores son async, cooperativos y deben acotar sus operaciones de E/S.
"""

import asyncio
import inspect
import math
import re
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


def normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if unicodedata.category(c) != "Mn").strip(" ¡!¿?.\n\t")


def canonical_key(key: str) -> str:
    # Rechazar alias en lugar de permitir que el mismo recurso tenga dos claves.
    if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*:[a-z0-9][a-z0-9_.:-]{0,127}", key):
        raise ValueError("Clave de recurso no canónica")
    return key


class Busy(Exception):
    pass


class ResourceLocks:
    def __init__(self):
        self._guard = threading.Lock()
        self._held: set[str] = set()

    @contextmanager
    def acquire(self, keys):
        keys = frozenset(canonical_key(key) for key in keys)
        with self._guard:
            if self._held.intersection(keys):
                raise Busy()
            self._held.update(keys)
        try:
            yield
        finally:
            # No await: la cancelación tampoco puede interrumpir la liberación.
            with self._guard:
                self._held.difference_update(keys)


class CapabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message: str = Field(min_length=1, max_length=2000)
    response_type: Literal["text", "unavailable"] = "text"


@dataclass(frozen=True, repr=False)
class ExecutionContext:
    terminal_id: str
    messages: tuple = ()


@dataclass(frozen=True)
class Capability:
    identifier: str
    name: str
    permissions: frozenset[str]
    resources: frozenset[str]
    input_model: type[BaseModel]
    handler: Callable[[BaseModel, ExecutionContext], Awaitable[CapabilityResult]]
    result_model: type[CapabilityResult] = CapabilityResult
    timeout: float = 10.0
    confirmation_required: bool = False


class CapabilityRegistry:
    def __init__(self, capabilities=()):
        self._capabilities = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: Capability):
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", capability.identifier):
            raise ValueError("Identificador inválido")
        if capability.identifier in self._capabilities:
            raise ValueError("Capacidad duplicada")
        if (not capability.name.strip() or not isinstance(capability.permissions, frozenset)
                or not isinstance(capability.resources, frozenset)
                or not all(isinstance(p, str) and p for p in capability.permissions)
                or not issubclass(capability.input_model, BaseModel)
                or not issubclass(capability.result_model, CapabilityResult)
                or not inspect.iscoroutinefunction(capability.handler)
                or not math.isfinite(capability.timeout) or not 0 < capability.timeout <= 60):
            raise ValueError("Contrato de capacidad inválido")
        for key in capability.resources:
            canonical_key(key)
            if key.startswith("terminal:"):
                raise ValueError("Espacio de claves reservado")
        self._capabilities[capability.identifier] = capability

    def get(self, identifier):
        return self._capabilities.get(identifier)


class IntentRouter:
    """Coincidencia completa normalizada; nunca prioridad por coincidencia parcial."""

    def __init__(self, registry: CapabilityRegistry, rules, fallback=None):
        if fallback is not None and registry.get(fallback) is None:
            raise ValueError("Capacidad alternativa inválida")
        self._fallback = fallback
        self._routes: dict[str, set[str]] = {}
        for phrase, identifier in rules:
            if registry.get(identifier) is None or not normalized(phrase):
                raise ValueError("Regla inválida")
            self._routes.setdefault(normalized(phrase), set()).add(identifier)

    def resolve(self, text):
        matches = self._routes.get(normalized(text), set())
        return next(iter(matches)) if len(matches) == 1 else (None if matches else self._fallback)


@dataclass(frozen=True)
class Outcome:
    message: str
    response_type: str = "text"
    http_status: int = 200
    code: str | None = None


class Orchestrator:
    def __init__(self, registry, router, locks=None):
        self.registry = registry
        self.router = router
        self.locks = locks or ResourceLocks()

    async def execute(self, text, permissions, context: ExecutionContext):
        identifier = self.router.resolve(text)
        capability = self.registry.get(identifier)
        if capability is None:
            return Outcome("Solicitud no reconocida. IA, voz, acciones e integraciones todavía no están disponibles. Escribe ayuda.", "unavailable")
        if not capability.permissions <= permissions:
            return Outcome("Permiso de terminal requerido", "error", 403, "forbidden")
        if capability.confirmation_required:
            # Reserva segura: no existe todavía un mecanismo para confirmar.
            return Outcome("Esta función requiere confirmación explícita y todavía no está disponible.",
                           "error", 409, "confirmation_required")
        try:
            payload = capability.input_model.model_validate({"text": text}, strict=True)
        except ValidationError:
            return Outcome("Solicitud inválida", "error", 422, "invalid_input")
        try:
            with self.locks.acquire(capability.resources | {canonical_key("terminal:" + context.terminal_id)}):
                async with asyncio.timeout(capability.timeout):
                    result = await capability.handler(payload, context)
                    result = capability.result_model.model_validate(result)
                    return Outcome(result.message, result.response_type)
        except Busy:
            return Outcome("Un recurso necesario está ocupado por otra operación. Inténtalo más tarde.",
                           "error", 409, "resource_busy")
        except TimeoutError:
            return Outcome("La operación superó el tiempo permitido; no se reintentará automáticamente.",
                           "error", 504, "execution_timeout")
        except Exception:
            # No registrar excepciones, parámetros, resultados ni contenido privado.
            return Outcome("No se pudo procesar la solicitud", "error", 500, "processing_error")
