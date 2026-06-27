# -*- coding: utf-8 -*-
"""Tests de noticias de mercado (RSS simulado) y control de gastos."""

import datetime

import pytest

import nexus
import nexus_noticias as noticias
import nexus_gastos as gastos


# --------------------------- Noticias (RSS) ---------------------------

_RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>El S&amp;P sube un 1%</title><link>http://x/1</link></item>
<item><title>La Fed mantiene tipos</title><link>http://x/2</link></item>
</channel></rss>"""


def test_parse_feed():
    items = noticias._parse_feed(_RSS)
    assert len(items) == 2 and items[0]["titulo"].startswith("El S&P")


def test_obtener_dedup(monkeypatch):
    class _R:
        def read(self): return _RSS
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(noticias.urllib.request, "urlopen", lambda *a, **k: _R())
    out = noticias.obtener(n=5, feeds=["http://a", "http://b"])
    assert len(out) == 2  # deduplicado entre fuentes


def test_obtener_fuente_caida(monkeypatch):
    def boom(*a, **k):
        raise OSError("sin red")
    monkeypatch.setattr(noticias.urllib.request, "urlopen", boom)
    assert noticias.obtener(feeds=["http://x"]) == []  # no revienta


def test_tool_noticias_registrada():
    assert "noticias_mercado" in nexus.EJECUTORES
    assert "noticias_mercado" in {t.get("name") for t in nexus.TOOLS}


# --------------------------- Gastos ---------------------------

@pytest.fixture(autouse=True)
def _archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(gastos, "GASTOS_PATH", str(tmp_path / "gastos.json"))


def test_agregar_y_resumen():
    gastos.agregar(12.5, "comida", "almuerzo")
    gastos.agregar("7,80", "transporte")  # acepta coma decimal
    r = gastos.resumen()
    assert r["n"] == 2 and r["total"] == 20.3
    assert r["por_categoria"]["comida"] == 12.5


def test_monto_invalido():
    with pytest.raises(ValueError):
        gastos.agregar("carisimo", "ocio")
    with pytest.raises(ValueError):
        gastos.agregar(0, "ocio")


def test_listar_por_mes():
    gastos.agregar(10, "x", fecha="2026-01-15")
    gastos.agregar(20, "y", fecha="2026-02-15")
    assert len(gastos.listar("2026-01")) == 1
    assert gastos.resumen("2026-02")["total"] == 20


def test_eliminar_gasto():
    g = gastos.agregar(5, "cafe", "starbucks")
    assert "eliminado" in gastos.eliminar(g["id"]).lower()
    assert gastos.cargar() == []


def test_tools_gastos():
    out = gastos.tool_agregar_gasto({"monto": 30, "categoria": "ocio", "descripcion": "cine"})
    assert "registrado" in out.lower()
    assert "ocio" in gastos.tool_resumen_gastos({})
    for n in ("agregar_gasto", "resumen_gastos", "eliminar_gasto"):
        assert n in nexus.EJECUTORES
