# -*- coding: utf-8 -*-
"""Tests del canal de WhatsApp (Twilio). Sin red: enrutado por numero, firma del
webhook, TwiML, gate de actividad y aislamiento por negocio."""

import base64
import hashlib
import hmac

import pytest

import nexus_db
import nexus_recepcion_saas as saas
import nexus_recepcion_whatsapp as wa


@pytest.fixture(autouse=True)
def _db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "wa.db"))
    saas._HITS.clear()
    saas._SESIONES.clear()
    wa._SESIONES.clear()
    wa.init()


# --------------------------- Numero -> negocio ---------------------------

def test_set_y_buscar_por_wa_number():
    saas.crear_negocio("A", slug="a")
    n = wa.set_wa_number("a", "+34600111222")
    assert n == "whatsapp:+34600111222"
    assert wa.negocio_por_wa("whatsapp:+34600111222") == "a"
    assert wa.negocio_por_wa("+34600111222") == "a"   # normaliza el prefijo
    assert wa.negocio_por_wa("+34000000000") is None


def test_set_wa_negocio_inexistente_falla():
    with pytest.raises(ValueError):
        wa.set_wa_number("fantasma", "+34600111222")


def test_numeros_aislados_por_negocio():
    saas.crear_negocio("A", slug="a")
    saas.crear_negocio("B", slug="b")
    wa.set_wa_number("a", "+34600111222")
    wa.set_wa_number("b", "+34600333444")
    assert wa.negocio_por_wa("+34600111222") == "a"
    assert wa.negocio_por_wa("+34600333444") == "b"


# --------------------------- Firma del webhook (hmac-sha1) ---------------------------

def _firmar(url, params, token):
    base = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), base.encode(), hashlib.sha1).digest()).decode()


def test_firma_valida_e_invalida():
    url = "https://x/wa/webhook"
    params = {"From": "whatsapp:+34600", "To": "whatsapp:+34611", "Body": "hola"}
    firma = _firmar(url, params, "tok")
    assert wa.verificar_firma(url, params, firma, token="tok") is True
    assert wa.verificar_firma(url, params, firma, token="otro") is False
    assert wa.verificar_firma(url, {**params, "Body": "otra"}, firma, token="tok") is False
    assert wa.verificar_firma(url, params, "", token="tok") is False


# --------------------------- TwiML ---------------------------

def test_twiml_escapa_y_envuelve():
    x = wa.twiml("precio <100> & ok")
    assert x.startswith("<?xml") and "<Response><Message>" in x
    assert "&lt;100&gt;" in x and "&amp;" in x


# --------------------------- responder_whatsapp (sesion por cliente) ---------------------------

def test_responder_whatsapp_usa_responder_cliente(monkeypatch):
    saas.crear_negocio("A", slug="a")
    monkeypatch.setattr(saas, "responder_cliente",
                        lambda slug, msg, **kw: {"ok": True, "texto": f"[{slug}] {msg}"})
    assert wa.responder_whatsapp("a", "whatsapp:+34600", "hola") == "[a] hola"


# --------------------------- Webhook (Flask) ---------------------------

@pytest.fixture()
def cliente_web():
    flask = pytest.importorskip("flask")
    app = flask.Flask(__name__)
    app.register_blueprint(wa.crear_blueprint())
    return app.test_client()


def _post(cliente, **form):
    return cliente.post("/wa/webhook", data=form)


def test_webhook_enruta_y_responde(cliente_web, monkeypatch):
    saas.crear_negocio("A", slug="a")
    wa.set_wa_number("a", "+34611")
    monkeypatch.setattr(saas, "responder_cliente",
                        lambda slug, msg, **kw: {"ok": True, "texto": "respuesta de A"})
    r = _post(cliente_web, From="whatsapp:+34600", To="whatsapp:+34611", Body="hola")
    assert r.status_code == 200 and b"respuesta de A" in r.data
    assert r.mimetype == "text/xml"


def test_webhook_numero_desconocido(cliente_web):
    r = _post(cliente_web, From="whatsapp:+34600", To="whatsapp:+34999", Body="hola")
    assert r.status_code == 200 and b"no esta disponible" in r.data


def test_webhook_negocio_inactivo(cliente_web):
    saas.crear_negocio("A", slug="a")
    wa.set_wa_number("a", "+34611")
    saas.fijar_estado_cuenta("a", activo=False)
    r = _post(cliente_web, From="whatsapp:+34600", To="whatsapp:+34611", Body="hola")
    assert b"no esta disponible" in r.data


def test_webhook_firma_requerida_si_hay_token(cliente_web, monkeypatch):
    saas.crear_negocio("A", slug="a")
    wa.set_wa_number("a", "+34611")
    monkeypatch.setattr(wa, "AUTH_TOKEN", "tok")
    # Sin firma valida -> 403.
    r = _post(cliente_web, From="whatsapp:+34600", To="whatsapp:+34611", Body="hola")
    assert r.status_code == 403


def test_webhook_cuerpo_vacio_saluda(cliente_web):
    saas.crear_negocio("A", slug="a")
    wa.set_wa_number("a", "+34611")
    r = _post(cliente_web, From="whatsapp:+34600", To="whatsapp:+34611", Body="")
    assert b"ayudarte" in r.data
