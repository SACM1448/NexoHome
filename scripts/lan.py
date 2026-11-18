"""Preflight y arranque LAN; no modifica DNS, firewall ni confianza del equipo."""
import argparse
import ipaddress
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ["docker", "compose", "-f", str(ROOT / "compose.lan.yaml")]


def validate(config):
    backend = config["services"]["nexo"]
    proxy = config["services"]["caddy"]
    if backend.get("ports") or backend["environment"]["NEXO_ENV"] != "production":
        raise ValueError("Backend LAN debe ser interno y de producción")
    address = ipaddress.ip_address(proxy["ports"][0]["host_ip"])
    private_ranges = [ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if not any(address in network for network in private_ranges):
        raise ValueError("NEXO_LAN_IP debe ser una IPv4 privada concreta de la LAN (RFC1918)")
    origin = urlsplit(backend["environment"]["NEXO_ORIGIN"])
    host = origin.hostname or ""
    if (origin.scheme != "https" or origin.netloc != proxy["environment"]["NEXO_LAN_HOST"]
            or origin.port is not None or origin.path or origin.query or origin.fragment
            or origin.username or origin.password):
        raise ValueError("Origen HTTPS y nombre de Caddy deben coincidir sin puerto ni ruta")
    if not (host.endswith(".home.arpa") or host == str(address)):
        raise ValueError("Usa un nombre bajo home.arpa o la misma IP privada del servidor")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "up"])
    args = parser.parse_args()
    result = subprocess.run([*COMMAND, "config", "--format", "json"], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        parser.exit(1, "Configuración LAN incompleta; revisa NEXO_LAN_IP y .env.example.\n")
    try:
        validate(json.loads(result.stdout))
    except (ValueError, KeyError) as error:
        parser.exit(1, str(error) + "\n")
    print("Configuración LAN válida; comprueba que la IP pertenece a este equipo y el nombre resuelve en cada cliente.")
    if args.action == "up":
        return subprocess.run([*COMMAND, "up", "--build", "-d", "--wait"], cwd=ROOT).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
