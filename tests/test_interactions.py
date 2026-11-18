"""Contrato 2.1, aislamiento, memoria acotada y fronteras de seguridad."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from nexo import interactions as module, security
from nexo.config import Settings
from nexo.database import audit, terminals
from nexo.main import create_app
from test_security import database, initialized, client, ORIGIN
from test_terminals import admin, linked

PATH = module.PATH


def send(client, headers=None, value="hola"):
    return client.post(PATH, headers={"Content-Type": "application/json", **(headers or {})},
                       content=json.dumps({"text": value}).encode("ascii"))


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"request_id", "terminal_id", "status", "message", "response_type", "error"}
    assert len(body["request_id"]) == 32
    assert body["status"] == "failed" and body["response_type"] == "error"
    assert body["error"] == {"code": code}
    assert response.headers["cache-control"] == "no-store"


def test_authorized_and_deterministic_context(admin):
    terminal, headers = linked(admin, ["terminal.chat"])
    schema = admin.get("/openapi.json").json()["paths"][PATH]["post"]["responses"]
    assert schema["200"]["content"]["application/json"]["schema"] == schema["422"]["content"]["application/json"]["schema"]
    first = send(admin, headers)
    assert first.status_code == 200
    body = first.json()
    assert body["terminal_id"] == terminal["terminal"]["id"]
    assert body["status"] == "completed" and body["error"] is None
    assert body["response_type"] == "text" and "Soy NEXO" in body["message"]
    again = send(admin, headers).json()
    assert "de nuevo" in again["message"] and again["request_id"] != body["request_id"]
    assert "disponible" in send(admin, headers, "estado").json()["message"]
    assert "ayuda" in send(admin, headers, "ayuda").json()["message"]
    assert send(admin, headers, "enciende la luz").json()["response_type"] == "unavailable"


@pytest.mark.parametrize("mode", ["permission", "revoked", "expired", "cookie", "unknown", "origin"])
def test_auth_boundaries(admin, initialized, mode):
    terminal, headers = linked(admin, [] if mode == "permission" else ["terminal.chat"])
    identifier = terminal["terminal"]["id"]
    status, code = 401, "invalid_credential"
    if mode == "revoked":
        send(admin, headers)
        assert admin.delete("/api/v1/admin/terminals/"+identifier).status_code == 204
        assert identifier not in admin.app.state.interactions._contexts
    elif mode == "expired":
        with initialized.transaction(write=True) as db:
            db.execute(update(terminals).where(terminals.c.id == identifier).values(
                created_at=security.now()-100, expires_at=security.now()))
    elif mode == "cookie":
        headers = {}
    elif mode == "unknown":
        headers = {"Authorization": "Bearer nt_"+"x"*43}
    elif mode == "permission":
        status, code = 403, "forbidden"
    elif mode == "origin":
        headers = {**headers, "Origin": "https://evil.example"}
        status, code = 403, "forbidden"
    assert_error(send(admin, headers), status, code)


def test_isolation_and_restart(admin, initialized):
    one, h1 = linked(admin, ["terminal.chat"])
    two, h2 = linked(admin, ["terminal.chat"])
    send(admin, h1, "privado-uno")
    assert "Soy NEXO" in send(admin, h2).json()["message"]
    store = admin.app.state.interactions
    assert store._contexts[one["terminal"]["id"]].messages[0].text == "privado-uno"
    assert "privado-uno" not in str([m.text for m in store._contexts[two["terminal"]["id"]].messages])
    with TestClient(create_app(Settings(initialized.data_dir)), base_url=ORIGIN) as fresh:
        assert "Soy NEXO" in send(fresh, h1).json()["message"]
        assert send(fresh, h1, "hola").status_code == 200
    assert not fresh.app.state.interactions._contexts
    assert admin.get(PATH).status_code == 405
    assert_error(admin.post(PATH, headers=h1, json={"text": "hola", "terminal_id": two["terminal"]["id"]}), 422, "invalid_input")


def test_expiry_and_deferred_revocation(admin, initialized):
    result, headers = linked(admin, ["terminal.chat"])
    store = admin.app.state.interactions
    clock = [1000.0]
    store.clock = lambda: clock[0]
    send(admin, headers)
    clock[0] += store.ttl-1
    assert "de nuevo" in send(admin, headers).json()["message"]
    clock[0] += store.ttl
    assert "Soy NEXO" in send(admin, headers).json()["message"]
    identifier = result["terminal"]["id"]
    with initialized.transaction(write=True) as db:
        db.execute(update(terminals).where(terminals.c.id == identifier).values(revoked_at=security.now()))
    assert_error(send(admin, headers), 401, "invalid_credential")
    assert identifier not in store._contexts


@pytest.mark.parametrize("value", ["", "  ", "x"*2001, "\x00", "\ud800", 42, None])
def test_input_limits(admin, value):
    _, headers = linked(admin, ["terminal.chat"])
    assert_error(send(admin, headers, value), 422, "invalid_input")


def test_body_limit_including_chunked(admin):
    _, headers = linked(admin, ["terminal.chat"])
    response = admin.post(PATH, headers={**headers, "Content-Type": "application/json"},
                          content=iter([b'{"text":"', b'x'*module.MAX_BODY, b'"}']))
    assert_error(response, 413, "input_too_large")
    assert_error(admin.post(PATH, headers=headers, content=b'{bad sensitive'), 422, "invalid_input")


def test_context_limits_rate_and_capacity(admin, monkeypatch):
    _, headers = linked(admin, ["terminal.chat"])
    store = admin.app.state.interactions
    clock = [1000.0]
    store.clock = lambda: clock[0]
    for i in range(20):
        assert send(admin, headers, "😀"*2000).status_code == 200
    entry = next(iter(store._contexts.values()))
    assert len(entry.messages) <= module.MAX_MESSAGES
    assert sum(len(m.text.encode("utf-8")) for m in entry.messages) <= module.MAX_CONTEXT_BYTES
    assert_error(send(admin, headers), 429, "rate_limited")
    clock[0] += 60
    assert send(admin, headers).status_code == 200
    monkeypatch.setattr(module, "MAX_CONTEXTS", 1)
    _, second = linked(admin, ["terminal.chat"])
    assert_error(send(admin, second), 503, "capacity_unavailable")


def test_concurrent_http_independent_and_same_terminal(admin, monkeypatch):
    one, h1 = linked(admin, ["terminal.chat"])
    two, h2 = linked(admin, ["terminal.chat"])
    entered, release = threading.Event(), threading.Event()
    original = module.process
    def blocked(value, context):
        if value == "privado-uno":
            entered.set()
            assert release.wait(10)
        return original(value, context)
    monkeypatch.setattr(module, "process", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(send, admin, h1, "privado-uno")
        try:
            assert entered.wait(10)
            assert_error(send(admin, h1, "conflicto"), 409, "terminal_busy")
            assert send(admin, h2, "privado-dos").status_code == 200
        finally:
            release.set()
        assert pending.result().status_code == 200
    contexts = admin.app.state.interactions._contexts
    assert contexts[one["terminal"]["id"]].messages[0].text == "privado-uno"
    assert contexts[two["terminal"]["id"]].messages[0].text == "privado-dos"
    assert len(contexts[one["terminal"]["id"]].messages) == 2


def test_processor_error_releases_and_does_not_log(admin, monkeypatch, caplog):
    caplog.set_level("DEBUG")
    _, headers = linked(admin, ["terminal.chat"])
    original = module.process
    def fail(value, context):
        raise RuntimeError(value)
    monkeypatch.setattr(module, "process", fail)
    assert_error(send(admin, headers, "secreto-procesador"), 500, "processing_error")
    assert "secreto-procesador" not in caplog.text
    entry = next(iter(admin.app.state.interactions._contexts.values()))
    assert not entry.busy and not entry.messages
    monkeypatch.setattr(module, "process", original)
    assert send(admin, headers).status_code == 200


def test_no_conversations_sqlite_or_logs(admin, initialized, caplog):
    caplog.set_level("DEBUG")
    _, headers = linked(admin, ["terminal.chat"])
    secret = "contenido-privado-unico-2.1"
    with initialized.transaction() as db:
        before = list(db.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")))
    assert send(admin, headers, secret).status_code == 200
    assert_error(send(admin, headers, secret*2000), 413, "input_too_large")
    with initialized.transaction() as db:
        assert before == list(db.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")))
        serialized = json.dumps([dict(row) for row in db.execute(select(audit)).mappings()])
    import sqlite3
    with sqlite3.connect(initialized.data_dir / "nexo.sqlite3") as db:
        dump = "\n".join(db.iterdump())
    assert secret not in dump+serialized+caplog.text
    assert secret.encode() not in (initialized.data_dir / "nexo.sqlite3").read_bytes()


def test_persistence_error_structured(admin, initialized):
    _, headers = linked(admin, ["terminal.chat"])
    with initialized.transaction(write=True) as db:
        db.execute(text("SELECT 1"))
        assert_error(send(admin, headers), 503, "persistence_unavailable")


def test_ttl_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXO_CONTEXT_TTL", "120")
    assert Settings.from_env().context_ttl == 120
    for value in (0, 59, 86401):
        with pytest.raises(ValueError):
            Settings(tmp_path, context_ttl=value)


def test_message_count_bound(admin):
    _, headers = linked(admin, ["terminal.chat"])
    for _ in range(15):
        assert send(admin, headers).status_code == 200
    entry = next(iter(admin.app.state.interactions._contexts.values()))
    assert len(entry.messages) == module.MAX_MESSAGES
    assert [m.role for m in entry.messages] == ["user", "assistant"]*10


def test_revocation_during_processing_cannot_restore_context(admin, monkeypatch):
    result, headers = linked(admin, ["terminal.chat"])
    entered, release = threading.Event(), threading.Event()
    original = module.process
    def blocked(value, context):
        entered.set()
        assert release.wait(10)
        return original(value, context)
    monkeypatch.setattr(module, "process", blocked)
    identifier = result["terminal"]["id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(send, admin, headers)
        try:
            assert entered.wait(10)
            assert admin.delete("/api/v1/admin/terminals/"+identifier).status_code == 204
        finally:
            release.set()
        assert pending.result().status_code == 200
    assert identifier not in admin.app.state.interactions._contexts
    assert_error(send(admin, headers), 401, "invalid_credential")
