"""Caddy real: TLS verificado con CA temporal, origen, sesión y aislamiento.

No instala confianza global ni publica LAN. Solo loopback:18443; volumen aleatorio.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import uuid

import httpx

from docker_smoke import PTY_INIT

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "nexo-https-validation-" + uuid.uuid4().hex[:10]
ORIGIN = "https://nexo.home.arpa:18443"


def main():
    env = {**os.environ, "NEXO_LAN_IP": "127.0.0.1", "NEXO_LAN_HOST": "nexo.home.arpa"}
    source = subprocess.run(["docker", "compose", "-f", "compose.lan.yaml", "config", "--format", "json"],
                            cwd=ROOT, env=env, text=True, capture_output=True, check=True)
    config = json.loads(source.stdout)
    assert "ports" not in config["services"]["nexo"]
    assert config["networks"]["backend"]["internal"] is True
    config["services"]["nexo"]["environment"]["NEXO_ORIGIN"] = ORIGIN
    config["services"]["caddy"]["ports"][0]["published"] = "18443"
    # Compose config normaliza nombres; aislar TODOS los volúmenes/redes.
    for section in ("networks", "volumes"):
        for name, item in config[section].items():
            item["name"] = PROJECT + "_" + name
    scratch = ROOT / ".validation"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        directory = Path(directory)
        file = directory / "compose.json"
        file.write_text(json.dumps(config), encoding="utf-8")

        def compose(*args, input=None):
            result = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(file), *args],
                                    cwd=ROOT, env=env, input=input, text=True, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError("Falló Compose HTTPS: " + " ".join(args[:2]))
            return result.stdout

        original_resolver = socket.getaddrinfo

        def resolve(host, *args, **kwargs):
            return original_resolver("127.0.0.1" if host == "nexo.home.arpa" else host, *args, **kwargs)

        password = secrets.token_urlsafe(32) + "a1"
        try:
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90")
            compose("exec", "-T", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
            compose("exec", "-T", "nexo", "python", "-c", PTY_INIT,
                    input=json.dumps({"username": "validacion", "password": password}))
            ca = directory / "root.crt"
            compose("cp", "caddy:/data/caddy/pki/authorities/local/root.crt", str(ca))
            context = ssl.create_default_context(cafile=str(ca))
            socket.getaddrinfo = resolve
            # Sin confiar en esta CA, TLS debe fallar; jamás verify=False.
            try:
                with httpx.Client(trust_env=False, timeout=5) as untrusted:
                    untrusted.get(ORIGIN + "/api/v1/health")
            except httpx.ConnectError as error:
                assert "CERTIFICATE_VERIFY_FAILED" in str(error), "El rechazo debe ser de certificado, no de conectividad"
            else:
                raise AssertionError("La CA temporal no debe ser de confianza global")
            with httpx.Client(base_url=ORIGIN, verify=context, trust_env=False, timeout=5) as client:
                response = client.get("/api/v1/health")
                assert response.status_code == 200
                assert response.headers["strict-transport-security"] == "max-age=31536000"
                assert response.headers["x-frame-options"] == "DENY"
                assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
                assert client.get("/api/v1/admin/metrics").status_code == 401
                credentials = {"username": "validacion", "password": password}
                assert client.post("/api/v1/auth/login", json=credentials, headers={"Origin": "http://localhost:8000"}).status_code == 403
                response = client.post("/api/v1/auth/login", json=credentials, headers={"Origin": ORIGIN})
                assert response.status_code == 200
                assert "Secure" in response.headers["set-cookie"] and "__Host-nexo_session=" in response.headers["set-cookie"]
                csrf = response.json()["csrf_token"]
                assert client.get("/api/v1/admin/metrics").status_code == 200
                assert client.get("/admin/dashboard").status_code == 200
                assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
                compose("up", "-d", "--no-build", "--force-recreate", "--wait", "--wait-timeout", "90")
                assert client.get("/api/v1/admin/persistence").json()["status"] == "ok"
                assert client.get("/api/v1/admin/audit").json()
                assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 204
                logs = compose("logs", "--no-color")
                assert password not in logs and csrf not in logs
            print("HTTPS real aprobado: CA y hostname verificados, rechazo sin confianza, Secure, origen/CSRF, encabezados, persistencia y healthchecks. Solo loopback.")
        finally:
            socket.getaddrinfo = original_resolver
            compose("down", "--volumes")
            print("Proyecto HTTPS y CA temporal retirados; confianza global y datos operativos intactos.")


if __name__ == "__main__":
    main()
