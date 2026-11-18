"""Fronteras de administración, datos locales reales y degradación segura."""
from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient

from nexo import monitoring
from nexo.config import Settings
from nexo.main import create_app
from test_security import database, initialized, client, login, ORIGIN, PASSWORD
from test_terminals import admin, linked

PATHS = ["summary", "metrics", "persistence", "audit", "updates"]


@pytest.mark.parametrize("path", PATHS)
def test_administrative_boundary(client, path):
    assert client.get("/api/v1/admin/" + path).status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_terminal_rejected_even_with_admin_cookie(admin, path):
    _, headers = linked(admin)
    assert admin.get("/api/v1/admin/" + path, headers=headers).status_code == 401


def test_summary_and_sqlite(admin):
    linked(admin)
    result = admin.get("/api/v1/admin/summary").json()
    assert result["service"] == "ok"
    assert result["terminals"]["total"] == result["terminals"]["linked"] == 1
    persistence = admin.get("/api/v1/admin/persistence").json()
    assert persistence["engine"] == "SQLite" and persistence["migration"] == "0002"
    assert persistence["status"] == "ok"


def test_persistence_failure(tmp_path):
    from nexo.database import Database
    missing = Database(tmp_path / "missing")
    try:
        assert monitoring.persistence(missing)["status"] == "unavailable"
    finally:
        missing.close()


def test_real_metrics_and_cache(admin):
    result = admin.get("/api/v1/admin/metrics").json()
    assert result["os"]["system"]
    assert result["refresh_seconds"] == 30
    values = result["metrics"]
    for key in ["ram_total_bytes", "process_rss_bytes", "storage_free_bytes"]:
        assert values[key]["value"] > 0
    assert values["service_uptime_seconds"]["value"] >= 0
    assert values["cpu_percent"]["value"] is None
    assert admin.get("/api/v1/admin/metrics").json() == result


def test_cpu_samples_and_missing_sensors(tmp_path, monkeypatch):
    # cpu_times returns a tuple-like object.
    from collections import namedtuple
    cpu = namedtuple("cpu", "user idle")
    samples = iter([cpu(20, 80), cpu(30, 90)])
    monkeypatch.setattr(monitoring.psutil, "cpu_times", lambda: next(samples))
    monitor = monitoring.Monitor(tmp_path, 5)
    assert monitor.cpu() is None
    assert monitor.cpu() == 50
    monkeypatch.setattr(monitoring.psutil, "sensors_temperatures", lambda: {}, raising=False)
    assert monitoring.metric(monitor.temperature, "°C", "test")["value"] is None


def test_metric_errors_are_safe():
    def failed():
        raise OSError("sensitive-file-name")
    result = monitoring.metric(failed, "%", "test")
    assert result["value"] is None and result["limitation"]
    assert "sensitive" not in str(result)


def test_audit_bounded_and_secret_free(admin, initialized):
    pairing, _ = linked(admin)
    for limit in [0, 101, "invalid"]:
        assert admin.get(f"/api/v1/admin/audit?limit={limit}").status_code == 422
    events = admin.get("/api/v1/admin/audit?limit=1").json()
    assert len(events) == 1 and events[0]["event"]
    content = " ".join(admin.get("/api/v1/admin/" + path).text for path in PATHS)
    for secret in [PASSWORD, pairing["credential"], admin.cookies["nexo_session"], "password_hash", "token_hash", "credential_hash"]:
        assert secret not in content


def test_inventory_local_and_informative(admin):
    result = admin.get("/api/v1/admin/updates").json()
    assert result["dependencies"]["psutil"] == version("psutil")
    assert result["dependencies"]["fastapi"] == version("fastapi")
    assert result["checks_available"] is False
    assert result["last_check_at"] is result["last_check_result"] is None
    assert result["notice"] == monitoring.UPDATE_NOTICE


def test_security_headers_csrf_and_origin(admin):
    for path in PATHS:
        response = admin.get("/api/v1/admin/" + path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert admin.post("/api/v1/admin/" + path).status_code == 405
    assert admin.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert admin.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "0" * 64}).status_code == 403


def test_https_cookie_and_persistence(initialized):
    origin = "https://nexo.home.arpa"
    settings = Settings(initialized.data_dir, origin, "production")
    with TestClient(create_app(settings), base_url=origin) as client:
        result = client.post("/api/v1/auth/login", json={"username": "principal", "password": PASSWORD}, headers={"Origin": origin})
        assert result.status_code == 200
        assert "Secure" in result.headers["set-cookie"]
        assert "__Host-nexo_session=" in result.headers["set-cookie"]
        cookies = dict(client.cookies)
    with TestClient(create_app(settings), base_url=origin) as recreated:
        recreated.cookies.update(cookies)
        assert recreated.get("/api/v1/admin/summary").status_code == 200
        assert recreated.get("/api/v1/admin/audit").json()


@pytest.mark.parametrize("interval", [0, 4, 301])
def test_interval_validation(tmp_path, interval):
    with pytest.raises(ValueError):
        Settings(tmp_path, metrics_interval=interval)


@pytest.mark.parametrize("page,content", [
    ("dashboard", "system-summary"), ("terminals", "pairing-code"),
    ("resources", "resource-charts"), ("audit", "audit-events"),
    ("updates", "version-inventory"),
])
def test_independent_admin_pages(client, page, content):
    response = client.get("/admin/" + page)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert f'data-page="{page}"' in response.text
    assert response.text.count('id="login-form"') == 1
    assert f'id="{content}"' in response.text
    for other in {"system-summary", "pairing-code", "resource-charts", "audit-events", "version-inventory"} - {content}:
        assert f'id="{other}"' not in response.text
    for route in ("dashboard", "terminals", "resources", "audit", "updates"):
        assert f'href="/admin/{route}"' in response.text
    assert "{{" not in response.text


def test_admin_page_allowlist_and_assets(client):
    assert client.get("/admin/unknown").status_code == 404
    assert client.get("/admin/%2e%2e%2fconfig").status_code == 404
    for asset in ("/static/css/admin.css", "/static/js/terminals-admin.js"):
        assert client.get(asset).status_code == 200
