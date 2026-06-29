#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clima para NEXUS usando Open-Meteo (gratis y SIN API key).

Geocodifica una ciudad y devuelve el tiempo actual y el pronostico del dia.
Se usa como herramienta del agente y, opcionalmente, en el resumen matutino.

Configuracion:
    NEXUS_CIUDAD   Ciudad por defecto (para el resumen matutino y cuando no se indica).
"""

import json
import os
import urllib.parse
import urllib.request

CIUDAD_DEFECTO = os.environ.get("NEXUS_CIUDAD") or ""
_HEADERS = {"User-Agent": "Mozilla/5.0 (NEXUS-clima)"}

# Codigos de tiempo de Open-Meteo -> descripcion en espanol (resumido).
_CODIGOS = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha", 51: "llovizna ligera", 53: "llovizna",
    55: "llovizna intensa", 61: "lluvia ligera", 63: "lluvia", 65: "lluvia fuerte",
    71: "nieve ligera", 73: "nieve", 75: "nieve fuerte", 80: "chubascos",
    81: "chubascos", 82: "chubascos fuertes", 95: "tormenta", 96: "tormenta con granizo",
    99: "tormenta fuerte con granizo",
}


def _get(url: str):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def geocodificar(ciudad: str):
    """Devuelve (nombre, lat, lon) de una ciudad, o None si no se encuentra."""
    q = urllib.parse.urlencode({"name": ciudad, "count": 1, "language": "es"})
    data = _get("https://geocoding-api.open-meteo.com/v1/search?" + q)
    res = (data.get("results") or [])
    if not res:
        return None
    r = res[0]
    nombre = r.get("name", ciudad)
    if r.get("country"):
        nombre += f", {r['country']}"
    return nombre, r["latitude"], r["longitude"]


def obtener(ciudad: str = "") -> dict:
    """Tiempo actual + maxima/minima del dia para una ciudad. Lanza si falla."""
    ciudad = (ciudad or CIUDAD_DEFECTO or "").strip()
    if not ciudad:
        raise ValueError("Indica una ciudad (o define NEXUS_CIUDAD).")
    geo = geocodificar(ciudad)
    if not geo:
        raise ValueError(f"No encontre la ciudad '{ciudad}'.")
    nombre, lat, lon = geo
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    })
    data = _get("https://api.open-meteo.com/v1/forecast?" + q)
    actual = data.get("current", {})
    diario = data.get("daily", {})
    codigo = actual.get("weather_code")
    return {
        "ciudad": nombre,
        "temp": actual.get("temperature_2m"),
        "desc": _CODIGOS.get(codigo, "—"),
        "max": (diario.get("temperature_2m_max") or [None])[0],
        "min": (diario.get("temperature_2m_min") or [None])[0],
    }


def texto(ciudad: str = "") -> str:
    """Resumen del clima en una linea (para el briefing)."""
    try:
        c = obtener(ciudad)
    except Exception:
        return ""
    return f"{c['ciudad']}: {c['temp']}°C, {c['desc']} (max {c['max']}° / min {c['min']}°)"


# ============================================================
#  HERRAMIENTA  (SEGURA)
# ============================================================

def tool_clima(args: dict) -> str:
    try:
        c = obtener(args.get("ciudad", ""))
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"No pude obtener el clima: {e}"
    return (f"🌤️ {c['ciudad']}: {c['temp']}°C, {c['desc']}. "
            f"Hoy max {c['max']}° / min {c['min']}°.")


CLIMA_TOOLS = [
    {
        "name": "clima",
        "description": "Consulta el clima actual y el pronostico del dia de una ciudad (gratis, Open-Meteo).",
        "input_schema": {
            "type": "object",
            "properties": {"ciudad": {"type": "string", "description": "Ciudad (ej. 'Madrid'). Si no, usa la de por defecto."}},
            "required": [],
        },
    },
]

CLIMA_SEGURAS = {"clima"}
CLIMA_EJECUTORES = {"clima": tool_clima}
