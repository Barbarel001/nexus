# -*- coding: utf-8 -*-
"""Tests de la cuenta de usuario: contraseña, exportar y borrar (datos + BD)."""

import os
import pytest

import nexus_db
import nexus_ctx
import nexus_web


# --------------------------- BD ---------------------------

@pytest.fixture
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "c.db"))
    nexus_db.init()


def test_cambiar_password(_db):
    u = nexus_db.crear_usuario("a@b.com", "viejaclave")
    with pytest.raises(ValueError):
        nexus_db.cambiar_password(u["id"], "incorrecta", "nuevaclave")
    with pytest.raises(ValueError):
        nexus_db.cambiar_password(u["id"], "viejaclave", "corta")   # < 6
    nexus_db.cambiar_password(u["id"], "viejaclave", "nuevaclave")
    assert nexus_db.autenticar("a@b.com", "nuevaclave")
    assert not nexus_db.autenticar("a@b.com", "viejaclave")


def test_borrar_usuario(_db):
    u = nexus_db.crear_usuario("x@y.com", "secreta1")
    nexus_db.guardar_dato(u["id"], "k", {"v": 1})
    nexus_db.borrar_usuario(u["id"])
    assert nexus_db.obtener_usuario(u["id"]) is None
    assert nexus_db.cargar_dato(u["id"], "k") is None


def test_borrar_datos_en_disco(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_ctx, "USERS_DIR", str(tmp_path / "users"))
    nexus_ctx.set_user(99)
    carpeta = nexus_ctx._carpeta_usuario()
    open(os.path.join(carpeta, "tareas.json"), "w").write("[]")
    nexus_ctx.clear_user()
    assert os.path.isdir(carpeta)
    assert nexus_ctx.borrar_datos(99) is True
    assert not os.path.isdir(carpeta)


# --------------------------- Web ---------------------------

def _tok(c):
    r = c.get("/")
    for h in r.headers.getlist("Set-Cookie"):
        if "nexus_csrf=" in h:
            return h.split("nexus_csrf=", 1)[1].split(";", 1)[0]
    return ""


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", True)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "cw.db"))
    monkeypatch.setattr(nexus_ctx, "USERS_DIR", str(tmp_path / "users"))
    nexus_db.init()
    return nexus_web.app.test_client()


def test_perfil_y_password_web(cliente):
    c = cliente
    c.post("/register", data={"email": "u@x.com", "password": "secreta1"})
    perfil = c.get("/api/cuenta").get_json()
    assert perfil["email"] == "u@x.com" and perfil["twofa"] is False
    r = c.post("/api/cuenta/password", json={"actual": "secreta1", "nueva": "secreta2"},
               headers={"X-CSRF-Token": _tok(c)})
    assert r.get_json()["ok"] is True


def test_exportar_datos_web(cliente):
    c = cliente
    c.post("/register", data={"email": "e@x.com", "password": "secreta1"})
    c.post("/api/trade", json={"instrument": "MNQ", "pnl": 30}, headers={"X-CSRF-Token": _tok(c)})
    r = c.get("/api/cuenta/exportar")
    assert r.headers["Content-Disposition"].startswith("attachment")
    data = r.get_json()
    assert data["perfil"]["email"] == "e@x.com"
    assert any(o["instrument"] == "MNQ" for o in data["operaciones"])


def test_borrar_cuenta_web(cliente):
    c = cliente
    c.post("/register", data={"email": "b@x.com", "password": "secreta1"})
    # contraseña incorrecta -> no borra
    assert c.post("/api/cuenta/borrar", json={"password": "mala"},
                  headers={"X-CSRF-Token": _tok(c)}).status_code == 400
    # correcta -> borra y cierra sesión
    r = c.post("/api/cuenta/borrar", json={"password": "secreta1"}, headers={"X-CSRF-Token": _tok(c)})
    assert r.get_json()["ok"] is True
    assert nexus_db.usuario_por_email("b@x.com") is None
    assert c.get("/api/cuenta").status_code == 401   # ya sin sesión
