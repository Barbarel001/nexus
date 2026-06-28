#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Control de gastos personales para NEXUS.

Registra gastos (monto, categoria, descripcion, fecha) y da resumenes por mes y
categoria. Persiste en gastos.json (git-ignored) con escritura atomica.

Configuracion:
    NEXUS_GASTOS_PATH   Ruta del archivo de gastos.
    NEXUS_MONEDA        Simbolo de moneda para mostrar (defecto '$').
"""

import os
import uuid
import datetime

import nexus_util
import nexus_ctx

_CARPETA = os.path.dirname(os.path.abspath(__file__))
GASTOS_PATH = os.environ.get("NEXUS_GASTOS_PATH") or os.path.join(_CARPETA, "gastos.json")
MONEDA = os.environ.get("NEXUS_MONEDA") or "$"


def cargar() -> list:
    return (nexus_util.cargar_json(nexus_ctx.user_path(GASTOS_PATH), {"gastos": []}) or {}).get("gastos", [])


def guardar(gastos: list) -> None:
    nexus_util.guardar_json(nexus_ctx.user_path(GASTOS_PATH), {"gastos": gastos})


def _monto(v) -> float:
    try:
        return round(float(str(v).replace(",", ".").replace(MONEDA, "").strip()), 2)
    except (TypeError, ValueError):
        raise ValueError(f"Monto invalido: '{v}'.")


def agregar(monto, categoria: str = "general", descripcion: str = "", fecha: str = "") -> dict:
    m = _monto(monto)
    if m <= 0:
        raise ValueError("El monto debe ser mayor que 0.")
    f = (fecha or "").strip() or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(f)
    except ValueError:
        f = datetime.date.today().isoformat()
    gasto = {
        "id": uuid.uuid4().hex[:6],
        "monto": m,
        "categoria": (categoria or "general").strip().lower(),
        "descripcion": (descripcion or "").strip(),
        "fecha": f,
    }
    gastos = cargar()
    gastos.append(gasto)
    guardar(gastos)
    return gasto


def _mes_actual() -> str:
    return datetime.date.today().strftime("%Y-%m")


def listar(mes: str = "") -> list:
    """Gastos del mes dado (YYYY-MM); vacio = mes actual."""
    mes = (mes or "").strip() or _mes_actual()
    return [g for g in cargar() if str(g.get("fecha", "")).startswith(mes)]


def resumen(mes: str = "") -> dict:
    """Total y desglose por categoria de un mes."""
    mes = (mes or "").strip() or _mes_actual()
    gastos = listar(mes)
    total = round(sum(g["monto"] for g in gastos), 2)
    por_cat = {}
    for g in gastos:
        por_cat[g["categoria"]] = round(por_cat.get(g["categoria"], 0) + g["monto"], 2)
    return {"mes": mes, "total": total, "n": len(gastos), "por_categoria": por_cat}


def eliminar(ref: str) -> str:
    ref = (ref or "").strip().lower()
    gastos = cargar()
    coincide = [g for g in gastos if g["id"].lower().startswith(ref)] or \
               [g for g in gastos if ref in g["descripcion"].lower()]
    if not coincide:
        return f"No encontre ningun gasto que coincida con '{ref}'."
    if len(coincide) > 1:
        ids = ", ".join(f"{g['id']} ({g['descripcion'][:20]})" for g in coincide[:5])
        return f"Hay varios gastos que coinciden. Precisa el id: {ids}"
    obj = coincide[0]
    guardar([g for g in gastos if g["id"] != obj["id"]])
    return f"Gasto eliminado: {MONEDA}{obj['monto']} ({obj['categoria']})"


# ============================================================
#  HERRAMIENTAS  (SEGURAS)
# ============================================================

def tool_agregar_gasto(args: dict) -> str:
    try:
        g = agregar(args.get("monto"), args.get("categoria", "general"),
                    args.get("descripcion", ""), args.get("fecha", ""))
    except ValueError as e:
        return f"No pude registrar el gasto: {e}"
    desc = f" — {g['descripcion']}" if g["descripcion"] else ""
    return f"Gasto registrado [{g['id']}]: {MONEDA}{g['monto']} en {g['categoria']}{desc} ({g['fecha']})"


def tool_resumen_gastos(args: dict) -> str:
    r = resumen(args.get("mes", ""))
    if not r["n"]:
        return f"No hay gastos registrados en {r['mes']}."
    lineas = [f"💸 Gastos de {r['mes']}: {MONEDA}{r['total']} en {r['n']} movimientos"]
    for cat, monto in sorted(r["por_categoria"].items(), key=lambda x: x[1], reverse=True):
        lineas.append(f"  • {cat}: {MONEDA}{monto}")
    return "\n".join(lineas)


def tool_eliminar_gasto(args: dict) -> str:
    return eliminar(args.get("ref", ""))


GASTOS_TOOLS = [
    {
        "name": "agregar_gasto",
        "description": ("Registra un gasto personal. 'monto' (numero), 'categoria' (ej. comida, "
                        "transporte, ocio), 'descripcion' opcional y 'fecha' opcional (AAAA-MM-DD)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "monto": {"type": "number", "description": "Importe del gasto."},
                "categoria": {"type": "string", "description": "Categoria (comida, transporte, etc.)."},
                "descripcion": {"type": "string", "description": "Detalle opcional."},
                "fecha": {"type": "string", "description": "Fecha opcional AAAA-MM-DD (defecto hoy)."},
            },
            "required": ["monto"],
        },
    },
    {
        "name": "resumen_gastos",
        "description": "Resumen de gastos de un mes (total y por categoria). 'mes' opcional (AAAA-MM).",
        "input_schema": {
            "type": "object",
            "properties": {"mes": {"type": "string", "description": "Mes AAAA-MM (defecto el actual)."}},
            "required": [],
        },
    },
    {
        "name": "eliminar_gasto",
        "description": "Elimina un gasto por su id o por parte de su descripcion.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Id del gasto o parte de su descripcion."}},
            "required": ["ref"],
        },
    },
]

GASTOS_SEGURAS = {"agregar_gasto", "resumen_gastos", "eliminar_gasto"}
GASTOS_EJECUTORES = {
    "agregar_gasto": tool_agregar_gasto,
    "resumen_gastos": tool_resumen_gastos,
    "eliminar_gasto": tool_eliminar_gasto,
}
