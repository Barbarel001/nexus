# -*- coding: utf-8 -*-
"""Tests del onboarding de negocios (CLI del recepcionista). Sin red."""

import json

import pytest

import nexus_db
import nexus_recepcion_panel as panel
import nexus_recepcion_saas as saas
import onboarding_recepcion as onb


@pytest.fixture(autouse=True)
def _db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "onb.db"))
    saas._HITS.clear()
    saas.init()
    panel.init()


def _config(**extra):
    base = {
        "slug": "aurora", "nombre": "Limpiezas Aurora", "sector": "limpieza",
        "servicios": [{"nombre": "limpieza de casa", "base": 80, "por_unidad": 20,
                       "unidad": "habitacion", "unidades_incluidas": 1}],
        "faq": [{"pregunta": "horario", "respuesta": "9 a 18h"}],
    }
    base.update(extra)
    return base


def test_onboard_crea_negocio_con_tarifas_faq_y_password():
    r = onb.onboard(_config(password="clave123"))
    assert r["slug"] == "aurora" and r["servicios"] == 1 and r["faq"] == 1 and r["panel"] is True
    n = saas.obtener_negocio("aurora")
    assert n["sector"] == "limpieza"
    assert panel.verificar_password("aurora", "clave123") is True
    # El precio sale de la tarifa aprobada (3 habitaciones = 80 + 2*20).
    import nexus_recepcionista as recep
    assert recep.estimar_precio_en(n, "limpieza de casa", 3)["desde"] == 120


def test_onboard_es_idempotente():
    onb.onboard(_config())
    onb.onboard(_config())  # segunda vez no duplica
    n = saas.obtener_negocio("aurora")
    assert len(n["servicios"]) == 1 and len(n["faq"]) == 1


def test_onboard_slug_derivado_del_nombre():
    r = onb.onboard({"nombre": "Bar Pepe", "servicios": [], "faq": []})
    assert r["slug"] == "bar-pepe"


def test_onboard_sin_nombre_falla():
    with pytest.raises(ValueError):
        onb.onboard({"slug": "x", "servicios": [], "faq": []})


def test_onboard_servicio_invalido_falla():
    with pytest.raises(ValueError):
        onb.onboard(_config(servicios=[{"nombre": "sin base"}]))


def test_cli_desde_archivo(tmp_path, capsys):
    ruta = tmp_path / "negocio.json"
    ruta.write_text(json.dumps(_config(password="clave123")), encoding="utf-8")
    codigo = onb.main(["--archivo", str(ruta)])
    assert codigo == 0
    salida = capsys.readouterr().out
    assert "/r/aurora" in salida and "/panel/aurora" in salida
    assert saas.obtener_negocio("aurora") is not None


def test_cli_flag_sobreescribe_archivo(tmp_path):
    ruta = tmp_path / "negocio.json"
    ruta.write_text(json.dumps(_config()), encoding="utf-8")
    onb.main(["--archivo", str(ruta), "--password", "otra-clave"])
    assert panel.verificar_password("aurora", "otra-clave") is True


def test_cli_sin_datos_error():
    with pytest.raises(SystemExit):
        onb.main([])  # argparse.error -> SystemExit
