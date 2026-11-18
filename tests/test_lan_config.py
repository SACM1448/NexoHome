"""Validación de publicación privada sin requerir Docker en la suite unitaria."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lan", ROOT / "scripts" / "lan.py")
lan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lan)


def config(ip="192.168.1.50", host="nexo.home.arpa"):
    return {"services": {
        "nexo": {"environment": {"NEXO_ENV": "production", "NEXO_ORIGIN": "https://" + host}},
        "caddy": {"ports": [{"host_ip": ip}], "environment": {"NEXO_LAN_HOST": host}}}}


@pytest.mark.parametrize("ip", ["0.0.0.0", "8.8.8.8", "127.0.0.1", "::", "100.64.0.1"])
def test_non_lan_bind_rejected(ip):
    with pytest.raises(ValueError):
        lan.validate(config(ip))


@pytest.mark.parametrize("host", ["example.com", "nexo.home.arpa:443", "nexo.home.arpa/path"])
def test_external_or_invalid_name_rejected(host):
    with pytest.raises(ValueError):
        lan.validate(config(host=host))


def test_domain_and_ip_modes():
    lan.validate(config())
    lan.validate(config(host="192.168.1.50"))
    unsafe = config()
    unsafe["services"]["nexo"]["ports"] = ["8000:8000"]
    with pytest.raises(ValueError):
        lan.validate(unsafe)
