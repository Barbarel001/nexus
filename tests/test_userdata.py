# -*- coding: utf-8 -*-
"""Tests del aislamiento de datos por usuario (nexus_ctx) en modo multiusuario."""

import pytest

import nexus
import nexus_ctx
import nexus_gastos as gastos
import nexus_tareas as tareas


@pytest.fixture(autouse=True)
def _ctx_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_ctx, "USERS_DIR", str(tmp_path / "users"))
    nexus_ctx.clear_user()
    yield
    nexus_ctx.clear_user()


# --------------------------- nexus_ctx ---------------------------

def test_user_path_global_sin_usuario(tmp_path):
    p = str(tmp_path / "tareas.json")
    assert nexus_ctx.user_path(p) == p   # sin usuario -> ruta global


def test_user_path_por_usuario():
    nexus_ctx.set_user(7)
    p = nexus_ctx.user_path("/x/tareas.json")
    assert "/users/7/tareas.json" in p.replace("\\", "/")


# --------------------------- Aislamiento real ---------------------------

def test_tareas_aisladas_por_usuario():
    nexus_ctx.set_user(1)
    tareas.agregar("tarea de Ana")
    assert len(tareas.filtrar("todas")) == 1

    nexus_ctx.set_user(2)              # otro usuario: no ve nada
    assert tareas.filtrar("todas") == []
    tareas.agregar("tarea de Luis")
    assert len(tareas.filtrar("todas")) == 1

    nexus_ctx.set_user(1)             # Ana sigue viendo solo lo suyo
    todas = tareas.filtrar("todas")
    assert len(todas) == 1 and todas[0]["texto"] == "tarea de Ana"


def test_gastos_aislados_por_usuario():
    nexus_ctx.set_user(1)
    gastos.agregar(10, "comida")
    nexus_ctx.set_user(2)
    assert gastos.cargar() == []
    nexus_ctx.set_user(1)
    assert len(gastos.cargar()) == 1


def test_memoria_aislada_por_usuario():
    nexus_ctx.set_user(1)
    nexus.guardar_nota("dato de Ana", "personal")
    nexus_ctx.set_user(2)
    assert nexus.cargar_memoria() == []
    nexus_ctx.set_user(1)
    assert "dato de Ana" in nexus.cargar_memoria()


# --------------------------- Integración web ---------------------------

def test_conversaciones_aisladas_web(monkeypatch, tmp_path):
    import nexus_db
    import nexus_web
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", True)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "u.db"))
    monkeypatch.setattr(tareas, "TAREAS_PATH", str(tmp_path / "tareas.json"))
    nexus_db.init()
    c = nexus_web.app.test_client()

    def tok():
        r = c.get("/")
        for h in r.headers.getlist("Set-Cookie"):
            if "nexus_csrf=" in h:
                return h.split("nexus_csrf=", 1)[1].split(";", 1)[0]
        return ""

    # Usuario A crea una tarea (vía la herramienta segura a través del panel API)
    c.post("/register", data={"email": "a@x.com", "password": "secreta1"})
    c.post("/api/tarea/agregar", json={"texto": "tarea de A"}, headers={"X-CSRF-Token": tok()})
    assert any(t["texto"] == "tarea de A" for t in c.get("/api/panel").get_json()["tareas"])
    c.get("/logout")
    # Usuario B no ve las tareas de A
    c.post("/register", data={"email": "b@x.com", "password": "secreta1"})
    assert c.get("/api/panel").get_json()["tareas"] == []
