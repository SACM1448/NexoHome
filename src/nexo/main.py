"""Aplicación ASGI, portal inicial y seguridad administrativa."""

from pathlib import Path
from typing import Literal
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from nexo import interactions
from nexo.config import Settings
from nexo.database import Database
from nexo.security import router as security_router
from nexo.terminals import router as terminals_router
from nexo.monitoring import Monitor, VERSION, router as monitoring_router

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
ADMIN_PAGES = {
    "dashboard": ("Resumen", "Tu hogar, de un vistazo", "Estado general de NEXO Home y accesos a tu sistema."),
    "terminals": ("Terminales", "Cada terminal, bajo control", "Vincula dispositivos y administra sus permisos desde un solo lugar."),
    "resources": ("Recursos", "El pulso de tu sistema", "CPU, memoria y almacenamiento con lecturas locales reales."),
    "audit": ("Auditoría", "Actividad y seguridad", "Consulta los eventos recientes de acceso y administración."),
    "updates": ("Actualizaciones", "Actualizaciones y seguridad", "Versiones instaladas y estado de las comprobaciones de seguridad."),
}


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["nexo-home"] = "nexo-home"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.data_dir)

    @asynccontextmanager
    async def lifespan(app):
        try:
            database.check()
        except (SQLAlchemyError, OSError):
            raise RuntimeError("Persistencia no disponible; ejecuta migraciones") from None
        try:
            yield
        finally:
            app.state.interactions.clear()
            database.close()

    app = FastAPI(title="NEXO Home", version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.interactions = interactions.InteractionService(settings.context_ttl)
    app.state.settings = settings
    app.state.database = database
    app.state.monitor = Monitor(settings.data_dir, settings.metrics_interval)

    @app.exception_handler(SQLAlchemyError)
    async def persistence_error(request, error):
        if request.url.path == interactions.PATH:
            return interactions.failure(request, 503, "persistence_unavailable", "Persistencia temporalmente no disponible")
        return JSONResponse({"detail": "Persistencia temporalmente no disponible"}, status_code=503,
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path == interactions.PATH:
            return interactions.failure(request, 422, "invalid_input", "Solicitud inválida")
        # La respuesta predeterminada puede incluir el valor de la contraseña.
        return JSONResponse({"detail": "Solicitud inválida"}, status_code=422)

    from starlette.exceptions import HTTPException as StarletteHTTPException
    from fastapi.exception_handlers import http_exception_handler

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        if request.url.path == interactions.PATH:
            codes = {401: "invalid_credential", 403: "forbidden", 409: "terminal_busy",
                     429: "rate_limited", 503: "capacity_unavailable", 405: "method_not_allowed"}
            return interactions.failure(request, error.status_code, codes.get(error.status_code, "request_error"),
                                        str(error.detail), error.headers)
        return await http_exception_handler(request, error)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = None
        if request.url.path == interactions.PATH:
            response = await interactions.prepare(request)
        if response is None:
            response = await call_next(request)
        if request.url.path.startswith(("/api/v1/auth/", "/api/v1/admin/", "/api/v1/terminal/")):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    app.include_router(interactions.router)
    app.include_router(security_router)
    app.include_router(terminals_router)
    app.include_router(monitoring_router)
    api = APIRouter(prefix="/api/v1")

    @api.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse()

    app.include_router(api)
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/admin/{page}", include_in_schema=False, response_class=HTMLResponse)
    async def admin_page(page: str) -> HTMLResponse:
        if page not in ADMIN_PAGES:
            raise HTTPException(404, "Página no encontrada")
        label, title, description = ADMIN_PAGES[page]
        # Solo fragmentos locales de la lista permitida; sin datos de usuario.
        html = (WEB_DIR / "admin-layout.html").read_text(encoding="utf-8")
        content = (WEB_DIR / "admin" / f"{page}.html").read_text(encoding="utf-8")
        for key, value in {"PAGE": page, "LABEL": label, "TITLE": title,
                           "DESCRIPTION": description, "CONTENT": content}.items():
            html = html.replace("{{" + key + "}}", value)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/terminal", include_in_schema=False)
    async def terminal() -> FileResponse:
        return FileResponse(WEB_DIR / "terminal.html")

    return app


app = create_app()
