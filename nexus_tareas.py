#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Productividad personal para NEXUS: tareas, recordatorios y notas.

Persiste en  tareas.json  (junto a este archivo; git-ignored, es personal),
igual que la memoria. Sin dependencias externas. Las herramientas son SEGURAS
(solo tocan este archivo propio de Nexus), asi que estan disponibles tambien en
la web sin necesidad de confirmacion.

Una "tarea" es un dict:
    {id, texto, hecha, creada, vence, prioridad}
Un recordatorio es simplemente una tarea con fecha de vencimiento ('vence').

Configurable por entorno:
    NEXUS_TAREAS_PATH   Ruta del archivo de tareas (defecto: tareas.json junto a este script).
"""

import os
import json
import uuid
import datetime

CARPETA = os.path.dirname(os.path.abspath(__file__))
TAREAS_PATH = os.environ.get("NEXUS_TAREAS_PATH") or os.path.join(CARPETA, "tareas.json")

PRIORIDADES = {"alta", "media", "baja"}
_MARCA = {"alta": "[!]", "media": "[-]", "baja": "[.]"}


# --------------------------- Persistencia ---------------------------

def cargar() -> list:
    try:
        with open(TAREAS_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("tareas", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def guardar(tareas: list) -> None:
    with open(TAREAS_PATH, "w", encoding="utf-8") as f:
        json.dump({"tareas": tareas}, f, ensure_ascii=False, indent=2)


def _hoy() -> datetime.date:
    return datetime.date.today()


# --------------------------- Utilidades de fecha ---------------------------

def normalizar_fecha(texto: str) -> str:
    """Convierte 'hoy'/'manana'/'mañana' o una fecha ISO (YYYY-MM-DD) a ISO.
    Devuelve "" si no se indico fecha. Lanza ValueError si el formato es invalido."""
    t = (texto or "").strip().lower()
    if not t:
        return ""
    if t in ("hoy", "today"):
        return _hoy().isoformat()
    if t in ("manana", "mañana", "tomorrow"):
        return (_hoy() + datetime.timedelta(days=1)).isoformat()
    try:
        return datetime.date.fromisoformat(t).isoformat()
    except ValueError:
        raise ValueError(f"Fecha invalida: '{texto}'. Usa AAAA-MM-DD, 'hoy' o 'manana'.")


def _vencimiento(t: dict):
    """Devuelve la fecha de vencimiento como date, o None si no tiene/es invalida."""
    v = (t.get("vence") or "").strip()
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(v)
    except ValueError:
        return None


# --------------------------- Operaciones ---------------------------

def agregar(texto: str, vence: str = "", prioridad: str = "media") -> dict:
    """Crea una tarea y la guarda. Devuelve la tarea creada."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("La tarea no puede estar vacia.")
    prioridad = (prioridad or "media").strip().lower()
    if prioridad not in PRIORIDADES:
        prioridad = "media"
    tarea = {
        "id": uuid.uuid4().hex[:6],
        "texto": texto,
        "hecha": False,
        "creada": _hoy().isoformat(),
        "vence": normalizar_fecha(vence),
        "prioridad": prioridad,
    }
    tareas = cargar()
    tareas.append(tarea)
    guardar(tareas)
    return tarea


_ORDEN_PRIO = {"alta": 0, "media": 1, "baja": 2}


def _ordenar(tareas: list) -> list:
    """Ordena por: vencimiento (las que tienen fecha primero, mas proximas antes),
    luego prioridad."""
    return sorted(tareas, key=lambda t: (
        0 if _vencimiento(t) else 1,
        _vencimiento(t) or datetime.date.max,
        _ORDEN_PRIO.get(t.get("prioridad"), 1),
    ))


