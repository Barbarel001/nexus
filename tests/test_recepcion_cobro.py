# -*- coding: utf-8 -*-
"""Tests del cobro por suscripcion (Stripe), sin claves ni red: firma del webhook,
procesamiento de eventos, gate de actividad y el endpoint (checkout/webhook)."""

import json

import pytest

import nexus_db
import nexus_recepcion_cobro as cobro
import nexus_recepcion_saas as saas


@pytest.fixture(autouse=True)
def _db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "cobro.db"))
    saas._HITS.clear()
    saas._SESIONES.clear()
    cobro.init()


def _evento(tipo, obj):
    return {"type": tipo, "data": {"object": obj}}


# --------------------------- Migracion / estado ---------------------------

def test_init_agrega_columnas_de_cobro():
    saas.crear_negocio("A", slug="a")
    e = cobro.estado_cobro("a")
    assert e is not None and "current_period_end" in e and "stripe_customer_id" in e


def test_estado_negocio_inexistente_none():
    assert cobro.estado_cobro("fantasma") is None


# --------------------------- Firma del webhook (hmac, sin lib stripe) ---------------------------

def test_firma_valida_y_invalida():
    payload = b'{"hello":"world"}'
    cab = cobro.firmar(payload, "whsec_test")
    assert cobro.verificar_firma(payload, cab, secret="whsec_test") is True
    # Secreto equivocado -> falla.
    assert cobro.verificar_firma(payload, cab, secret="otro") is False
    # Payload alterado -> falla.
    assert cobro.verificar_firma(b'{"hello":"tampered"}', cab, secret="whsec_test") is False


def test_firma_caducada_falla():
    payload = b'{}'
    cab = cobro.firmar(payload, "whsec_test", ts=1)  # timestamp muy viejo
    assert cobro.verificar_firma(payload, cab, secret="whsec_test", tolerancia=300) is False


def test_firma_sin_secreto_o_cabecera_falla():
    assert cobro.verificar_firma(b'{}', "", secret="whsec_test") is False
    assert cobro.verificar_firma(b'{}', "t=1,v1=x", secret="") is False


# --------------------------- Procesar eventos (activa/desactiva el gate) ---------------------------

def test_checkout_completado_activa_y_guarda_ids():
    saas.crear_negocio("A", slug="a")
    saas.fijar_estado_cuenta("a", activo=False)  # arranca inactivo
    ev = _evento("checkout.session.completed", {
        "customer": "cus_1", "subscription": "sub_1",
        "metadata": {"negocio": "a", "plan": "pro"}})
    cobro.procesar_evento(ev)
    e = cobro.estado_cobro("a")
    assert e["activo"] is True and e["plan"] == "pro"
    assert e["stripe_customer_id"] == "cus_1" and e["stripe_subscription_id"] == "sub_1"
    # El gate publico del recepcionista ya lo ve activo.
    assert saas.negocio_activo(saas.obtener_negocio("a")) is True


def test_subscription_impago_desactiva_por_customer():
    saas.crear_negocio("A", slug="a")
    cobro.procesar_evento(_evento("checkout.session.completed", {
        "customer": "cus_1", "subscription": "sub_1", "metadata": {"negocio": "a", "plan": "pro"}}))
    cobro.procesar_evento(_evento("customer.subscription.updated", {
        "id": "sub_1", "customer": "cus_1", "status": "past_due"}))
    assert saas.negocio_activo(saas.obtener_negocio("a")) is False


def test_subscription_reactivada():
    saas.crear_negocio("A", slug="a")
    cobro.procesar_evento(_evento("checkout.session.completed", {
        "customer": "cus_1", "subscription": "sub_1", "metadata": {"negocio": "a", "plan": "pro"}}))
    cobro.procesar_evento(_evento("customer.subscription.updated", {
        "id": "sub_1", "customer": "cus_1", "status": "past_due"}))
    cobro.procesar_evento(_evento("customer.subscription.updated", {
        "id": "sub_1", "customer": "cus_1", "status": "active", "current_period_end": 4102444800}))
    e = cobro.estado_cobro("a")
    assert e["activo"] is True and e["current_period_end"] == 4102444800


