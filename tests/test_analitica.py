# -*- coding: utf-8 -*-
"""Tests de la analitica de trading: estadisticas, equity, drawdown y riesgo."""

import math

import pytest

import nexus_analitica as A
import nexus_ctx


@pytest.fixture(autouse=True)
def _ops_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "OPS_PATH", str(tmp_path / "ops.json"))
    nexus_ctx.clear_user()
    yield
    nexus_ctx.clear_user()


def _sembrar(pnls):
    for i, p in enumerate(pnls):
        A.registrar("MNQ", p, fecha=f"2026-01-{i+1:02d}")


# --------------------------- Registro ---------------------------

def test_registrar_y_cargar():
    o = A.registrar("mnq", 125.5, lado="long", qty=2, entrada=21000, salida=21050)
    assert o["instrument"] == "MNQ" and o["pnl"] == 125.5 and o["lado"] == "long"
    assert len(A.cargar()) == 1


def test_registrar_exige_instrumento_y_pnl():
    with pytest.raises(ValueError):
        A.registrar("", 10)
    with pytest.raises(ValueError):
        A.registrar("ES", None)


# --------------------------- Estadisticas ---------------------------

def test_estadisticas_basicas():
    _sembrar([100, -50, 200, -30])
    s = A.estadisticas()
    assert s["n"] == 4
    assert s["ganadoras"] == 2 and s["perdedoras"] == 2
    assert s["win_rate"] == 50.0
    assert s["pnl_total"] == 220
    assert s["bruto_ganado"] == 300 and s["bruto_perdido"] == -80
    assert s["profit_factor"] == 3.75
    assert s["avg_win"] == 150 and s["avg_loss"] == -40
    assert s["expectancy"] == 55
    assert s["mejor"] == 200 and s["peor"] == -50


def test_profit_factor_infinito_sin_perdidas():
    _sembrar([10, 20, 30])
    assert A.estadisticas()["profit_factor"] == math.inf


def test_equity_y_drawdown():
    _sembrar([100, -50, 200, -30])
    assert A.curva_equity() == [100, 50, 250, 220]
    assert A.max_drawdown() == -50


def test_racha_actual():
    _sembrar([100, -50, -20, -10])     # termina en 3 perdedoras seguidas
    assert A.estadisticas()["racha"] == -3
    _sembrar([])                        # sin nada nuevo
    A.registrar("MNQ", 5, fecha="2026-02-01")  # ahora 1 ganadora al final
    assert A.estadisticas()["racha"] == 1


def test_por_instrumento():
    A.registrar("ES", 100)
    A.registrar("NQ", -40)
    A.registrar("ES", 25)
    assert A.estadisticas()["por_instrumento"] == {"ES": 125.0, "NQ": -40.0}


def test_stats_vacio():
    assert A.estadisticas() == {"n": 0}


# --------------------------- Filtros ---------------------------

def test_filtrar_por_instrumento_y_fecha():
    A.registrar("ES", 100, fecha="2026-01-05")
    A.registrar("NQ", -40, fecha="2026-01-10")
    A.registrar("ES", 25, fecha="2026-02-01")
    assert len(A.filtrar(instrument="ES")) == 2
    assert len(A.filtrar(desde="2026-01-08", hasta="2026-01-31")) == 1
    assert A.filtrar(instrument="ES", desde="2026-01-20")[0]["fecha"] == "2026-02-01"
    assert A.instrumentos() == ["ES", "NQ"]


def test_estadisticas_sobre_filtrado():
    A.registrar("ES", 100)
    A.registrar("NQ", -40)
    s = A.estadisticas(A.filtrar(instrument="ES"))
    assert s["n"] == 1 and s["pnl_total"] == 100


# --------------------------- Detalle (R, notas, lado) ---------------------------

def test_registrar_con_detalle():
    o = A.registrar("MNQ", 200, lado="long", entrada=21000, salida=21100, r=2, notas="buena entrada")
    assert o["r"] == 2.0 and o["entrada"] == 21000 and o["notas"] == "buena entrada"


def test_avg_r():
    A.registrar("ES", 100, r=2)
    A.registrar("ES", -50, r=-1)
    A.registrar("ES", 30)            # sin R: no cuenta para la media
    assert A.estadisticas()["avg_r"] == 0.5     # (2 + -1) / 2


def test_avg_r_none_sin_datos():
    A.registrar("ES", 100)
    assert A.estadisticas()["avg_r"] is None


# --------------------------- Tamano de posicion ---------------------------

def test_tamano_posicion_acciones():
    r = A.tamano_posicion(10000, 1, 100, 95, 1)   # riesgo 100$, 5 puntos
    assert r["contratos"] == 20 and r["riesgo_real"] == 100.0


def test_tamano_posicion_futuro_es():
    r = A.tamano_posicion(10000, 1, 5000, 4990, 50)  # riesgo/contrato=500 > 100
    assert r["contratos"] == 0


def test_tamano_posicion_errores():
    with pytest.raises(ValueError):
        A.tamano_posicion(0, 1, 100, 95)
    with pytest.raises(ValueError):
        A.tamano_posicion(10000, 1, 100, 100)   # entrada == stop


# --------------------------- Integracion web ---------------------------

def test_trades_web(monkeypatch, tmp_path):
    import nexus_web
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(A, "OPS_PATH", str(tmp_path / "ops_web.json"))
    c = nexus_web.app.test_client()
    assert c.post("/api/trade", json={"instrument": "MNQ", "pnl": 50}).get_json()["ok"]
    assert c.post("/api/trade", json={"instrument": "MNQ", "pnl": -20}).get_json()["ok"]
    data = c.get("/api/trades/stats").get_json()
    assert data["stats"]["n"] == 2 and data["equity"] == [50, 30]
    # calculadora de riesgo
    r = c.get("/api/riesgo?saldo=10000&riesgo_pct=1&entrada=100&stop=95").get_json()
    assert r["ok"] and r["resultado"]["contratos"] == 20


def test_trades_listar_y_eliminar_web(monkeypatch, tmp_path):
    import nexus_web
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(A, "OPS_PATH", str(tmp_path / "ops_le.json"))
    c = nexus_web.app.test_client()
    c.post("/api/trade", json={"instrument": "ES", "pnl": 100})
    c.post("/api/trade", json={"instrument": "NQ", "pnl": -30})
    ops = c.get("/api/trades?n=5").get_json()["ops"]
    assert len(ops) == 2 and ops[0]["instrument"] == "NQ"   # más reciente primero
    r = c.post("/api/trade/eliminar", json={"ref": ops[0]["id"]}).get_json()
    assert r["ok"] is True
    assert len(c.get("/api/trades").get_json()["ops"]) == 1


def test_trades_filtro_web(monkeypatch, tmp_path):
    import nexus_web
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(A, "OPS_PATH", str(tmp_path / "ops_f.json"))
    c = nexus_web.app.test_client()
    c.post("/api/trade", json={"instrument": "ES", "pnl": 100})
    c.post("/api/trade", json={"instrument": "NQ", "pnl": -40})
    d = c.get("/api/trades/stats?instrument=ES").get_json()
    assert d["stats"]["n"] == 1 and d["stats"]["pnl_total"] == 100
    assert set(d["instrumentos"]) == {"ES", "NQ"}
    assert len(c.get("/api/trades?instrument=NQ").get_json()["ops"]) == 1
