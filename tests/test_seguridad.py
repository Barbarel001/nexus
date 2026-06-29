# -*- coding: utf-8 -*-
"""Tests de las mejoras de seguridad: TOTP (2FA), CSRF y el flujo de login 2FA."""

import pytest

import nexus_totp
import nexus_db
import nexus_web


# --------------------------- TOTP (unidad) ---------------------------

def test_totp_genera_y_verifica():
    s = nexus_totp.generar_secreto()
    assert len(s) >= 16 and s.isalnum()
    codigo = nexus_totp.codigo_actual(s, t=1_000_000)
    assert len(codigo) == 6 and codigo.isdigit()
    assert nexus_totp.verificar(s, codigo, t=1_000_000)


def test_totp_rechaza_codigo_malo():
    s = nexus_totp.generar_secreto()
    assert not nexus_totp.verificar(s, "000000", t=1_000_000) or \
        nexus_totp.codigo_actual(s, t=1_000_000) == "000000"
    assert not nexus_totp.verificar(s, "abc", t=1_000_000)
    assert not nexus_totp.verificar(s, "", t=1_000_000)
    assert not nexus_totp.verificar("", "123456")


def test_totp_ventana_tolerancia():
    s = nexus_totp.generar_secreto()
    # El codigo del periodo anterior sigue siendo valido (ventana +-1).
    anterior = nexus_totp.codigo_actual(s, t=1_000_000 - 30)
    assert nexus_totp.verificar(s, anterior, t=1_000_000)
    # Dos periodos atras ya no.
    lejano = nexus_totp.codigo_actual(s, t=1_000_000 - 90)
    assert not nexus_totp.verificar(s, lejano, t=1_000_000)


def test_otpauth_uri():
    uri = nexus_totp.uri_otpauth("ABC234", "yo@x.com")
    assert uri.startswith("otpauth://totp/") and "secret=ABC234" in uri and "issuer=NEXUS" in uri


# --------------------------- BD: 2FA ---------------------------

def test_db_totp_ciclo(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "t.db"))
    u = nexus_db.crear_usuario("z@x.com", "secreta1")
    assert nexus_db.get_totp(u["id"]) == (None, False)
    nexus_db.set_totp_secret(u["id"], "SECRETO")
    assert nexus_db.get_totp(u["id"]) == ("SECRETO", False)
    nexus_db.enable_totp(u["id"])
    assert nexus_db.get_totp(u["id"]) == ("SECRETO", True)
    nexus_db.disable_totp(u["id"])
    assert nexus_db.get_totp(u["id"]) == (None, False)


# --------------------------- Web: helpers ---------------------------

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
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "s.db"))
    import nexus_tareas
    monkeypatch.setattr(nexus_tareas, "TAREAS_PATH", str(tmp_path / "tareas.json"))
    nexus_db.init()
    return nexus_web.app.test_client()


# --------------------------- Web: CSRF ---------------------------

def test_csrf_bloquea_post_sin_token(cliente):
    cliente.post("/register", data={"email": "a@x.com", "password": "secreta1"})  # exento
    # POST autenticado SIN token -> 403
    r = cliente.post("/api/tarea/agregar", json={"texto": "x"})
    assert r.status_code == 403
    # CON token -> ok
    r2 = cliente.post("/api/tarea/agregar", json={"texto": "x"},
                      headers={"X-CSRF-Token": _tok(cliente)})
    assert r2.status_code == 200 and r2.get_json()["ok"] is True


def test_csrf_no_aplica_sin_login(tmp_path, monkeypatch):
    # Sin auth (uso local), los POST no requieren token (no rompe el modo de siempre).
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    import nexus_tareas
    monkeypatch.setattr(nexus_tareas, "TAREAS_PATH", str(tmp_path / "tareas.json"))
    c = nexus_web.app.test_client()
    r = c.post("/api/tarea/agregar", json={"texto": "libre"})
    assert r.status_code == 200


# --------------------------- Web: flujo 2FA completo ---------------------------

def test_flujo_2fa_login(cliente):
    c = cliente
    c.post("/register", data={"email": "u@x.com", "password": "secreta1"})
    # 1) Generar secreto
    r = c.post("/api/2fa/setup", headers={"X-CSRF-Token": _tok(c)})
    secret = r.get_json()["secret"]
    assert secret
    # 2) Activar con un codigo valido
    codigo = nexus_totp.codigo_actual(secret)
    r2 = c.post("/api/2fa/activar", json={"code": codigo}, headers={"X-CSRF-Token": _tok(c)})
    assert r2.get_json()["ok"] is True
    assert c.get("/api/2fa/estado").get_json()["enabled"] is True
    # 3) Logout y volver a entrar: la contraseña sola NO basta -> pide 2º factor
    c.get("/logout")
    r3 = c.post("/login", data={"email": "u@x.com", "password": "secreta1"})
    assert b"/login/2fa" in r3.data                       # muestra el desafio, no entra aun
    assert c.get("/api/2fa/estado").status_code == 401     # aun no autenticado
    # 4) Codigo incorrecto -> sigue fuera
    assert b"incorrecto" in c.post("/login/2fa", data={"code": "000001"}).data
    assert c.get("/api/2fa/estado").status_code == 401
    # 5) Codigo correcto -> dentro
    c.post("/login/2fa", data={"code": nexus_totp.codigo_actual(secret)})
    assert c.get("/api/2fa/estado").get_json()["enabled"] is True


def test_2fa_no_disponible_en_modo_clave_unica(tmp_path, monkeypatch):
    # Con NEXUS_PASSWORD (una sola clave, sin cuentas) el 2FA no aplica.
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "clave-secreta")
    c = nexus_web.app.test_client()
    c.post("/login", data={"password": "clave-secreta"})
    assert c.get("/api/2fa/estado").get_json()["disponible"] is False
