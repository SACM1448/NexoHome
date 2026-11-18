"""Validación HTTP/CLI real con Compose aislado, sin credenciales de producción.

Ejecutar desde la raíz: .venv/Scripts/python tests/docker_smoke.py
No imprime contraseñas, cookies ni tokens; elimina solo su volumen temporal.
"""

import json
import os
import secrets
import subprocess
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "nexo-validation-" + uuid.uuid4().hex[:10]
ORIGIN = "http://localhost:18000"
ENV = {**os.environ, "NEXO_PORT": "18000", "NEXO_ORIGIN": ORIGIN, "NEXO_ENV": "development"}


def compose(*args, input=None, check=True):
    result = subprocess.run(["docker", "compose", "-p", PROJECT, *args], cwd=ROOT,
                            env=ENV, input=input, text=True, capture_output=True, timeout=90)
    if check and result.returncode:
        # No devolver stdout/stderr: un fallo de la prueba podría incluir material sensible.
        raise RuntimeError("Falló Compose: " + " ".join(args[:2]))
    return result


# Se usa un PTY real en Linux para comprobar getpass, sin simular la CLI.
PTY_INIT = r'''
import errno, json, os, pty, select, signal, sys, time
credentials = json.load(sys.stdin)
pid, fd = pty.fork()
if pid == 0:
    os.execvp(sys.executable, [sys.executable, '-m', 'nexo.cli', 'init-admin'])
transcript = b''
buffer = b''
prompts = [b'Usuario administrador: ', b'letras y n', b'Confirmar contrase']
answers = [credentials['username'], credentials['password'], credentials['password']]
step = 0
deadline = time.monotonic() + 20
try:
    while time.monotonic() < deadline:
        if select.select([fd], [], [], 0.2)[0]:
            try:
                data = os.read(fd, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not data:
                break
            transcript += data
            buffer += data
            if step < 3 and prompts[step] in buffer:
                os.write(fd, (answers[step] + '\n').encode())
                buffer = b''
                step += 1
        result, status = os.waitpid(pid, os.WNOHANG)
        if result:
            assert os.waitstatus_to_exitcode(status) == 0
            break
    else:
        os.kill(pid, signal.SIGKILL)
        raise RuntimeError('CLI timeout')
    assert step == 3 and b'Administrador inicial creado' in transcript
    assert credentials['password'].encode() not in transcript
    print('CLI real: administrador temporal creado sin eco')
finally:
    os.close(fd)
'''


