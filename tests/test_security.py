"""API y persistencia reales contra SQLite temporal; sin servicios externos."""

import getpass
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update, text
from sqlalchemy.exc import IntegrityError, OperationalError

from nexo import cli, security
from nexo.config import Settings
from nexo.database import Database, administrators, audit, sessions
from nexo.main import create_app

PASSWORD = "SoloPruebas2026!Temporal"
ORIGIN = "http://localhost:8000"


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "data")
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def initialized(database):
    security.initialize_admin(database, "principal", PASSWORD)
    return database


@pytest.fixture
def client(initialized):
    app = create_app(Settings(initialized.data_dir))
    with TestClient(app, base_url=ORIGIN) as client:
        yield client


def login(client, **kwargs):
    return client.post("/api/v1/auth/login", headers={"Origin": ORIGIN},
                       json={"username": "principal", "password": PASSWORD, **kwargs})


def test_initialize_and_hash(database):
    security.initialize_admin(database, "principal", PASSWORD)
    with database.transaction() as db:
        admin = db.execute(select(administrators)).mappings().one()
        assert admin.password_hash.startswith("$argon2id$")
        assert PASSWORD not in admin.password_hash
        assert PasswordHasher().verify(admin.password_hash, PASSWORD)
        assert db.scalar(select(audit.c.event)) == "admin_initialized"
    with pytest.raises(ValueError, match="Ya existe"):
        security.initialize_admin(database, "segundo", PASSWORD)


@pytest.mark.parametrize("username,password", [("x", PASSWORD), ("Principal", PASSWORD),
                         ("principal", "corta1"), ("principal", "abcdefghijkl"),
                         ("principal", "1" * 129)])
def test_initialization_validation(database, username, password):
    with pytest.raises(ValueError):
        security.initialize_admin(database, username, password)


def test_login_cookie_and_storage(client, initialized):
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=3600" in cookie
    assert "secure" not in cookie
    token = client.cookies["nexo_session"]
    with initialized.transaction() as db:
        session = db.execute(select(sessions)).mappings().one()
        assert session.token_hash == security.digest(token) and token not in session.token_hash
        assert session.expires_at - session.created_at == 3600
    assert client.get("/api/v1/auth/me").json()["csrf_token"] == response.json()["csrf_token"]
    assert client.get("/api/v1/admin/status").status_code == 200


def test_secure_cookie(initialized):
    settings = Settings(initialized.data_dir, "https://nexo.home.arpa", "production")
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        response = client.post("/api/v1/auth/login", headers={"Origin": settings.origin},
                               json={"username": "principal", "password": PASSWORD})
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        assert "__Host-nexo_session=" in response.headers["set-cookie"]
        assert "Domain=" not in response.headers["set-cookie"]
        assert client.get("/api/v1/admin/status").status_code == 200


def test_https_scheme_case_cannot_disable_secure(tmp_path):
    assert Settings(tmp_path, "HTTPS://nexo.home.arpa", "production").secure_cookie


@pytest.mark.parametrize("origin,environment", [(ORIGIN, "production"),
    ("http://192.168.1.2", "development"), ("https://host/", "production"),
    ("https://user:pass@host", "production"), ("https://host", "typo")])
def test_unsafe_config_rejected(tmp_path, origin, environment):
    with pytest.raises(ValueError):
        Settings(tmp_path, origin, environment)


def test_uniform_invalid_credentials(client):
    known = login(client, password="incorrecta")
    unknown = login(client, username="desconocido")
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json() == {"detail": "Credenciales inválidas"}


def test_rate_limit_persists_across_apps(client, initialized, monkeypatch):
    timestamp = security.now()
    monkeypatch.setattr(security, "now", lambda: timestamp)
    for _ in range(5):
        assert login(client, password="incorrecta").status_code == 401
    with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as other:
        response = login(other)
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
        monkeypatch.setattr(security, "now", lambda: timestamp + 60)
        assert login(other).status_code == 200


