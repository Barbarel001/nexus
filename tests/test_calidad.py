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
