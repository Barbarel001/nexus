# -*- coding: utf-8 -*-
"""Tests de clima (Open-Meteo simulado), Discord (sin red) y respaldos."""

import json
import os

import nexus
import nexus_clima as clima
import nexus_discord as discord
import nexus_util

# --------------------------- Clima ---------------------------

class _Resp:
    def __init__(self, data):
        self._d = json.dumps(data).encode("utf-8")
    def read(self): return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_clima_obtener(monkeypatch):
    geo = {"results": [{"name": "Madrid", "country": "España", "latitude": 40.4, "longitude": -3.7}]}
    fc = {"current": {"temperature_2m": 22.5, "weather_code": 0},
          "daily": {"temperature_2m_max": [28], "temperature_2m_min": [15]}}
    def fake(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        return _Resp(geo if "geocoding" in url else fc)
    monkeypatch.setattr(clima.urllib.request, "urlopen", fake)
    c = clima.obtener("Madrid")
    assert c["ciudad"].startswith("Madrid") and c["temp"] == 22.5
    assert c["desc"] == "despejado" and c["max"] == 28
    assert "Madrid" in clima.tool_clima({"ciudad": "Madrid"})


def test_clima_ciudad_no_encontrada(monkeypatch):
    monkeypatch.setattr(clima.urllib.request, "urlopen", lambda *a, **k: _Resp({"results": []}))
    assert "No encontre" in clima.tool_clima({"ciudad": "Xyzzz"})


def test_clima_sin_ciudad(monkeypatch):
    monkeypatch.setattr(clima, "CIUDAD_DEFECTO", "")
    assert "Indica una ciudad" in clima.tool_clima({})


def test_clima_registrada():
    assert "clima" in nexus.EJECUTORES
    assert "clima" in {t.get("name") for t in nexus.TOOLS}


# --------------------------- Discord ---------------------------

def test_discord_sin_webhook(monkeypatch):
    monkeypatch.setattr(discord, "WEBHOOK", "")
    assert discord.configurado() is False
    assert discord.enviar("hola") is False


def test_discord_envia(monkeypatch):
    monkeypatch.setattr(discord, "WEBHOOK", "http://webhook")
    enviados = []
    class _R:
        def read(self): return b""
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(req, timeout=0):
        enviados.append(json.loads(req.data.decode()))
        return _R()
    monkeypatch.setattr(discord.urllib.request, "urlopen", fake)
    assert discord.enviar("mensaje de prueba") is True
    assert enviados[0]["content"] == "mensaje de prueba"


# --------------------------- Respaldos ---------------------------

def test_respaldar_copia_y_limpia(tmp_path):
    # crea 3 archivos de datos
    a = tmp_path / "memoria.json"
    a.write_text("{}", encoding="utf-8")
    b = tmp_path / "tareas.json"
    b.write_text("{}", encoding="utf-8")
    dest = tmp_path / "backups"
    n = nexus_util.respaldar([str(a), str(b), str(tmp_path / "no_existe.json")], str(dest))
    assert n == 2
    # se creo una carpeta de fecha con los 2 archivos
    fechas = os.listdir(dest)
    assert len(fechas) == 1
    assert set(os.listdir(dest / fechas[0])) == {"memoria.json", "tareas.json"}


def test_respaldar_conserva_solo_keep(tmp_path):
    a = tmp_path / "d.json"
    a.write_text("{}", encoding="utf-8")
    dest = tmp_path / "bk"
    # simula respaldos viejos
    for fecha in ["2026-01-01", "2026-01-02", "2026-01-03"]:
        os.makedirs(dest / fecha)
    nexus_util.respaldar([str(a)], str(dest), keep=2)
    # se conservan como mucho 2 carpetas (las mas recientes + la de hoy puede recortar)
    assert len(os.listdir(dest)) <= 2
