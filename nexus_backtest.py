#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtesting simple para NEXUS: estrategia de CRUCE DE MEDIAS.

Compra cuando la media móvil corta cruza por ENCIMA de la larga, y vende cuando
cruza por DEBAJO. Calcula operaciones, retorno acumulado y win rate sobre una
serie de precios. Motor puro (sin red), ideal como demo/educativo.

No es asesoría financiera ni garantía de resultados futuros (ver DISCLAIMER.md).
"""


def _sma(precios, n, i):
    """Media móvil simple de los últimos n precios hasta el índice i (inclusive)."""
    if i + 1 < n:
        return None
    ventana = precios[i + 1 - n: i + 1]
    return sum(ventana) / n


def cruce_medias(precios, corta: int = 5, larga: int = 20) -> dict:
    """Backtest de cruce de medias. Devuelve un resumen con las operaciones."""
    precios = [float(p) for p in precios]
    if corta >= larga:
        raise ValueError("La media corta debe ser menor que la larga.")
    if len(precios) < larga + 2:
        raise ValueError(f"Hacen falta al menos {larga + 2} precios para esta prueba.")

    operaciones = []
    entrada = None       # precio de entrada de la posición abierta
    prev_diff = None     # signo previo de (sma_corta - sma_larga)
    for i in range(len(precios)):
        sc, sl = _sma(precios, corta, i), _sma(precios, larga, i)
        if sc is None or sl is None:
            continue
        diff = sc - sl
        if prev_diff is not None:
            cruce_arriba = prev_diff <= 0 and diff > 0
            cruce_abajo = prev_diff >= 0 and diff < 0
            if cruce_arriba and entrada is None:
                entrada = precios[i]
            elif cruce_abajo and entrada is not None:
                salida = precios[i]
                operaciones.append({"entrada": entrada, "salida": salida,
                                    "retorno": (salida - entrada) / entrada})
                entrada = None
        prev_diff = diff

    abierta = entrada is not None
    retornos = [o["retorno"] for o in operaciones]
    ganadoras = sum(1 for r in retornos if r > 0)
    n = len(retornos)
    # Retorno compuesto de las operaciones cerradas.
    acum = 1.0
    for r in retornos:
        acum *= (1 + r)
    return {
        "operaciones": n,
        "ganadoras": ganadoras,
        "perdedoras": n - ganadoras,
        "win_rate": round(100 * ganadoras / n, 1) if n else 0.0,
        "retorno_pct": round((acum - 1) * 100, 2),
        "posicion_abierta": abierta,
        "corta": corta, "larga": larga,
    }


# ============================================================
#  HERRAMIENTA  (SEGURA)
# ============================================================

def tool_backtest(args: dict) -> str:
    crudo = (args.get("precios") or "").replace(";", ",")
    precios = []
    for tok in crudo.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            precios.append(float(tok))
        except ValueError:
            pass
    if len(precios) < 22:
        return ("Para el backtest pásame una serie de precios (al menos ~22 valores) en "
                "'precios', separados por comas. Ej: 'precios': '100,101,99,...'.")
    try:
        corta = int(args.get("corta", 5))
        larga = int(args.get("larga", 20))
        r = cruce_medias(precios, corta, larga)
    except ValueError as e:
        return f"No pude correr el backtest: {e}"
    return (f"📊 Backtest cruce de medias ({r['corta']}/{r['larga']}) sobre {len(precios)} precios:\n"
            f"  • Operaciones: {r['operaciones']} (ganadoras {r['ganadoras']}, perdedoras {r['perdedoras']})\n"
            f"  • Win rate: {r['win_rate']}%\n"
            f"  • Retorno acumulado: {r['retorno_pct']}%\n"
            f"  {'(hay una posición abierta al final)' if r['posicion_abierta'] else ''}\n"
            "  Nota: resultado histórico simulado; no garantiza resultados futuros.")


BACKTEST_TOOLS = [
    {
        "name": "backtest",
        "description": ("Backtest de una estrategia de cruce de medias sobre una serie de "
                        "precios. Parámetros: 'precios' (lista separada por comas), 'corta' y "
                        "'larga' (periodos de las medias)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "precios": {"type": "string", "description": "Precios separados por comas."},
                "corta": {"type": "integer", "description": "Periodo de la media corta (defecto 5)."},
                "larga": {"type": "integer", "description": "Periodo de la media larga (defecto 20)."},
            },
            "required": ["precios"],
        },
    },
]

BACKTEST_SEGURAS = {"backtest"}
BACKTEST_EJECUTORES = {"backtest": tool_backtest}
