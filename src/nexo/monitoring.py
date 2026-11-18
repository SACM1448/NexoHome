"""Consultas administrativas locales, acotadas y sin ejecución de comandos."""

import math
import platform
import threading
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from nexo.database import audit, terminals
from nexo.security import require_admin_permission, now

VERSION = "0.1.0"
UNAVAILABLE = "No disponible"
UPDATE_NOTICE = "La comprobación automática de vulnerabilidades estará disponible en una fase posterior"


def metric(read, unit, scope, limitation=None):
    try:
        value = read()
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError
        return {"value": value, "unit": unit, "scope": scope, "limitation": limitation}
    except (OSError, psutil.Error, AttributeError, NotImplementedError, ValueError):
        return {"value": None, "unit": unit, "scope": scope,
                "limitation": "El sistema operativo o hardware no ofrece esta lectura."}


class Monitor:
    def __init__(self, data_dir, interval):
        self.data_dir, self.interval = data_dir, interval
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.cached = None
        self.sampled = 0.0
        self.previous_cpu = None

    def cpu(self):
        values = psutil.cpu_times()
        # guest ya está incluido en user/nice en Linux.
        total = sum(values) - getattr(values, "guest", 0) - getattr(values, "guest_nice", 0)
        idle = values.idle + getattr(values, "iowait", 0)
        previous, self.previous_cpu = self.previous_cpu, (total, idle)
        if previous is None or total <= previous[0]:
            return None
        return round(max(0, min(100, 100 * (1 - (idle - previous[1]) / (total - previous[0])))), 1)

    @staticmethod
    def temperature():
        for name, entries in psutil.sensors_temperatures().items():
            if name.lower() in {"cpu_thermal", "coretemp", "k10temp", "cpu-thermal"}:
                for entry in entries:
                    if entry.current is not None:
                        return entry.current
        return None

    def snapshot(self):
        with self.lock:
            if self.cached is not None and time.monotonic() - self.sampled < self.interval:
                return self.cached
            container = Path("/.dockerenv").exists()
            scope = "Sistema visible desde el contenedor" if container else "Sistema operativo local"
            warning = ("Las lecturas del kernel pueden corresponder al anfitrión o a la VM de Docker; "
                       "no representan los límites del contenedor ni acreditan métricas de la Raspberry.") if container else None
            metrics = {
                "cpu_percent": metric(self.cpu, "%", scope, warning),
                "ram_percent": metric(lambda: psutil.virtual_memory().percent, "%", scope, warning),
                "ram_used_bytes": metric(lambda: psutil.virtual_memory().used, "bytes", scope, warning),
                "ram_total_bytes": metric(lambda: psutil.virtual_memory().total, "bytes", scope, warning),
                "storage_percent": metric(lambda: psutil.disk_usage(str(self.data_dir)).percent, "%", "Sistema de archivos de persistencia", warning),
                "storage_free_bytes": metric(lambda: psutil.disk_usage(str(self.data_dir)).free, "bytes", "Sistema de archivos de persistencia", warning),
                "system_uptime_seconds": metric(lambda: max(0, time.time() - psutil.boot_time()), "s", scope, warning),
                "service_uptime_seconds": metric(lambda: time.monotonic() - self.started, "s", "Proceso NEXO"),
                "process_rss_bytes": metric(lambda: psutil.Process().memory_info().rss, "bytes", "Proceso NEXO"),
                "cpu_temperature_celsius": metric(self.temperature, "°C", scope, warning),
            }
            if metrics["cpu_percent"]["value"] is None:
                metrics["cpu_percent"]["limitation"] = "Se requieren dos muestras válidas para calcular CPU."
            self.cached = {"sampled_at": now(), "refresh_seconds": self.interval,
                           "execution": "container" if container else "local",
                           "os": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
                           "metrics": metrics}
            self.sampled = time.monotonic()
            return self.cached


def persistence(database):
    try:
        with database.transaction() as db:
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            available = db.scalar(text("SELECT 1")) == 1
        return {"status": "ok" if available and revision == "0002" else "unavailable",
                "engine": "SQLite", "migration": revision,
                "check": "Consulta de lectura y revisión de migración; no es un análisis integral de integridad."}
    except (SQLAlchemyError, OSError):
        return {"status": "unavailable", "engine": "SQLite", "migration": None,
                "check": "No fue posible consultar la persistencia."}


def inventory():
    packages = {}
    for name in ("fastapi", "starlette", "uvicorn", "pydantic", "SQLAlchemy", "alembic", "argon2-cffi", "psutil"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"nexo_home": VERSION, "python": platform.python_version(), "dependencies": packages,
            "deployment": "Docker" if Path("/.dockerenv").exists() else "Python local",
            "image_digest": None, "image_limitation": "El digest de imagen no está disponible dentro del proceso; sin acceso al socket Docker.",
            "last_check_at": None, "last_check_result": None, "checks_available": False,
            "notice": UPDATE_NOTICE}


router = APIRouter(prefix="/api/v1/admin", tags=["monitoring"],
                   dependencies=[Depends(require_admin_permission)])


@router.get("/summary")
def summary(request: Request):
    with request.app.state.database.transaction() as db:
        total = db.scalar(select(func.count()).select_from(terminals))
        linked = db.scalar(select(func.count()).select_from(terminals).where(
            terminals.c.revoked_at.is_(None), terminals.c.expires_at > now()))
    return {"service": "ok", "version": VERSION, "persistence": persistence(request.app.state.database),
            "terminals": {"total": total, "linked": linked,
                          "note": "Vinculado significa credencial vigente; no confirma conexión en línea."}}


@router.get("/metrics")
def metrics(request: Request):
    return request.app.state.monitor.snapshot()


@router.get("/persistence")
def persistence_status(request: Request):
    return persistence(request.app.state.database)


@router.get("/audit")
def recent_audit(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    with request.app.state.database.transaction() as db:
        rows = db.execute(select(audit.c.id, audit.c.occurred_at, audit.c.event, audit.c.result,
                                 audit.c.reason, audit.c.subject_id).order_by(audit.c.id.desc()).limit(limit)).mappings()
        return [dict(row) for row in rows]


@router.get("/updates")
def updates():
    return inventory()