def test_absolute_expiry(client, monkeypatch):
    timestamp = security.now()
    monkeypatch.setattr(security, "now", lambda: timestamp)
    response = login(client)
    expiry = response.json()["expires_at"]
    monkeypatch.setattr(security, "now", lambda: timestamp + 3599)
    assert client.get("/api/v1/auth/me").json()["expires_at"] == expiry
    monkeypatch.setattr(security, "now", lambda: timestamp + 3600)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_single_session_and_revocation(client, initialized):
    assert login(client).status_code == 200
    previous = client.cookies["nexo_session"]
    assert login(client).status_code == 200
    current = client.cookies["nexo_session"]
    client.cookies.set("nexo_session", previous, domain="localhost.local", path="/")
    assert client.get("/api/v1/admin/status").status_code == 401
    client.cookies.set("nexo_session", current, domain="localhost.local", path="/")
    with initialized.transaction(write=True) as db:
        row = db.execute(select(sessions).where(sessions.c.token_hash == security.digest(current))).mappings().one()
        security.revoke_session(db, row.id, 1, "operator")
    assert client.get("/api/v1/admin/status").status_code == 401


def test_logout_and_replay(client):
    response = login(client)
    token = client.cookies["nexo_session"]
    response = client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN,
                          "X-CSRF-Token": response.json()["csrf_token"]})
    assert response.status_code == 204 and not response.content
    assert not client.cookies
    client.cookies.set("nexo_session", token)
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/admin/status"])
def test_protected_without_auth(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("headers", [{}, {"Origin": "null"}, {"Origin": "https://evil.example"},
                                      {"Origin": ORIGIN}, {"Origin": ORIGIN, "X-CSRF-Token": "incorrecto"}])
def test_csrf_rejected(client, headers):
    login(client)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", "http://localhost:8000.evil"])
def test_login_origin_and_cors(client, origin):
    headers = {"Origin": origin} if origin else {}
    response = client.post("/api/v1/auth/login", headers=headers,
                           json={"username": "principal", "password": PASSWORD})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_audit_contains_no_secrets(client, initialized, caplog):
    login(client, password="error-secreto")
    response = login(client)
    csrf = response.json()["csrf_token"]
    token = client.cookies["nexo_session"]
    client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    client.get("/api/v1/admin/status")
    with initialized.transaction() as db:
        rows = [dict(row) for row in db.execute(select(audit)).mappings()]
    serialized = json.dumps(rows) + caplog.text
    for secret in (PASSWORD, token, csrf, "error-secreto", "$argon2id$"):
        assert secret not in serialized
    assert {"admin_initialized", "login_success", "login_failure", "logout", "session_revoked",
            "admin_access_denied"} <= {row["event"] for row in rows}


def test_retention(database, monkeypatch):
    with database.transaction(write=True) as db:
        db.execute(insert(audit), [dict(occurred_at=security.now(), event="admin_access_denied", result="denied")
                                  for _ in range(security.AUDIT_LIMIT + 10)])
        db.execute(insert(audit).values(occurred_at=0, event="old", result="failure"))
        security.record(db, "login_failure", "failure")
        assert db.scalar(select(func.count()).select_from(audit)) == security.AUDIT_LIMIT
        assert db.scalar(select(func.count()).select_from(audit).where(audit.c.event == "old")) == 0


def test_persistence_and_migration_idempotence(client, initialized):
    assert login(client).status_code == 200
    token = client.cookies["nexo_session"]
    initialized.close()
    reopened = Database(initialized.data_dir)
    reopened.migrate()
    reopened.check()
    with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as other:
        other.cookies.set("nexo_session", token)
        assert other.get("/api/v1/auth/me").status_code == 200
    with reopened.transaction() as db:
        assert db.scalar(select(func.count()).select_from(administrators)) == 1
        tables = set(db.scalars(text("SELECT name FROM sqlite_master WHERE type='table'")))
        assert tables == {"alembic_version", "administrators", "admin_sessions", "security_audit",
                          "terminals", "terminal_permissions", "pairing_codes", "pairing_rate"}
        assert db.scalar(text("PRAGMA integrity_check")) == "ok"
        assert db.scalar(text("PRAGMA foreign_keys")) == 1
    reopened.close()


def test_database_constraints(initialized):
    with pytest.raises(IntegrityError):
        with initialized.transaction(write=True) as db:
            db.execute(insert(administrators).values(id=2, username="otro", password_hash="irrelevante",
                                                     active=True, created_at=1, updated_at=1))
    with pytest.raises(IntegrityError):
        with initialized.transaction(write=True) as db:
            db.execute(insert(sessions).values(token_hash="f" * 64, administrator_id=99,
                                                created_at=1, expires_at=3601, revoked=False))
    with initialized.transaction(write=True) as db:
        db.execute(insert(sessions).values(token_hash="a" * 64, administrator_id=1,
                                           created_at=1, expires_at=3601, revoked=False))
    with pytest.raises(IntegrityError):
        with initialized.transaction(write=True) as db:
            db.execute(insert(sessions).values(token_hash="b" * 64, administrator_id=1,
                                               created_at=2, expires_at=3602, revoked=False))


def test_migration_downgrade_upgrade(database):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with database.engine.connect().execution_options(write=True) as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    with database.transaction() as db:
        assert not db.scalar(text("SELECT name FROM sqlite_master WHERE name='administrators'"))
    database.migrate()
    database.check()


def test_audit_failure_rolls_back_new_login(client, initialized, monkeypatch):
    assert login(client).status_code == 200
    original_token = client.cookies["nexo_session"]
    original_record = security.record
    def fail_after_insert(db, event, *args, **kwargs):
        if event == "login_success":
            raise OperationalError("redacted", {}, Exception("unavailable"))
        original_record(db, event, *args, **kwargs)
    monkeypatch.setattr(security, "record", fail_after_insert)
    assert login(client).status_code == 503
    assert client.cookies["nexo_session"] == original_token
    assert client.get("/api/v1/admin/status").status_code == 200
    with initialized.transaction() as db:
        assert db.scalar(select(func.count()).select_from(sessions)) == 1
        assert db.scalar(select(sessions.c.revoked)) is False


def test_disabled_admin(client, initialized):
    login(client)
    with initialized.transaction(write=True) as db:
        db.execute(update(administrators).values(active=False))
    assert client.get("/api/v1/admin/status").status_code == 401
    assert login(client).status_code == 401


def test_database_failure_safe(client, initialized):
    with initialized.transaction(write=True) as db:
        db.execute(text("DROP TABLE security_audit"))
    response = login(client)
    assert response.status_code == 503
    assert response.json() == {"detail": "Persistencia temporalmente no disponible"}
    assert PASSWORD not in response.text and "sqlite" not in response.text


def test_validation_does_not_echo_password(client):
    response = login(client, password="SECRETO" * 100)
    assert response.status_code == 422 and "SECRETO" not in response.text


def test_atomic_initialization(database):
    def create():
        try:
            security.initialize_admin(database, "principal", PASSWORD)
            return "created"
        except (ValueError, OperationalError):
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: create(), range(2))) == ["created", "rejected"]


