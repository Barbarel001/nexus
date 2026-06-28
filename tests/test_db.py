# -*- coding: utf-8 -*-
"""Tests de la base de datos / cuentas (SQLite) y del login multiusuario."""

import pytest

import nexus_db


@pytest.fixture(autouse=True)
def _db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "test.db"))
    nexus_db.init()


# --------------------------- Usuarios ---------------------------

def test_crear_y_autenticar():
    u = nexus_db.crear_usuario("Test@Mail.com", "secreta1")
    assert u["email"] == "test@mail.com" and u["plan"] == "free"
    assert nexus_db.autenticar("test@mail.com", "secreta1")["id"] == u["id"]
    assert nexus_db.autenticar("test@mail.com", "mala") is None
    assert nexus_db.autenticar("otro@mail.com", "secreta1") is None


def test_email_duplicado():
    nexus_db.crear_usuario("a@b.com", "secreta1")
    with pytest.raises(ValueError):
        nexus_db.crear_usuario("a@b.com", "otra123")


def test_validaciones():
    with pytest.raises(ValueError):
        nexus_db.crear_usuario("no-es-email", "secreta1")
    with pytest.raises(ValueError):
        nexus_db.crear_usuario("a@b.com", "corta")  # <6


def test_password_no_se_guarda_en_claro():
    nexus_db.crear_usuario("a@b.com", "secretaza")
    with nexus_db._conn() as c:
        row = c.execute("SELECT password_hash FROM users WHERE email='a@b.com'").fetchone()
    assert "secretaza" not in row["password_hash"] and "$" in row["password_hash"]


def test_plan_y_conteo():
    u = nexus_db.crear_usuario("a@b.com", "secreta1")
    nexus_db.cambiar_plan(u["id"], "pro")
    assert nexus_db.obtener_usuario(u["id"])["plan"] == "pro"
    assert nexus_db.contar_usuarios() == 1


# --------------------------- Datos por usuario ---------------------------

def test_datos_por_usuario():
    u = nexus_db.crear_usuario("a@b.com", "secreta1")
    nexus_db.guardar_dato(u["id"], "tareas", [{"t": "x"}])
    assert nexus_db.cargar_dato(u["id"], "tareas") == [{"t": "x"}]
    nexus_db.guardar_dato(u["id"], "tareas", [{"t": "y"}])     # upsert
    assert nexus_db.cargar_dato(u["id"], "tareas") == [{"t": "y"}]
    assert nexus_db.cargar_dato(u["id"], "inexistente", "def") == "def"


# --------------------------- Login web multiusuario ---------------------------

def test_login_multiusuario(monkeypatch, tmp_path):
    import nexus_web
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", True)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "web.db"))
    nexus_db.init()
    c = nexus_web.app.test_client()
    # sin login: API bloqueada
    assert c.get("/api/config").status_code == 401
    # registro -> con acceso
    r = c.post("/register", data={"email": "user@mail.com", "password": "secreta1"})
    assert r.status_code in (301, 302)
    assert c.get("/api/config").status_code == 200
    # logout y login de nuevo
    c.get("/logout")
    assert c.get("/api/config").status_code == 401
    r2 = c.post("/login", data={"email": "user@mail.com", "password": "secreta1"})
    assert r2.status_code in (301, 302)
    assert c.get("/api/config").status_code == 200
