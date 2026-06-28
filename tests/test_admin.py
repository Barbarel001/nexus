# -*- coding: utf-8 -*-
"""Tests del panel de administración (usuarios, planes, métricas) y su gating."""

import pytest

import nexus_db
import nexus_web


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "admin.db"))
    nexus_db.init()


# --------------------------- BD: helpers de admin ---------------------------

def test_listar_y_stats():
    nexus_db.crear_usuario("a@b.com", "secreta1")
    u2 = nexus_db.crear_usuario("c@d.com", "secreta1")
    nexus_db.cambiar_plan(u2["id"], "pro")
    us = nexus_db.listar_usuarios()
    assert len(us) == 2 and us[0]["id"] > us[1]["id"]   # más reciente primero
    s = nexus_db.stats()
    assert s["usuarios"] == 2 and s["por_plan"].get("pro") == 1


# --------------------------- Gating del panel ---------------------------

def _cliente_admin(monkeypatch, email="admin@nexus.com"):
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", True)
    monkeypatch.setattr(nexus_web, "NEXUS_ADMIN_EMAIL", {email})
    c = nexus_web.app.test_client()
    return c


def test_admin_requiere_ser_admin(monkeypatch):
    c = _cliente_admin(monkeypatch)
    nexus_db.crear_usuario("normal@user.com", "secreta1")
    # login como usuario NO admin
    c.post("/login", data={"email": "normal@user.com", "password": "secreta1"})
    assert c.get("/api/admin/usuarios").status_code == 403
    assert c.get("/admin").status_code == 403


def test_admin_acceso_y_cambio_plan(monkeypatch):
    c = _cliente_admin(monkeypatch, "admin@nexus.com")
    nexus_db.crear_usuario("admin@nexus.com", "secreta1")     # el admin
    objetivo = nexus_db.crear_usuario("cliente@x.com", "secreta1")
    c.post("/login", data={"email": "admin@nexus.com", "password": "secreta1"})
    # ve usuarios y stats
    r = c.get("/api/admin/usuarios")
    assert r.status_code == 200 and len(r.get_json()["usuarios"]) == 2
    assert c.get("/api/admin/stats").status_code == 200
    assert c.get("/admin").status_code == 200
    # cambia el plan de un cliente
    r2 = c.post("/api/admin/plan", json={"user_id": objetivo["id"], "plan": "team"})
    assert r2.status_code == 200 and r2.get_json()["ok"] is True
    assert nexus_db.obtener_usuario(objetivo["id"])["plan"] == "team"


def test_config_expone_admin(monkeypatch):
    c = _cliente_admin(monkeypatch, "admin@nexus.com")
    nexus_db.crear_usuario("admin@nexus.com", "secreta1")
    c.post("/login", data={"email": "admin@nexus.com", "password": "secreta1"})
    assert c.get("/api/config").get_json()["admin"] is True