def test_conflicting_login_rejected(client, initialized):
    with initialized.transaction(write=True) as db:
        db.execute(text("SELECT 1"))  # Fuerza el BEGIN perezoso y mantiene un bloqueo real.
        assert login(client).status_code == 503
    security.HASH_GATE.acquire()
    try:
        assert login(client).status_code == 503
    finally:
        security.HASH_GATE.release()


def test_cli_password_no_echo(database, monkeypatch, capsys):
    monkeypatch.setenv("NEXO_DATA_DIR", str(database.data_dir))
    monkeypatch.setattr(sys, "argv", ["nexo.cli", "init-admin"])
    monkeypatch.setattr("builtins.input", lambda _: "principal")
    monkeypatch.setattr(getpass, "getpass", lambda _: PASSWORD)
    assert cli.main() == 0
    assert PASSWORD not in capsys.readouterr().out
    assert cli.main() == 1


def test_cli_refuses_echo_fallback(database, monkeypatch):
    import warnings
    monkeypatch.setenv("NEXO_DATA_DIR", str(database.data_dir))
    monkeypatch.setattr(sys, "argv", ["nexo.cli", "init-admin"])
    monkeypatch.setattr("builtins.input", lambda _: "principal")
    def fallback(_):
        warnings.warn("Sin terminal seguro", getpass.GetPassWarning)
        return PASSWORD
    monkeypatch.setattr(getpass, "getpass", fallback)
    assert cli.main() == 1
    with database.transaction() as db:
        assert db.scalar(select(administrators.c.id)) is None
