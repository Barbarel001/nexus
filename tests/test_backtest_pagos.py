# -*- coding: utf-8 -*-
"""Tests del motor de backtesting y del scaffold de pagos (Stripe)."""

import pytest

import nexus
import nexus_backtest as bt
import nexus_pagos as pagos

# --------------------------- Backtest ---------------------------

def test_sma():
    assert bt._sma([1, 2, 3, 4], 2, 3) == 3.5
    assert bt._sma([1, 2, 3], 2, 0) is None   # aun no hay ventana


def test_cruce_medias_detecta_operacion():
    # Sube y luego baja -> al menos una operación cerrada (compra y vende).
    precios = [10, 10, 10, 10, 11, 12, 13, 14, 15, 14, 12, 10, 9, 9, 9, 9]
    r = bt.cruce_medias(precios, corta=2, larga=4)
    assert r["operaciones"] >= 1
    assert 0 <= r["win_rate"] <= 100
    assert isinstance(r["retorno_pct"], float)


def test_cruce_medias_validaciones():
    with pytest.raises(ValueError):
        bt.cruce_medias([1, 2, 3], corta=5, larga=20)      # pocos datos
    with pytest.raises(ValueError):
        bt.cruce_medias(list(range(50)), corta=20, larga=5)  # corta >= larga


def test_tool_backtest_pocos_datos():
    assert "al menos" in bt.tool_backtest({"precios": "1,2,3"})


def test_tool_backtest_ok():
    serie = ",".join(str(x) for x in [10, 10, 10, 10, 11, 12, 13, 14, 15, 14, 12, 10,
                                      9, 9, 9, 9, 10, 11, 12, 13, 14, 15, 16])
    out = bt.tool_backtest({"precios": serie, "corta": 3, "larga": 8})
    assert "Backtest" in out and "Win rate" in out


def test_backtest_registrada():
    assert "backtest" in nexus.EJECUTORES
    assert "backtest" in {t.get("name") for t in nexus.TOOLS}


# --------------------------- Pagos (scaffold) ---------------------------

def test_pagos_no_configurado(monkeypatch):
    monkeypatch.setattr(pagos, "STRIPE_KEY", "")
    assert pagos.configurado() is False
    with pytest.raises(RuntimeError):
        pagos.crear_checkout("pro")


def test_pagos_plan_invalido():
    with pytest.raises(ValueError):
        pagos.crear_checkout("plan_inexistente")


def test_api_checkout_sin_stripe(monkeypatch):
    import nexus_web
    monkeypatch.setattr(nexus_web.pagos, "STRIPE_KEY", "")
    c = nexus_web.app.test_client()
    r = c.get("/api/checkout?plan=pro")
    assert r.status_code == 400 and r.get_json()["ok"] is False


def test_webhook_sin_secret(monkeypatch):
    monkeypatch.setattr(pagos, "WEBHOOK_SECRET", "")
    with pytest.raises(RuntimeError):
        pagos.verificar_webhook(b"{}", "sig")


def test_api_webhook_firma_invalida(monkeypatch):
    import nexus_web
    # Sin secret valido / firma -> 400 (no revienta el servidor).
    monkeypatch.setattr(nexus_web.pagos, "WEBHOOK_SECRET", "")
    c = nexus_web.app.test_client()
    r = c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
    assert r.status_code == 400


def test_webhook_activa_plan(monkeypatch, tmp_path):
    """Simula un evento de Stripe y comprueba que sube el plan del usuario."""
    import nexus_db
    import nexus_web
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "wh.db"))
    nexus_db.init()
    u = nexus_db.crear_usuario("pagador@mail.com", "secreta1")
    # Falseamos la verificacion de Stripe para devolver un evento ya validado.
    evento = {"type": "checkout.session.completed",
              "data": {"object": {"customer_email": "pagador@mail.com", "metadata": {"plan": "pro"}}}}
    monkeypatch.setattr(nexus_web.pagos, "verificar_webhook", lambda *a, **k: evento)
    c = nexus_web.app.test_client()
    r = c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
    assert r.status_code == 200
    assert nexus_db.obtener_usuario(u["id"])["plan"] == "pro"
