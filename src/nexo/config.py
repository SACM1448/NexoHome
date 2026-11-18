"""Configuración explícita; HTTP solo para desarrollo en loopback."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    origin: str = "http://localhost:8000"
    environment: str = "development"
    metrics_interval: int = 30
    context_ttl: int = 900

    def __post_init__(self):
        if not 5 <= self.metrics_interval <= 300:
            raise ValueError("Intervalo de métricas: entre 5 y 300 segundos")
        if not 60 <= self.context_ttl <= 86400:
            raise ValueError("Caducidad de contexto: entre 60 y 86400 segundos")
        url = urlsplit(self.origin)
        # Evaluar también el puerto: urlsplit pospone esa validación.
        _ = url.port
        if (self.environment not in {"development", "production"}
                or url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.path or url.query or url.fragment
                or any(character.isspace() for character in self.origin)):
            raise ValueError("Configuración de entorno/origen inválida")
        if self.environment == "production" and url.scheme != "https":
            raise ValueError("Producción requiere origen HTTPS")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("HTTP solo está permitido en loopback")

    @property
    def secure_cookie(self) -> bool:
        return urlsplit(self.origin).scheme == "https"

    @property
    def cookie_name(self) -> str:
        return "__Host-nexo_session" if self.secure_cookie else "nexo_session"

    @classmethod
    def from_env(cls):
        return cls(Path(os.environ.get("NEXO_DATA_DIR", "data")).resolve(),
                   os.environ.get("NEXO_ORIGIN", "http://localhost:8000"),
                   os.environ.get("NEXO_ENV", "development"),
                   int(os.environ.get("NEXO_METRICS_INTERVAL", "30")),
                   int(os.environ.get("NEXO_CONTEXT_TTL", "900")))
