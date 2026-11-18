"""Vinculación real sobre SQLite migrado, identidades y fronteras de autorización."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError

from nexo import security, terminals as module
from nexo.config import Settings
from nexo.database import Database, audit, pairing_codes, pairing_rate, sessions, terminal_permissions, terminals
from nexo.main import create_app
from test_security import database, initialized, client, login, ORIGIN


@pytest.fixture
def admin(client):
    result = login(client)
    assert result.status_code == 200
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]})
    return client


def code(admin, permissions=None):
    response = admin.post("/api/v1/admin/pairing-codes", json={
        "permissions": permissions if permissions is not None else ["terminal.status"]})
    assert response.status_code == 201
    return response.json()


def pair(client, value, name="Tableta"):
    return client.post("/api/v1/terminal/pair", json={"code": value, "name": name})


def linked(admin, permissions=None, name="Tableta"):
    response = pair(admin, code(admin, permissions)["code"], name)
    assert response.status_code == 201
    result = response.json()
    return result, {"Authorization": "Bearer " + result["credential"]}


def test_generation_and_protected_storage(admin, initialized):
    value = code(admin)
    assert len(value["code"]) == 96 and value["code"].isalnum()
    assert value["state"] == "pending" and value["attempts_remaining"] == 5
    assert admin.get("/api/v1/admin/pairing-codes/" + value["id"]).json()["state"] == "pending"
    with initialized.transaction() as db:
        row = db.execute(select(pairing_codes)).mappings().one()
        assert row.expires_at-row.created_at == 300
        assert row.code_hash == security.digest(value["code"])
        assert value["code"] not in str(dict(row))


def test_generation_requires_admin_and_csrf(client):
    path = "/api/v1/admin/pairing-codes"
    assert client.post(path, json={}).status_code == 401
    result = login(client)
    for headers in ({}, {"Origin": ORIGIN}, {"Origin": "https://evil.example", "X-CSRF-Token": result.json()["csrf_token"]}):
        assert client.post(path, json={}, headers=headers).status_code == 403
    assert client.get("/api/v1/admin/terminals").status_code == 200


def test_link_valid_and_identity(admin, initialized):
    value = code(admin)
    response = pair(admin, value["code"])
    assert response.status_code == 201
    data = response.json()
    assert data["token_type"] == "Bearer"
    assert data["terminal"]["state"] == "linked"
    assert data["terminal"]["voice_config"] == {"language": "es", "voice_id": None}
    headers = {"Authorization": "Bearer " + data["credential"]}
    assert admin.get("/api/v1/terminal/me", headers=headers).json() == data["terminal"]
    assert admin.get("/api/v1/terminal/status", headers=headers).status_code == 200
    assert admin.get("/api/v1/admin/pairing-codes/"+value["id"]).json()["state"] == "consumed"
    with initialized.transaction() as db:
        row = db.execute(select(terminals)).mappings().one()
        assert row.credential_hash == security.digest(data["credential"])
        assert data["credential"] not in str(dict(row))


@pytest.mark.parametrize("mode", ["expired", "reused", "incorrect", "revoked", "unknown"])
def test_invalid_codes(admin, monkeypatch, mode):
    timestamp = security.now()
    monkeypatch.setattr(security, "now", lambda: timestamp)
    value = code(admin)
    raw = value["code"]
    if mode == "expired":
        monkeypatch.setattr(security, "now", lambda: timestamp + 300)
    elif mode == "reused":
        assert pair(admin, raw).status_code == 201
    elif mode == "incorrect":
        raw = raw[:32] + "0" * 64
    elif mode == "revoked":
        assert admin.delete("/api/v1/admin/pairing-codes/"+value["id"]).status_code == 204
    else:
        raw = "f" * 96
    response = pair(admin, raw)
    assert response.status_code == 401
    assert response.json() == {"detail": "Código de vinculación inválido"}


def test_per_code_limit_persistent(admin, initialized, monkeypatch):
    timestamp = security.now()
    monkeypatch.setattr(security, "now", lambda: timestamp)
    value = code(admin)
    for _ in range(5):
        assert pair(admin, value["code"][:32]+"0"*64).status_code == 401
    assert admin.get("/api/v1/admin/pairing-codes/"+value["id"]).json()["state"] == "locked"
    monkeypatch.setattr(security, "now", lambda: timestamp+60)
    with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as other:
        assert pair(other, value["code"]).status_code == 401


def test_global_limit_survives_restart(admin, initialized, monkeypatch):
    timestamp = security.now()
    monkeypatch.setattr(security, "now", lambda: timestamp)
    value = code(admin)
    for _ in range(10):
        assert pair(admin, "unknown").status_code == 401
    with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as other:
        assert pair(other, value["code"]).status_code == 429
        monkeypatch.setattr(security, "now", lambda: timestamp+60)
        assert pair(other, value["code"]).status_code == 201


def test_atomic_code_consumption(admin, initialized):
    raw = code(admin)["code"]
    def attempt(_):
        with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as other:
            return pair(other, raw).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, range(2)))
    assert statuses.count(201) == 1
    assert all(status in (201, 401, 503) for status in statuses)
    assert pair(admin, raw).status_code == 401
    with initialized.transaction() as db:
        assert db.scalar(select(func.count()).select_from(terminals)) == 1


def test_independent_identities_permissions_context(admin):
    one, headers1 = linked(admin, ["terminal.status"], "Motorola")
    two, headers2 = linked(admin, ["terminal.chat"], "Tableta")
    assert one["terminal"]["id"] != two["terminal"]["id"]
    assert one["credential"] != two["credential"]
    assert admin.get("/api/v1/terminal/me", headers=headers1).json()["name"] == "Motorola"
    assert admin.get("/api/v1/terminal/me", headers=headers2).json()["name"] == "Tableta"
    assert admin.get("/api/v1/terminal/status", headers=headers1).status_code == 200
    assert admin.get("/api/v1/terminal/status", headers=headers2).status_code == 403
    identity1 = module.TerminalIdentity(module.TerminalView(**one["terminal"]))
    identity2 = module.TerminalIdentity(module.TerminalView(**two["terminal"]))
    assert identity1.context_scope != identity2.context_scope


def test_permission_updates_immediate_and_deny_default(admin):
    result, headers = linked(admin, [])
    identifier = result["terminal"]["id"]
    path = f"/api/v1/admin/terminals/{identifier}/permissions"
    assert admin.get("/api/v1/terminal/status", headers=headers).status_code == 403
    assert admin.put(path, json={"permissions": ["terminal.status"]}).status_code == 200
    assert admin.get("/api/v1/terminal/status", headers=headers).status_code == 200
    assert admin.put(path, json={"permissions": []}).status_code == 200
    assert admin.get("/api/v1/terminal/status", headers=headers).status_code == 403
    assert admin.put(path, json={"permissions": ["admin"]}).status_code == 422
    assert admin.put(path, json={"permissions": ["terminal.status"]*2}).status_code == 422


def test_credentials_cannot_cross_admin_boundary(admin):
    result, headers = linked(admin)
    for path in ("auth/me", "admin/status", "admin/terminals"):
        # Incluso con cookie admin presente: no heredar privilegios al presentar Bearer.
        assert admin.get("/api/v1/"+path, headers=headers).status_code == 401
    assert admin.post("/api/v1/admin/pairing-codes", headers=headers, json={}).status_code == 401
    assert admin.get("/api/v1/terminal/me").status_code == 401
    cookie = admin.cookies["nexo_session"]
    assert admin.get("/api/v1/terminal/me", headers={"Authorization": "Bearer "+cookie}).status_code == 401
    assert admin.get("/api/v1/terminal/me?credential="+result["credential"]).status_code == 401
    with TestClient(admin.app, base_url=ORIGIN) as other:
        assert other.get("/api/v1/admin/status", headers=headers).status_code == 401


@pytest.mark.parametrize("method,suffix,body", [("patch", "/name", {"name": "Nuevo"}),
    ("put", "/permissions", {"permissions": []}), ("delete", "", None)])
def test_admin_mutations_preserve_csrf(admin, method, suffix, body):
    result, _ = linked(admin)
    path = "/api/v1/admin/terminals/" + result["terminal"]["id"] + suffix
    headers = {"Origin": "https://evil.example"}
    assert admin.request(method, path, json=body, headers=headers).status_code == 403
    headers = {"X-CSRF-Token": "wrong"}
    assert admin.request(method, path, json=body, headers=headers).status_code == 403


def test_rename_list_revoke_and_replay(admin):
    first, headers = linked(admin)
    second, headers2 = linked(admin)
    identifier = first["terminal"]["id"]
    path = "/api/v1/admin/terminals/"+identifier
    assert admin.patch(path+"/name", json={"name": "Sala"}).json()["name"] == "Sala"
    assert admin.patch(path+"/name", json={"name": "   "}).status_code == 422
    assert admin.get("/api/v1/terminal/me", headers=headers).json()["name"] == "Sala"
    assert len(admin.get("/api/v1/admin/terminals").json()) == 2
    assert admin.delete(path).status_code == 204
    assert admin.delete(path).status_code == 204
    assert admin.get("/api/v1/terminal/me", headers=headers).status_code == 401
    assert admin.get("/api/v1/terminal/status", headers=headers).status_code == 401
    assert admin.get("/api/v1/terminal/me", headers=headers2).status_code == 200
    assert {r["state"] for r in admin.get("/api/v1/admin/terminals").json()} == {"linked", "revoked"}


def test_refresh_preserves_revocation_history_permissions_and_admin_session(admin, initialized):
    first, revoked_headers = linked(admin, ["terminal.status", "terminal.chat"], "Revocado")
    second, active_headers = linked(admin, ["terminal.status"], "Activo")
    identifier = first["terminal"]["id"]
    assert admin.delete("/api/v1/admin/terminals/" + identifier).status_code == 204
    assert admin.get("/api/v1/terminal/me", headers=revoked_headers).status_code == 401
    assert admin.get("/api/v1/terminal/status", headers=active_headers).status_code == 200
    before_identity = admin.get("/api/v1/auth/me").json()
    before_cookies = dict(admin.cookies)

    def snapshot():
        with initialized.transaction() as db:
            return {table.name: list(db.execute(select(table).order_by(*table.primary_key.columns)))
                    for table in (terminals, terminal_permissions, audit, sessions)}

    before = snapshot()
    for _ in range(2):
        response = admin.get("/api/v1/admin/terminals")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        rows = {row["id"]: row for row in response.json()}
        # El endpoint conserva historial; solo la interfaz filtra la lista visible.
        assert len(rows) == 2
        assert rows[identifier]["state"] == "revoked" and rows[identifier]["revoked_at"] is not None
        active = rows[second["terminal"]["id"]]
        assert active["state"] == "linked" and active["revoked_at"] is None
        assert active["permissions"] == ["terminal.status"]
    assert admin.get("/api/v1/auth/me").json() == before_identity
    assert dict(admin.cookies) == before_cookies
    assert snapshot() == before
    assert any(row.event == "terminal_revoked" and row.subject_id == identifier
               for row in before[audit.name])
    assert admin.get("/api/v1/admin/terminals", headers=active_headers).status_code == 401


def test_terminal_expiry_and_activity(admin, initialized, monkeypatch):
    timestamp = security.now()
    monkeypatch.setattr(security, "now", lambda: timestamp)
    result, headers = linked(admin)
    expiry = result["terminal"]["expires_at"]
    assert expiry == timestamp+module.CREDENTIAL_TTL
    monkeypatch.setattr(security, "now", lambda: timestamp+59)
    assert admin.get("/api/v1/terminal/me", headers=headers).json()["last_activity"] == timestamp
    monkeypatch.setattr(security, "now", lambda: timestamp+60)
    assert admin.get("/api/v1/terminal/me", headers=headers).json()["last_activity"] == timestamp+60
    monkeypatch.setattr(security, "now", lambda: expiry)
    assert admin.get("/api/v1/terminal/me", headers=headers).status_code == 401


def test_persistence_restart(admin, initialized):
    result, headers = linked(admin)
    with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as other:
        assert other.get("/api/v1/terminal/me", headers=headers).json()["id"] == result["terminal"]["id"]
    admin.delete("/api/v1/admin/terminals/"+result["terminal"]["id"])
    with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as other:
        assert other.get("/api/v1/terminal/me", headers=headers).status_code == 401


def test_no_secrets_in_audit_or_logs(admin, initialized, caplog):
    value = code(admin)
    response = pair(admin, value["code"])
    credential = response.json()["credential"]
    secret = "incorrect-secret"
    pair(admin, secret)
    admin.delete("/api/v1/admin/terminals/"+response.json()["terminal"]["id"])
    with initialized.transaction() as db:
        serialized = json.dumps([dict(row) for row in db.execute(select(audit)).mappings()])
    for raw in (value["code"], credential, secret, security.digest(credential), security.digest(value["code"])):
        assert raw not in serialized+caplog.text
    assert "terminal_linked" in serialized and "terminal_revoked" in serialized


def test_pairing_audit_failure_rolls_back(admin, initialized, monkeypatch):
    value = code(admin)
    original = security.record
    def fail(db, event, *args, **kwargs):
        if event == "terminal_linked":
            raise OperationalError("redacted", {}, Exception("unavailable"))
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(security, "record", fail)
    assert pair(admin, value["code"]).status_code == 503
    with initialized.transaction() as db:
        assert db.scalar(select(func.count()).select_from(terminals)) == 0
        assert db.scalar(select(pairing_codes.c.consumed_at)) is None
        assert db.scalar(select(pairing_codes.c.attempts)) == 0
    monkeypatch.setattr(security, "record", original)
    assert pair(admin, value["code"]).status_code == 201


def test_sqlite_contention_no_retry(admin, initialized):
    value = code(admin)
    with initialized.transaction(write=True) as db:
        db.execute(text("SELECT 1"))
        assert pair(admin, value["code"]).status_code == 503
    assert pair(admin, value["code"]).status_code == 201


def test_validation_origin_and_no_cache(admin):
    value = code(admin)
    response = admin.post("/api/v1/terminal/pair", headers={"Origin": "https://evil.example"},
                          json={"code": value["code"], "name": "Tableta"})
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"
    response = pair(admin, "sensitive"*100)
    assert response.status_code == 422 and "sensitive" not in response.text
    result, headers = linked(admin)
    response = admin.get("/api/v1/terminal/me", headers=headers)
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert admin.get("/api/v1/terminal/me", headers={**headers, "Origin": "null"}).status_code == 403


def test_upgrade_preserves_administrator_and_sessions(tmp_path):
    db = Database(tmp_path / "old")
    db.migrate("0001")
    # Datos administrativos de la revisión anterior, sin usar el modelo de auditoría nuevo.
    with db.transaction(write=True) as session:
        session.execute(text("INSERT INTO administrators VALUES (1, 'principal', 'hash', 1, 1, 1)"))
        session.execute(text("INSERT INTO admin_sessions VALUES (1, :hash, 1, 1, 3601, 0)"), {"hash": "a"*64})
        session.execute(text("INSERT INTO security_audit VALUES (1, 1, 'login_success', 1, 'success', NULL)"))
    db.migrate()
    db.check()
    with db.transaction() as session:
        assert session.scalar(text("SELECT username FROM administrators")) == "principal"
        assert session.scalar(text("SELECT token_hash FROM admin_sessions")) == "a"*64
        assert session.scalar(text("SELECT event FROM security_audit")) == "login_success"
        assert session.scalar(text("PRAGMA integrity_check")) == "ok"
    db.close()
