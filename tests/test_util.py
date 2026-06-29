# -*- coding: utf-8 -*-
"""Tests de las utilidades base: escritura atomica de JSON, lectura tolerante y log."""

import os

import nexus_util


def test_guardar_y_cargar_json(tmp_path):
    p = str(tmp_path / "datos.json")
    nexus_util.guardar_json(p, {"a": 1, "ñ": "áéí"})
    assert nexus_util.cargar_json(p) == {"a": 1, "ñ": "áéí"}


def test_cargar_json_inexistente_devuelve_defecto(tmp_path):
    assert nexus_util.cargar_json(str(tmp_path / "no.json"), defecto=[]) == []


def test_cargar_json_corrupto_devuelve_defecto(tmp_path):
    p = tmp_path / "roto.json"
    p.write_text("{no es json", encoding="utf-8")
    assert nexus_util.cargar_json(str(p), defecto={"ok": False}) == {"ok": False}


def test_guardar_json_no_deja_temporales(tmp_path):
    p = str(tmp_path / "x.json")
    nexus_util.guardar_json(p, {"k": "v"})
    sobrantes = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert sobrantes == []  # el temporal se renombro, no quedo basura


def test_guardar_json_crea_carpeta(tmp_path):
    p = str(tmp_path / "sub" / "dir" / "d.json")
    nexus_util.guardar_json(p, {"ok": True})
    assert nexus_util.cargar_json(p) == {"ok": True}


def test_guardar_json_es_atomico_sobreescribe(tmp_path):
    """Reescribir varias veces deja siempre un JSON valido y completo."""
    p = str(tmp_path / "d.json")
    for i in range(5):
        nexus_util.guardar_json(p, {"n": i})
    assert nexus_util.cargar_json(p) == {"n": 4}


def test_log_escribe(tmp_path, monkeypatch):
    log = tmp_path / "nexus.log"
    monkeypatch.setattr(nexus_util, "LOG_PATH", str(log))
    nexus_util.log("hola", "INFO")
    nexus_util.log("ups", "ERROR")
    contenido = log.read_text(encoding="utf-8")
    assert "hola" in contenido and "[ERROR]" in contenido


def test_log_nunca_lanza(monkeypatch):
    monkeypatch.setattr(nexus_util, "LOG_PATH", "/ruta/imposible/x/y/z.log")
    nexus_util.log("no debe lanzar")  # simplemente no revienta