def test_subscription_cancelada_desactiva():
    saas.crear_negocio("A", slug="a")
    cobro.procesar_evento(_evento("checkout.session.completed", {
        "customer": "cus_1", "subscription": "sub_1", "metadata": {"negocio": "a", "plan": "pro"}}))
    cobro.procesar_evento(_evento("customer.subscription.deleted", {"id": "sub_1", "customer": "cus_1"}))
    assert saas.negocio_activo(saas.obtener_negocio("a")) is False


def test_checkout_sin_negocio_valido_se_ignora():
    msg = cobro.procesar_evento(_evento("checkout.session.completed", {
        "customer": "cus_x", "metadata": {"negocio": "fantasma", "plan": "pro"}}))
    assert "ignorado" in msg.lower()


def test_evento_desconocido_se_ignora():
    assert "ignorado" in cobro.procesar_evento(_evento("invoice.paid", {})).lower()


def test_evento_no_cruza_negocios():
    saas.crear_negocio("A", slug="a")
    saas.crear_negocio("B", slug="b")
    cobro.procesar_evento(_evento("checkout.session.completed", {
        "customer": "cus_a", "subscription": "sub_a", "metadata": {"negocio": "a", "plan": "pro"}}))
    # Un impago de la suscripcion de A no debe tocar a B.
    cobro.procesar_evento(_evento("customer.subscription.deleted", {"id": "sub_a", "customer": "cus_a"}))
    assert saas.negocio_activo(saas.obtener_negocio("a")) is False
    assert saas.obtener_negocio("b")["activo"] is True


# --------------------------- Checkout: configuracion ---------------------------

def test_crear_checkout_sin_stripe_lanza(monkeypatch):
    saas.crear_negocio("A", slug="a")
    monkeypatch.setattr(cobro, "STRIPE_KEY", "")
    with pytest.raises(RuntimeError):
        cobro.crear_checkout("a", "pro")


def test_crear_checkout_plan_invalido():
    saas.crear_negocio("A", slug="a")
    with pytest.raises(ValueError):
        cobro.crear_checkout("a", "inexistente")


# --------------------------- Endpoint (Flask) ---------------------------

@pytest.fixture()
def cliente_web():
    flask = pytest.importorskip("flask")
    app = flask.Flask(__name__)
    app.register_blueprint(cobro.crear_blueprint())
    return app.test_client()


def test_webhook_firma_mala_400(cliente_web):
    r = cliente_web.post("/billing/webhook", data=b"{}",
                         headers={"Stripe-Signature": "t=1,v1=malo"})
    assert r.status_code == 400


def test_webhook_valido_procesa(cliente_web, monkeypatch):
    saas.crear_negocio("A", slug="a")
    saas.fijar_estado_cuenta("a", activo=False)
    monkeypatch.setattr(cobro, "WEBHOOK_SECRET", "whsec_test")
    payload = json.dumps(_evento("checkout.session.completed", {
        "customer": "cus_1", "subscription": "sub_1",
        "metadata": {"negocio": "a", "plan": "basico"}})).encode()
    cab = cobro.firmar(payload, "whsec_test")
    r = cliente_web.post("/billing/webhook", data=payload,
                         headers={"Stripe-Signature": cab, "Content-Type": "application/json"})
    assert r.status_code == 200
    assert saas.negocio_activo(saas.obtener_negocio("a")) is True


def test_checkout_endpoint_503_sin_stripe(cliente_web, monkeypatch):
    saas.crear_negocio("A", slug="a")
    monkeypatch.setattr(cobro, "STRIPE_KEY", "")
    r = cliente_web.post("/billing/a/checkout", json={"plan": "pro"})
    assert r.status_code == 503


def test_checkout_endpoint_404_negocio(cliente_web):
    assert cliente_web.post("/billing/fantasma/checkout", json={"plan": "pro"}).status_code == 404


def test_estado_endpoint(cliente_web):
    saas.crear_negocio("A", slug="a")
    r = cliente_web.get("/billing/a/estado")
    assert r.status_code == 200 and "activo" in r.get_json()
