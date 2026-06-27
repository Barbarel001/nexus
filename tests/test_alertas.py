# -*- coding: utf-8 -*-
"""Tests de alertas de precio. La lectura de precios de NinjaTrader se simula."""

import pytest

import nexus
import nexus_alertas as alertas
import nexus_ninjatrader as nt


@pytest.fixture(autouse=True)
def _archivo_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(alertas, "ALERTAS_PATH", str(tmp_path / "alertas.json"))


# --------------------------- Normalizacion ---------------------------

def test_normalizar_op():
    assert alertas.normalizar_op(">=") == ">="
    assert alertas.normalizar_op("sube") == ">="
    assert alertas.normalizar_op("toca") == ">="
    assert alertas.normalizar_op("baja") == "<="
    assert alertas.normalizar_op("<") == "<="


def test_normalizar_op_invalida():
    with pytest.raises(ValueError):
        alertas.normalizar_op("de lado")


# --------------------------- Alta / baja ---------------------------

def test_agregar_y_listar():
    a = alertas.agregar("ES 12-25", "sube", 5000)
    assert a["instrument"] == "ES 12-25" and a["op"] == ">=" and a["precio"] == 5000.0
    assert len(alertas.cargar()) == 1


def test_agregar_precio_invalido():
    with pytest.raises(ValueError):
        alertas.agregar("ES", ">=", "carisimo")


def test_eliminar():
    a = alertas.agregar("MNQ", "baja", 21000)
    assert "eliminada" in alertas.eliminar(a["id"]).lower()
    assert alertas.cargar() == []


# --------------------------- Evaluacion ---------------------------

def test_evaluar_dispara(monkeypatch):
    alertas.agregar("ES 12-25", "sube", 5000)
    monkeypatch.setattr(nt, "leer_precio", lambda *a, **k: "5012.25")
    disp = alertas.evaluar()
    assert len(disp) == 1 and disp[0]["actual"] == 5012.25
    # ya quedo marcada como disparada: no vuelve a disparar
    assert alertas.evaluar() == []


def test_evaluar_no_dispara_si_no_se_cumple(monkeypatch):
    alertas.agregar("ES", "sube", 5000)
    monkeypatch.setattr(nt, "leer_precio", lambda *a, **k: "4990")
    assert alertas.evaluar() == []


def test_evaluar_sin_precio_no_rompe(monkeypatch):
    alertas.agregar("ES", "sube", 5000)
    def sin_precio(*a, **k):
        raise FileNotFoundError("sin datos")
    monkeypatch.setattr(nt, "leer_precio", sin_precio)
    assert alertas.evaluar() == []          # no lanza
    assert alertas.cargar()[0]["disparada"] is False


# --------------------------- Herramienta y registro ---------------------------

def test_tool_crear_listar_eliminar(monkeypatch):
    out = alertas.tool_alerta_precio({"instrument": "ES 12-25", "condicion": "sube", "precio": 5000})
    assert "creada" in out.lower()
    assert "ES 12-25" in alertas.tool_alerta_precio({"accion": "listar"})
    ide = alertas.cargar()[0]["id"]
    assert "eliminada" in alertas.tool_alerta_precio({"accion": "eliminar", "ref": ide}).lower()


def test_alertas_registradas_en_nexus():
    assert "alerta_precio" in nexus.EJECUTORES
    assert {"alerta_precio"} <= {t.get("name") for t in nexus.TOOLS}
    assert "alerta_precio" not in nexus.HERRAMIENTAS_PELIGROSAS


# --------------------------- Endpoints web ---------------------------

def test_api_alertas(monkeypatch):
    import nexus_web
    alertas.agregar("ES", "sube", 5000)
    monkeypatch.setattr(nt, "leer_precio", lambda *a, **k: "4000")  # no dispara
    c = nexus_web.app.test_client()
    r = c.get("/api/alertas")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["alertas"]) == 1 and data["disparadas"] == []


def test_api_crear_y_eliminar_alerta():
    import nexus_web
    c = nexus_web.app.test_client()
    r = c.post("/api/alerta", json={"instrument": "MNQ", "condicion": "baja", "precio": 21000})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    ide = alertas.cargar()[0]["id"]
    r2 = c.post("/api/alerta/eliminar", json={"ref": ide})
    assert r2.get_json()["ok"] is True