def main():
    password = secrets.token_urlsafe(32) + "a1"
    try:
        compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "60")
        compose("exec", "-T", "nexo", "python", "-m", "alembic", "upgrade", "head")
        result = compose("exec", "-T", "nexo", "python", "-c", PTY_INIT,
                         input=json.dumps({"username": "validacion", "password": password}))
        assert result.stdout.strip() == "CLI real: administrador temporal creado sin eco"
        duplicate = compose("exec", "-T", "nexo", "python", "-m", "nexo.cli", "init-admin", check=False)
        assert duplicate.returncode == 1
        with httpx.Client(base_url=ORIGIN, timeout=5, trust_env=False) as client:
            assert client.get("/api/v1/health").json() == {"status": "ok", "service": "nexo-home"}
            assert client.get("/api/v1/admin/status").status_code == 401
            credentials = {"username": "validacion", "password": password}
            assert client.post("/api/v1/auth/login", json=credentials).status_code == 403
            response = client.post("/api/v1/auth/login", json=credentials, headers={"Origin": ORIGIN})
            assert response.status_code == 200
            csrf = response.json()["csrf_token"]
            assert client.get("/api/v1/admin/status").status_code == 200
            assert client.post("/api/v1/terminal/interact", json={"text": "hola"}).status_code == 401
            for endpoint in ("summary", "metrics", "persistence", "audit", "updates"):
                result = client.get("/api/v1/admin/" + endpoint)
                assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
            assert client.get("/api/v1/admin/persistence").json()["status"] == "ok"
            assert client.get("/api/v1/admin/metrics").json()["execution"] == "container"
            assert client.get("/api/v1/admin/updates").json()["checks_available"] is False
            assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
            admin_headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
            response = client.post("/api/v1/admin/pairing-codes", headers=admin_headers,
                                   json={"permissions": ["terminal.status", "terminal.chat"]})
            assert response.status_code == 201
            pairing = response.json()
            with httpx.Client(base_url=ORIGIN, timeout=5, trust_env=False) as terminal:
                assert terminal.get("/api/v1/terminal/me").status_code == 401
                response = terminal.post("/api/v1/terminal/pair", json={"code": pairing["code"], "name": "Smoke"})
                assert response.status_code == 201
                linked = response.json()
                terminal.headers["Authorization"] = "Bearer " + linked["credential"]
                assert terminal.get("/api/v1/terminal/status").status_code == 200
                response = terminal.post("/api/v1/terminal/interact", json={"text": "hola"})
                assert response.status_code == 200 and "Soy NEXO" in response.json()["message"]
                assert "de nuevo" in terminal.post("/api/v1/terminal/interact", json={"text": "hola"}).json()["message"]
                assert terminal.get("/api/v1/admin/terminals").status_code == 401
                for endpoint in ("summary", "metrics", "persistence", "audit", "updates"):
                    assert terminal.get("/api/v1/admin/" + endpoint).status_code == 401
                assert terminal.post("/api/v1/terminal/pair", json={"code": pairing["code"], "name": "Replay"}).status_code == 401
                path = "/api/v1/admin/terminals/"+linked["terminal"]["id"]
                assert client.patch(path+"/name", headers=admin_headers, json={"name": "Smoke renombrado"}).status_code == 200
                assert client.put(path+"/permissions", headers=admin_headers, json={"permissions": []}).status_code == 200
                assert terminal.get("/api/v1/terminal/status").status_code == 403
                denied = terminal.post("/api/v1/terminal/interact", json={"text": "hola"})
                assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden"
                assert client.put(path+"/permissions", headers=admin_headers, json={"permissions": ["terminal.status", "terminal.chat"]}).status_code == 200
                assert terminal.post("/api/v1/terminal/interact", json={"text": "hola"}).status_code == 200
                private_text = "privado-smoke-" + uuid.uuid4().hex
                assert terminal.post("/api/v1/terminal/interact", json={"text": private_text}).status_code == 200
                compose("up", "-d", "--no-build", "--force-recreate", "--wait", "--wait-timeout", "60")
                assert "Soy NEXO" in terminal.post("/api/v1/terminal/interact", json={"text": "hola"}).json()["message"]
                assert terminal.get("/api/v1/terminal/me").json()["name"] == "Smoke renombrado"
                assert terminal.get("/api/v1/terminal/status").status_code == 200
                assert client.delete(path, headers=admin_headers).status_code == 204
                assert terminal.get("/api/v1/terminal/me").status_code == 401
                assert terminal.post("/api/v1/terminal/interact", json={"text": "hola"}).status_code == 401
                assert client.get("/api/v1/admin/terminals").json()[0]["state"] == "revoked"
                check = compose("exec", "-T", "nexo", "python", "-c",
                    "import sqlite3,sys; c=sqlite3.connect('/data/nexo.sqlite3'); "
                    "assert sys.stdin.read() not in '\\n'.join(c.iterdump()); print('Sin conversaciones en SQLite')",
                    input=private_text)
                assert "Sin conversaciones" in check.stdout
                logs = compose("logs", "--no-color", "nexo").stdout
                assert all(secret not in logs for secret in (password, csrf, linked["credential"], pairing["code"], private_text))
            compose("up", "-d", "--no-build", "--force-recreate", "--wait", "--wait-timeout", "60")
            assert client.get("/api/v1/auth/me").status_code == 200
            assert client.get("/api/v1/admin/summary").json()["persistence"]["status"] == "ok"
            assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 204
            assert client.get("/api/v1/admin/status").status_code == 401
        verify = compose("exec", "-T", "nexo", "python", "-c",
                         "import os,sqlite3; c=sqlite3.connect('/data/nexo.sqlite3'); "
                         "assert os.getuid()==10001; "
                         "assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
                         "assert c.execute('SELECT count(*) FROM administrators').fetchone()[0]==1; "
                         "assert c.execute('SELECT count(*) FROM admin_sessions WHERE revoked=0').fetchone()[0]==0; "
                         "assert os.stat('/data/nexo.sqlite3').st_mode & 0o077 == 0; "
                         "assert os.stat('/data').st_mode & 0o077 == 0; "
                         "print('Integridad, permisos y revocacion correctos')")
        assert "correctos" in verify.stdout
        compose("exec", "-T", "nexo", "python", "-m", "pip", "check")
        print("Docker AMD64/Python 3.12: migraciones, healthcheck, CLI con PTY sin eco, login HTTP, "
              "autorización, CSRF, logout, vinculación de terminal, permisos, revocación, "
              "ausencia de secretos en logs y persistencia tras recreación: aprobados.")
    finally:
        compose("down", "--volumes", check=True)
        print("Contenedores y volumen temporales retirados; datos operativos intactos.")


if __name__ == "__main__":
    main()