def filtrar(filtro: str = "pendientes") -> list:
    """Devuelve la lista de tareas segun el filtro: 'pendientes' (defecto), 'todas',
    'hechas', 'hoy' (vencen hoy y pendientes), 'vencidas' (atrasadas y pendientes)."""
    filtro = (filtro or "pendientes").strip().lower()
    tareas = cargar()
    hoy = _hoy()
    if filtro == "todas":
        sel = tareas
    elif filtro == "hechas":
        sel = [t for t in tareas if t.get("hecha")]
    elif filtro == "hoy":
        sel = [t for t in tareas if not t.get("hecha") and _vencimiento(t) == hoy]
    elif filtro == "vencidas":
        sel = [t for t in tareas if not t.get("hecha") and _vencimiento(t) and _vencimiento(t) < hoy]
    else:  # pendientes
        sel = [t for t in tareas if not t.get("hecha")]
    return _ordenar(sel)


def _coincidencias(ref: str, tareas: list) -> list:
    """Tareas que coinciden con `ref` (por id exacto/prefijo, o substring del texto)."""
    ref = (ref or "").strip().lower()
    if not ref:
        return []
    por_id = [t for t in tareas if t["id"].lower() == ref or t["id"].lower().startswith(ref)]
    if por_id:
        return por_id
    return [t for t in tareas if ref in t["texto"].lower()]


def completar(ref: str) -> str:
    tareas = cargar()
    matches = _coincidencias(ref, [t for t in tareas if not t.get("hecha")]) or _coincidencias(ref, tareas)
    if not matches:
        return f"No encontre ninguna tarea que coincida con '{ref}'."
    if len(matches) > 1:
        ids = ", ".join(f"{t['id']} ({t['texto'][:30]})" for t in matches[:5])
        return f"Hay varias tareas que coinciden con '{ref}'. Precisa el id: {ids}"
    objetivo = matches[0]
    for t in tareas:
        if t["id"] == objetivo["id"]:
            t["hecha"] = True
    guardar(tareas)
    return f"Tarea completada: {objetivo['texto']}"


def eliminar(ref: str) -> str:
    tareas = cargar()
    matches = _coincidencias(ref, tareas)
    if not matches:
        return f"No encontre ninguna tarea que coincida con '{ref}'."
    if len(matches) > 1:
        ids = ", ".join(f"{t['id']} ({t['texto'][:30]})" for t in matches[:5])
        return f"Hay varias tareas que coinciden con '{ref}'. Precisa el id: {ids}"
    objetivo = matches[0]
    guardar([t for t in tareas if t["id"] != objetivo["id"]])
    return f"Tarea eliminada: {objetivo['texto']}"


# --------------------------- Formato legible ---------------------------

def _linea(t: dict) -> str:
    estado = "x" if t.get("hecha") else " "
    marca = _MARCA.get(t.get("prioridad"), "[-]")
    cola = ""
    v = _vencimiento(t)
    if v:
        dias = (v - _hoy()).days
        if t.get("hecha"):
            etiqueta = f"vencia {t['vence']}"
        elif dias < 0:
            etiqueta = f"VENCIDA hace {-dias}d ({t['vence']})"
        elif dias == 0:
            etiqueta = "vence HOY"
        elif dias == 1:
            etiqueta = "vence manana"
        else:
            etiqueta = f"vence en {dias}d ({t['vence']})"
        cola = f"  -> {etiqueta}"
    return f"[{estado}] {marca} {t['id']}  {t['texto']}{cola}"


def render(tareas: list, vacio: str = "No hay tareas.") -> str:
    if not tareas:
        return vacio
    return "\n".join(_linea(t) for t in tareas)


def dto(t: dict) -> dict:
    """Representacion de una tarea para la web (incluye etiqueta y severidad de
    vencimiento ya calculadas: 'vencida' / 'hoy' / 'futura' / 'none')."""
    v = _vencimiento(t)
    sev, etiqueta = "none", ""
    if v:
        dias = (v - _hoy()).days
        if t.get("hecha"):
            sev, etiqueta = "hecha", f"vencia {t['vence']}"
        elif dias < 0:
            sev, etiqueta = "vencida", f"vencida ({t['vence']})"
        elif dias == 0:
            sev, etiqueta = "hoy", "vence hoy"
        elif dias == 1:
            sev, etiqueta = "futura", "vence manana"
        else:
            sev, etiqueta = "futura", f"en {dias}d"
    return {"id": t["id"], "texto": t["texto"], "prioridad": t.get("prioridad", "media"),
            "hecha": bool(t.get("hecha")), "vence": t.get("vence", ""),
            "sev": sev, "etiqueta": etiqueta}


