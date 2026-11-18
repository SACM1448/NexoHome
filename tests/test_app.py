import re

import pytest
from httpx import ASGITransport, AsyncClient

from nexo.main import create_app


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://testserver") as client:
        yield client


async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "service": "nexo-home"}


async def test_home_and_referenced_assets(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'lang="es"' in response.text
    assert "NEXO Home" in response.text
    assets = re.findall(r'(?:href|src)="(/static/[^\"]+)"', response.text)
    assert set(assets) == {"/static/css/styles.css", "/static/js/app.js"}
    for asset in assets:
        loaded = await client.get(asset)
        assert loaded.status_code == 200
        assert loaded.content
        assert ("text/css" if asset.endswith(".css") else "javascript") in loaded.headers["content-type"]


@pytest.mark.parametrize("path", ["/api/v1/missing", "/static/missing.css", "/static/../pyproject.toml", "/admin"])
async def test_missing_or_private_paths(client, path):
    assert (await client.get(path)).status_code == 404


async def test_health_disallows_mutation(client):
    assert (await client.post("/api/v1/health")).status_code == 405


async def test_terminal_assets_and_security_policy(client):
    response = await client.get('/terminal')
    assert response.status_code == 200
    assert 'lang="es"' in response.text
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert "style-src 'self'" in response.headers['content-security-policy']
    assert "unsafe-inline" not in response.headers['content-security-policy']
    assets = re.findall(r'(?:href|src)="(/static/[^\"]+)"', response.text)
    assert '/static/css/terminal.css' in assets
    for asset in assets:
        loaded = await client.get(asset)
        assert loaded.status_code == 200 and loaded.content
        assert loaded.headers['x-content-type-options'] == 'nosniff'
