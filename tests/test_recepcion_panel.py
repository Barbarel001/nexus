# -*- coding: utf-8 -*-
"""Tests del panel del dueño. Sin red: auth por negocio, aislamiento entre
negocios, gestion de leads/servicios/FAQ y el flujo web (Flask)."""

import pytest

import nexus_db
import nexus_recepcion_panel as panel
import nexus_recepcion_saas as saas


@pytest.fixture(autouse=True)
def _db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "panel.db"))
    saas._HITS.clear()
    saas._SESIONES.clear()
    panel._TOKENS.clear()
    panel.init()


# --------------------------- Contraseña ---------------------------

def test_fijar_y_verificar_password():
    saas.crear_negocio("A", slug="a")
    panel.fijar_password("a", "secreto")
    assert panel.tiene_password("a") is True
    assert panel.verificar_password("a", "secreto") is True
    assert panel.verificar_password("a", "malo") is False


def test_password_corta_falla():
    saas.crear_negocio("A", slug="a")
    with pytest.raises(ValueError):
        panel.fijar_password("a", "123")


def test_password_negocio_inexistente_falla():
    with pytest.raises(ValueError):
        panel.fijar_password("fantasma", "secreto")


def test_sin_password_no_verifica():
    saas.crear_negocio("A", slug="a")
    assert panel.tiene_password("a") is False
    assert panel.verificar_password("a", "loquesea") is False


# --------------------------- Sesiones / aislamiento ---------------------------

def test_token_valido_y_aislado_por_negocio():
    saas.crear_negocio("A", slug="a")
    saas.crear_negocio("B", slug="b")
    tok = panel.crear_token("a")
    assert panel.slug_de_token(tok) == "a"
    assert panel._autorizado(tok, "a") is True
    # El token de A no autoriza el negocio B.
    assert panel._autorizado(tok, "b") is False


def test_token_caduca(monkeypatch):
    saas.crear_negocio("A", slug="a")
    monkeypatch.setattr(panel, "SESSION_TTL", 0)
    tok = panel.crear_token("a")
    assert panel.slug_de_token(tok) is None


def test_logout_invalida_token():
    saas.crear_negocio("A", slug="a")
    tok = panel.crear_token("a")
    panel.cerrar(tok)
    assert panel.slug_de_token(tok) is None


# --------------------------- Flujo web (Flask) ---------------------------

@pytest.fixture()
def cliente_web():
    flask = pytest.importorskip("flask")
    app = flask.Flask(__name__)
    app.register_blueprint(panel.crear_blueprint())
    return app.test_client()


def _negocio_con_pw(slug="a", pw="secreto"):
    saas.crear_negocio(slug.upper(), slug=slug)
    panel.fijar_password(slug, pw)


def test_panel_muestra_login_sin_sesion(cliente_web):
    _negocio_con_pw()
    r = cliente_web.get("/panel/a")
    assert r.status_code == 200 and b"password" in r.data.lower()


def test_panel_negocio_inexistente_404(cliente_web):
    assert cliente_web.get("/panel/fantasma").status_code == 404


def test_login_malo_401(cliente_web):
    _negocio_con_pw()
    r = cliente_web.post("/panel/a/login", data={"password": "malo"})
    assert r.status_code == 401


def test_login_ok_da_cookie_y_acceso(cliente_web):
    _negocio_con_pw()
    r = cliente_web.post("/panel/a/login", data={"password": "secreto"})
    assert r.status_code == 302
    # La cookie de sesion queda fijada en el cliente; el panel ya carga.
    r2 = cliente_web.get("/panel/a")
    assert r2.status_code == 200 and b"Chat publico" in r2.data


def test_api_requiere_sesion(cliente_web):
    _negocio_con_pw()
    assert cliente_web.get("/panel/a/api/leads").status_code == 401


def test_api_leads_y_marcar_tras_login(cliente_web):
    _negocio_con_pw()
    saas.capturar_lead("a", contacto="600111222", servicio="x", avisar=False)
    cliente_web.post("/panel/a/login", data={"password": "secreto"})
    j = cliente_web.get("/panel/a/api/leads").get_json()
    assert len(j["leads"]) == 1
    lead_id = j["leads"][0]["id"]
    r = cliente_web.post(f"/panel/a/api/lead/{lead_id}/estado", json={"estado": "ganado"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert cliente_web.get("/panel/a/api/leads?filtro=ganados").get_json()["leads"][0]["id"] == lead_id


def test_api_agregar_servicio_y_faq(cliente_web):
    _negocio_con_pw()
    cliente_web.post("/panel/a/login", data={"password": "secreto"})
    r = cliente_web.post("/panel/a/api/servicio",
                         json={"nombre": "limpieza casa", "base": 80, "por_unidad": 20})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    r2 = cliente_web.post("/panel/a/api/faq", json={"pregunta": "horario", "respuesta": "9 a 18h"})
    assert r2.status_code == 200
    n = saas.obtener_negocio("a")
    assert n["servicios"][0]["nombre"] == "limpieza casa" and n["faq"][0]["respuesta"] == "9 a 18h"


def test_api_servicio_invalido_400(cliente_web):
    _negocio_con_pw()
    cliente_web.post("/panel/a/login", data={"password": "secreto"})
    r = cliente_web.post("/panel/a/api/servicio", json={"nombre": "", "base": 10})
    assert r.status_code == 400


def test_sesion_de_a_no_accede_a_b(cliente_web):
    _negocio_con_pw("a")
    _negocio_con_pw("b")
    saas.capturar_lead("b", contacto="600999888", servicio="y", avisar=False)
    cliente_web.post("/panel/a/login", data={"password": "secreto"})
    # Con la cookie de A, la API de B debe rechazar (aislamiento).
    assert cliente_web.get("/panel/b/api/leads").status_code == 401