def resumen_pendientes() -> str:
    """Resumen corto para mostrar al iniciar: pendientes, vencidas y de hoy."""
    pend = filtrar("pendientes")
    if not pend:
        return ""
    venc = len(filtrar("vencidas"))
    hoy = len(filtrar("hoy"))
    partes = [f"{len(pend)} tareas pendientes"]
    if venc:
        partes.append(f"{venc} vencidas")
    if hoy:
        partes.append(f"{hoy} para hoy")
    return ", ".join(partes)


# ============================================================
#  HERRAMIENTAS  (lo que Claude "ve")  -- todas SEGURAS
# ============================================================

def tool_agregar_tarea(args: dict) -> str:
    try:
        t = agregar(args.get("texto", ""), args.get("vence", ""), args.get("prioridad", "media"))
    except ValueError as e:
        return f"No pude crear la tarea: {e}"
    extra = f" (vence {t['vence']})" if t["vence"] else ""
    return f"Tarea anotada [{t['id']}]: {t['texto']}{extra}"


def tool_listar_tareas(args: dict) -> str:
    filtro = args.get("filtro", "pendientes")
    vacios = {"pendientes": "No tienes tareas pendientes.", "hechas": "No hay tareas completadas.",
              "hoy": "Nada vence hoy.", "vencidas": "No tienes tareas vencidas.",
              "todas": "No hay tareas."}
    return render(filtrar(filtro), vacios.get((filtro or "").lower(), "No hay tareas."))


def tool_completar_tarea(args: dict) -> str:
    return completar(args.get("ref", "") or args.get("id", "") or args.get("texto", ""))


def tool_eliminar_tarea(args: dict) -> str:
    return eliminar(args.get("ref", "") or args.get("id", "") or args.get("texto", ""))


TAREAS_TOOLS = [
    {
        "name": "agregar_tarea",
        "description": ("Anota una tarea o recordatorio en la lista del usuario. Usa 'vence' "
                        "para recordatorios con fecha (AAAA-MM-DD, 'hoy' o 'manana') y "
                        "'prioridad' (alta/media/baja)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Descripcion de la tarea."},
                "vence": {"type": "string", "description": "Fecha limite opcional: AAAA-MM-DD, 'hoy' o 'manana'."},
                "prioridad": {"type": "string", "description": "alta, media (defecto) o baja."},
            },
            "required": ["texto"],
        },
    },
    {
        "name": "listar_tareas",
        "description": ("Muestra las tareas del usuario. filtro: 'pendientes' (defecto), 'todas', "
                        "'hechas', 'hoy' (vencen hoy) o 'vencidas' (atrasadas)."),
        "input_schema": {
            "type": "object",
            "properties": {"filtro": {"type": "string", "description": "pendientes/todas/hechas/hoy/vencidas."}},
            "required": [],
        },
    },
    {
        "name": "completar_tarea",
        "description": "Marca una tarea como completada. Indica su id o parte de su texto en 'ref'.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Id de la tarea o parte de su texto."}},
            "required": ["ref"],
        },
    },
    {
        "name": "eliminar_tarea",
        "description": "Elimina una tarea de la lista. Indica su id o parte de su texto en 'ref'.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Id de la tarea o parte de su texto."}},
            "required": ["ref"],
        },
    },
]

# Todas son de solo escritura sobre el archivo propio de Nexus: SEGURAS.
TAREAS_SEGURAS = {"agregar_tarea", "listar_tareas", "completar_tarea", "eliminar_tarea"}

TAREAS_EJECUTORES = {
    "agregar_tarea": tool_agregar_tarea,
    "listar_tareas": tool_listar_tareas,
    "completar_tarea": tool_completar_tarea,
    "eliminar_tarea": tool_eliminar_tarea,
}
