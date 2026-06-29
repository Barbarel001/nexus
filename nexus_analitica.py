#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analitica de trading para NEXUS — convierte tu bitacora de operaciones CERRADAS
en estadisticas que sirven para decidir: win rate, profit factor, expectancy,
drawdown, curva de equity y desglose por instrumento. Incluye una calculadora de
tamano de posicion por % de riesgo.

A diferencia de `nexus_ninjatrader.diario()` (que solo cuenta ordenes ENVIADAS),
aqui registras el RESULTADO real de cada operacion (P&L), que es lo unico que
permite calcular rendimiento. Persiste por usuario (aislado con nexus_ctx) en
operaciones.json (git-ignored), con escritura atomica.

Configuracion:
    NEXUS_OPS_PATH   Ruta del archivo de operaciones.
    NEXUS_MONEDA     Simbolo de moneda para mostrar (defecto '$').
"""

import os
import math
import uuid
import datetime

import nexus_util
import nexus_ctx

_CARPETA = os.path.dirname(os.path.abspath(__file__))
OPS_PATH = os.environ.get("NEXUS_OPS_PATH") or os.path.join(_CARPETA, "operaciones.json")
MONEDA = os.environ.get("NEXUS_MONEDA") or "$"

_LADOS = {"long", "short", "compra", "venta", "buy", "sell", ""}


def cargar() -> list:
    return (nexus_util.cargar_json(nexus_ctx.user_path(OPS_PATH), {"ops": []}) or {}).get("ops", [])


def guardar(ops: list) -> None:
    nexus_util.guardar_json(nexus_ctx.user_path(OPS_PATH), {"ops": ops})


def _num(v, nombre: str):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ".").replace(MONEDA, "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"{nombre} invalido: '{v}'.")


def _lado(v: str) -> str:
    v = (v or "").strip().lower()
    if v in ("long", "compra", "buy"):
        return "long"
    if v in ("short", "venta", "sell"):
        return "short"
    return ""


def registrar(instrument: str, pnl, lado: str = "", qty=0,
              entrada=None, salida=None, notas: str = "", fecha: str = "") -> dict:
    """Registra una operacion cerrada. 'pnl' (resultado en dinero, +/-) es obligatorio."""
    inst = (instrument or "").strip().upper()
    if not inst:
        raise ValueError("Falta el instrumento.")
    p = _num(pnl, "pnl")
    if p is None:
        raise ValueError("Falta el resultado (pnl) de la operacion.")
    f = (fecha or "").strip() or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(f)
    except ValueError:
        f = datetime.date.today().isoformat()
    try:
        q = int(float(qty)) if qty not in (None, "") else 0
    except (TypeError, ValueError):
        q = 0
    op = {
        "id": uuid.uuid4().hex[:6],
        "fecha": f,
        "instrument": inst,
        "lado": _lado(lado),
        "qty": q,
        "entrada": _num(entrada, "entrada"),
        "salida": _num(salida, "salida"),
        "pnl": round(p, 2),
        "notas": (notas or "").strip(),
    }
    ops = cargar()
    ops.append(op)
    guardar(ops)
    return op


def eliminar(ref: str) -> str:
    ref = (ref or "").strip().lower()
    ops = cargar()
    coincide = [o for o in ops if o["id"].lower().startswith(ref)]
    if not coincide:
        return f"No encontre ninguna operacion con id '{ref}'."
    guardar([o for o in ops if o["id"] != coincide[0]["id"]])
    o = coincide[0]
    return f"Operacion eliminada: {o['instrument']} {MONEDA}{o['pnl']}"


def _ordenadas(ops: list) -> list:
    """Operaciones por fecha (y orden de registro) para la curva de equity."""
    return sorted(ops, key=lambda o: (o.get("fecha", ""), ops.index(o)))


def curva_equity(ops: list = None) -> list:
    """Serie de P&L acumulado tras cada operacion (para dibujar la curva)."""
    ops = cargar() if ops is None else ops
    acum = 0.0
    serie = []
    for o in _ordenadas(ops):
        acum = round(acum + float(o.get("pnl", 0)), 2)
        serie.append(acum)
    return serie


def max_drawdown(ops: list = None) -> float:
    """Mayor caida desde un pico de la curva de equity (en dinero, valor <= 0)."""
    serie = curva_equity(ops)
    pico = 0.0
    peor = 0.0
    for v in serie:
        pico = max(pico, v)
        peor = min(peor, v - pico)
    return round(peor, 2)


def _racha(ops: list) -> int:
    """Racha actual: + n ganadoras seguidas, - n perdedoras seguidas (al final)."""
    serie = _ordenadas(ops)
    n = 0
    signo = 0
    for o in reversed(serie):
        pnl = float(o.get("pnl", 0))
        s = 1 if pnl > 0 else (-1 if pnl < 0 else 0)
        if s == 0:
            break
        if signo == 0:
            signo = s
        if s != signo:
            break
        n += 1
    return signo * n


def estadisticas(ops: list = None) -> dict:
    """Metricas clave de rendimiento a partir de las operaciones cerradas."""
    ops = cargar() if ops is None else ops
    n = len(ops)
    if not n:
        return {"n": 0}
    pnls = [float(o.get("pnl", 0)) for o in ops]
    ganadoras = [p for p in pnls if p > 0]
    perdedoras = [p for p in pnls if p < 0]
    bruto_ganado = round(sum(ganadoras), 2)
    bruto_perdido = round(sum(perdedoras), 2)            # <= 0
    pnl_total = round(sum(pnls), 2)
    decididas = len(ganadoras) + len(perdedoras)
    win_rate = round(100 * len(ganadoras) / decididas, 1) if decididas else 0.0
    profit_factor = (round(bruto_ganado / abs(bruto_perdido), 2)
                     if bruto_perdido else (math.inf if bruto_ganado else 0.0))
    avg_win = round(bruto_ganado / len(ganadoras), 2) if ganadoras else 0.0
    avg_loss = round(bruto_perdido / len(perdedoras), 2) if perdedoras else 0.0
    expectancy = round(pnl_total / n, 2)                 # P&L medio por operacion
    por_inst = {}
    for o in ops:
        k = o.get("instrument", "?")
        por_inst[k] = round(por_inst.get(k, 0.0) + float(o.get("pnl", 0)), 2)
    return {
        "n": n,
        "ganadoras": len(ganadoras),
        "perdedoras": len(perdedoras),
        "win_rate": win_rate,
        "pnl_total": pnl_total,
        "bruto_ganado": bruto_ganado,
        "bruto_perdido": bruto_perdido,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "mejor": round(max(pnls), 2),
        "peor": round(min(pnls), 2),
        "max_drawdown": max_drawdown(ops),
        "racha": _racha(ops),
        "por_instrumento": por_inst,
    }


def tamano_posicion(saldo, riesgo_pct, entrada, stop, valor_por_punto=1.0) -> dict:
    """Calculadora de tamano de posicion por % de riesgo.

    saldo: capital de la cuenta. riesgo_pct: % del saldo a arriesgar (ej. 1).
    entrada/stop: precios. valor_por_punto: $ por punto/unidad de precio y contrato
    (ej. MES=5, ES=50, acciones=1). Devuelve contratos/acciones a operar."""
    saldo = _num(saldo, "saldo") or 0.0
    riesgo_pct = _num(riesgo_pct, "riesgo_pct") or 0.0
    entrada = _num(entrada, "entrada")
    stop = _num(stop, "stop")
    vpp = _num(valor_por_punto, "valor_por_punto") or 1.0
    if saldo <= 0 or riesgo_pct <= 0:
        raise ValueError("El saldo y el % de riesgo deben ser mayores que 0.")
    if entrada is None or stop is None or entrada == stop:
        raise ValueError("Indica entrada y stop distintos para medir el riesgo.")
    riesgo_monto = saldo * riesgo_pct / 100.0
    puntos = abs(entrada - stop)
    riesgo_por_contrato = puntos * vpp
    contratos = int(riesgo_monto // riesgo_por_contrato) if riesgo_por_contrato > 0 else 0
    return {
        "riesgo_monto": round(riesgo_monto, 2),
        "puntos_riesgo": round(puntos, 4),
        "riesgo_por_contrato": round(riesgo_por_contrato, 2),
        "contratos": contratos,
        "riesgo_real": round(contratos * riesgo_por_contrato, 2),
    }


# ============================================================
#  HERRAMIENTAS  (SEGURAS: registran/leen tu bitacora, no mueven dinero)
# ============================================================

def _fmt_pf(pf) -> str:
    return "∞" if pf == math.inf else str(pf)


def tool_registrar_trade(args: dict) -> str:
    try:
        o = registrar(args.get("instrument"), args.get("pnl"), args.get("lado", ""),
                      args.get("qty", 0), args.get("entrada"), args.get("salida"),
                      args.get("notas", ""), args.get("fecha", ""))
    except ValueError as e:
        return f"No pude registrar la operacion: {e}"
    signo = "🟢" if o["pnl"] > 0 else ("🔴" if o["pnl"] < 0 else "⚪")
    return f"{signo} Operacion registrada [{o['id']}]: {o['instrument']} {MONEDA}{o['pnl']} ({o['fecha']})"


def tool_stats_trading(args: dict = None) -> str:
    s = estadisticas()
    if not s.get("n"):
        return ("Aun no hay operaciones cerradas registradas. Registra tus trades con "
                "su resultado (pnl) para ver estadisticas.")
    return (
        f"📊 Estadisticas de trading ({s['n']} operaciones)\n"
        f"  P&L total     : {MONEDA}{s['pnl_total']}\n"
        f"  Win rate      : {s['win_rate']}%  ({s['ganadoras']}G / {s['perdedoras']}P)\n"
        f"  Profit factor : {_fmt_pf(s['profit_factor'])}\n"
        f"  Expectancy    : {MONEDA}{s['expectancy']} por operacion\n"
        f"  Media ganada  : {MONEDA}{s['avg_win']}   Media perdida: {MONEDA}{s['avg_loss']}\n"
        f"  Mejor / peor  : {MONEDA}{s['mejor']} / {MONEDA}{s['peor']}\n"
        f"  Max drawdown  : {MONEDA}{s['max_drawdown']}\n"
        f"  Racha actual  : {s['racha']:+d}"
    )


def tool_calc_riesgo(args: dict) -> str:
    try:
        r = tamano_posicion(args.get("saldo"), args.get("riesgo_pct"), args.get("entrada"),
                            args.get("stop"), args.get("valor_por_punto", 1.0))
    except ValueError as e:
        return f"No pude calcular el tamano: {e}"
    return (
        f"🧮 Tamano de posicion sugerido: {r['contratos']} contrato(s)/accion(es)\n"
        f"  Riesgo objetivo : {MONEDA}{r['riesgo_monto']}\n"
        f"  Riesgo/contrato : {MONEDA}{r['riesgo_por_contrato']} ({r['puntos_riesgo']} puntos)\n"
        f"  Riesgo real     : {MONEDA}{r['riesgo_real']}"
    )


ANALITICA_TOOLS = [
    {
        "name": "registrar_trade",
        "description": ("Registra una operacion CERRADA con su resultado para la analitica. "
                        "'instrument' y 'pnl' (resultado en dinero, +/-) obligatorios; 'lado' "
                        "(long/short), 'qty', 'entrada', 'salida', 'notas' y 'fecha' opcionales."),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "Instrumento, ej. 'MNQ', 'ES', 'AAPL'."},
                "pnl": {"type": "number", "description": "Resultado en dinero (positivo ganancia, negativo perdida)."},
                "lado": {"type": "string", "description": "long o short (opcional)."},
                "qty": {"type": "integer", "description": "Cantidad/contratos (opcional)."},
                "entrada": {"type": "number", "description": "Precio de entrada (opcional)."},
                "salida": {"type": "number", "description": "Precio de salida (opcional)."},
                "notas": {"type": "string", "description": "Notas/lecciones (opcional)."},
                "fecha": {"type": "string", "description": "Fecha AAAA-MM-DD (defecto hoy)."},
            },
            "required": ["instrument", "pnl"],
        },
    },
    {
        "name": "stats_trading",
        "description": ("Estadisticas de rendimiento de tus operaciones cerradas: win rate, "
                        "profit factor, expectancy, drawdown, mejor/peor y racha."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "calc_riesgo",
        "description": ("Calcula el tamano de posicion por % de riesgo. 'saldo', 'riesgo_pct' "
                        "(% del saldo), 'entrada' y 'stop'; 'valor_por_punto' segun el instrumento "
                        "(MES=5, ES=50, acciones=1)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "saldo": {"type": "number", "description": "Capital de la cuenta."},
                "riesgo_pct": {"type": "number", "description": "% del saldo a arriesgar (ej. 1)."},
                "entrada": {"type": "number", "description": "Precio de entrada."},
                "stop": {"type": "number", "description": "Precio del stop."},
                "valor_por_punto": {"type": "number", "description": "$ por punto y contrato (ej. ES=50)."},
            },
            "required": ["saldo", "riesgo_pct", "entrada", "stop"],
        },
    },
]

ANALITICA_SEGURAS = {"registrar_trade", "stats_trading", "calc_riesgo"}
ANALITICA_EJECUTORES = {
    "registrar_trade": tool_registrar_trade,
    "stats_trading": tool_stats_trading,
    "calc_riesgo": tool_calc_riesgo,
}
