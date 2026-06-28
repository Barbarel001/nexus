#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alertas de precio para NEXUS: "avisame si el ES toca 5000".

Persiste en  alertas.json  (git-ignored, personal). Cuando se evaluan, consultan
el precio actual via el puente de NinjaTrader (nexus_ninjatrader). Como Nexus no
es un servicio en segundo plano, las alertas se comprueban:
  - cuando el usuario lo pide (herramienta), y
  - periodicamente desde el panel web (endpoint /api/alertas), que ademas lanza
    una notificacion del navegador cuando una alerta se dispara.

Una alerta es un dict:
    {id, instrument, op (">=" | "<="), precio (float), creada, disparada (bool)}

Configurable:
    NEXUS_ALERTAS_PATH   Ruta del archivo de alertas.
"""

import os
import json
import uuid
import datetime

import nexus_util
import nexus_ctx
import nexus_ninjatrader as nt

_CARPETA = os.path.dirname(os.path.abspath(__file__))
ALERTAS_PATH = os.environ.get("NEXUS_ALERTAS_PATH") or os.path.join(_CARPETA, "alertas.json")


# --------------------------- Persistencia ---------------------------

def cargar() -> list:
    return (nexus_util.cargar_json(nexus_ctx.user_path(ALERTAS_PATH), {"alertas": []}) or {}).get("alertas", [])


def guardar(alertas: list) -> None:
    nexus_util.guardar_json(nexus_ctx.user_path(ALERTAS_PATH), {"alertas": alertas})


# --------------------------- Normalizacion ---------------------------

def normalizar_op(texto: str) -> str:
    """Convierte una condicion en '>=' o '<='. Acepta >=,>,<=,<, 'sube/arriba/mayor',
    'baja/abajo/menor', 'toca' (>=)."""
    t = (texto or "").strip().lower()
    if t in (">=", ">", "sube", "arriba", "mayor", "supera", "toca", "alcanza", "por encima"):
        return ">="
    if t in ("<=", "<", "baja", "abajo", "menor", "cae", "por debajo"):
        return "<="
    raise ValueError(f"Condicion invalida: '{texto}'. Usa '>=' (sube/toca) o '<=' (baja).")


def _precio_float(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"Precio invalido: '{v}'.")


# --------------------------- Operaciones ---------------------------

def agregar(instrument: str, condicion: str, precio) -> dict:
    instrument = (instrument or "").strip().upper()
    if not instrument:
        raise ValueError("Falta el instrumento de la alerta.")
    op = normalizar_op(condicion)
    objetivo = _precio_float(precio)
    alerta = {
        "id": uuid.uuid4().hex[:6],
        "instrument": instrument,
        "op": op,
        "precio": objetivo,
        "creada": datetime.date.today().isoformat(),
        "disparada": False,
    }
    alertas = cargar()
    alertas.append(alerta)
    guardar(alertas)
    return alerta


def _coincidencias(ref: str, alertas: list) -> list:
    ref = (ref or "").strip().lower()
    if not ref:
        return []
    por_id = [a for a in alertas if a["id"].lower() == ref or a["id"].lower().startswith(ref)]
    if por_id:
        return por_id
    return [a for a in alertas if ref in a["instrument"].lower()]


def eliminar(ref: str) -> str:
    alertas = cargar()
    matches = _coincidencias(ref, alertas)
    if not matches:
        return f"No encontre ninguna alerta que coincida con '{ref}'."
    if len(matches) > 1:
        ids = ", ".join(f"{a['id']} ({a['instrument']})" for a in matches[:5])
        return f"Hay varias alertas que coinciden. Precisa el id: {ids}"
    objetivo = matches[0]
    guardar([a for a in alertas if a["id"] != objetivo["id"]])
    return f"Alerta eliminada: {objetivo['instrument']} {objetivo['op']} {objetivo['precio']}"


def _se_cumple(op: str, actual: float, objetivo: float) -> bool:
    return actual >= objetivo if op == ">=" else actual <= objetivo


def evaluar(persistir: bool = True) -> list:
    """Comprueba las alertas activas contra el precio actual. Marca como disparadas
    las que se cumplen y devuelve la lista de alertas DISPARADAS en esta evaluacion
    (con el precio actual en 'actual'). Si NinjaTrader no da precio, la deja activa."""
    alertas = cargar()
    disparadas = []
    cambio = False
    for a in alertas:
        if a.get("disparada"):
            continue
        try:
            actual = float(nt.leer_precio(a["instrument"], "LAST", espera=1.0).replace(",", ""))
        except Exception:
            continue  # sin precio: no se evalua esta vez
        if _se_cumple(a["op"], actual, a["precio"]):
            a["disparada"] = True
            cambio = True
            disparadas.append({**a, "actual": actual})
    if cambio and persistir:
        guardar(alertas)
    return disparadas


# --------------------------- Formato / DTO ---------------------------

def dto(a: dict) -> dict:
    return {"id": a["id"], "instrument": a["instrument"], "op": a["op"],
            "precio": a["precio"], "disparada": bool(a.get("disparada"))}


def _linea(a: dict) -> str:
    estado = "DISPARADA" if a.get("disparada") else "activa"
    return f"[{a['id']}] {a['instrument']} {a['op']} {a['precio']}  ({estado})"


# ============================================================
#  HERRAMIENTA  (lo que Claude "ve")  -- SEGURA
# ============================================================

def tool_alerta_precio(args: dict) -> str:
    accion = (args.get("accion") or "crear").strip().lower()
    if accion in ("listar", "ver", "lista"):
        alertas = cargar()
        if not alertas:
            return "No tienes alertas de precio configuradas."
        return "Alertas de precio:\n" + "\n".join(_linea(a) for a in alertas)
    if accion in ("eliminar", "borrar", "quitar"):
        return eliminar(args.get("ref", "") or args.get("instrument", ""))
    if accion in ("evaluar", "comprobar", "revisar"):
        disp = evaluar()
        if not disp:
            return "Ninguna alerta se ha disparado por ahora."
        return "Se dispararon: " + "; ".join(
            f"{d['instrument']} {d['op']} {d['precio']} (actual {d['actual']})" for d in disp)
    # crear (por defecto)
    try:
        a = agregar(args.get("instrument", ""), args.get("condicion", ">="), args.get("precio"))
    except ValueError as e:
        return f"No pude crear la alerta: {e}"
    return f"Alerta creada [{a['id']}]: {a['instrument']} {a['op']} {a['precio']}"


ALERTAS_TOOLS = [
    {
        "name": "alerta_precio",
        "description": ("Gestiona alertas de precio sobre instrumentos de NinjaTrader. "
                        "accion: 'crear' (defecto), 'listar', 'eliminar' o 'evaluar'. Para crear: "
                        "instrument, condicion ('>=' o sube / '<=' o baja) y precio."),
        "input_schema": {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "description": "crear (defecto), listar, eliminar o evaluar."},
                "instrument": {"type": "string", "description": "Instrumento, ej. 'ES 12-25'."},
                "condicion": {"type": "string", "description": "'>=' / 'sube' / 'toca'  o  '<=' / 'baja'."},
                "precio": {"type": "number", "description": "Precio objetivo de la alerta."},
                "ref": {"type": "string", "description": "Para eliminar: id o instrumento de la alerta."},
            },
            "required": [],
        },
    },
]

ALERTAS_SEGURAS = {"alerta_precio"}
ALERTAS_EJECUTORES = {"alerta_precio": tool_alerta_precio}
