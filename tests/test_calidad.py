# -*- coding: utf-8 -*-
"""Tests de calidad/robustez: endpoint de métricas y su gating."""

import nexus_db
import nexus_web


def test_metrics_local(monkeypatch):
    # Sin login (uso local) las métricas son accesibles.
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    c = nexus_web.app.test_client()
    d = c.get("/api/metrics").get_json()
    assert "uptime_segundos" in d and d["peticiones"] >= 1 and "errores" in d


def test_metrics_cuenta_peticiones(monkeypatch):
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    c = nexus_web.app.test_client()
    antes = c.get("/api/metrics").get_json()["peticiones"]
    c.get("/api/health")
    despues = c.get("/api/metrics").get_json()["peticiones"]
    assert despues > antes


def test_metrics_requiere_admin_en_multiuser(monkeypatch, tmp_path):
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", True)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(nexus_web, "NEXUS_ADMIN_EMAIL", {"admin@x.com"})
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "m.db"))
    nexus_db.init()
    c = nexus_web.app.test_client()
    c.post("/register", data={"email": "normal@x.com", "password": "secreta1"})
    assert c.get("/api/metrics").status_code == 403   # logueado pero no admin


# --------------------------- Mensajes de error del chat ---------------------------

def test_error_amable_api_key():
    m = nexus_web._error_amable(Exception("Error code: 401 - invalid x-api-key"))
    assert "ANTHROPIC_API_KEY" in m and "console.anthropic.com" in m


def test_error_amable_ollama_caido():
    m = nexus_web._error_amable(Exception("<urlopen error [Errno 111] Connection refused>"), ollama=True)
    assert "Ollama" in m and "ollama.com" in m


def test_error_amable_saturado():
    assert "satur" in nexus_web._error_amable(Exception("429 rate limit")).lower()


def test_error_amable_generico():
    assert nexus_web._error_amable(Exception("algo raro")).startswith("No pude completar")
