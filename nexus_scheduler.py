#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scheduler PROACTIVO de NEXUS: hace cosas solo, sin que se lo pidas.

  - Vigila tus ALERTAS de precio y, cuando una se cumple, te avisa por Telegram.
  - Te manda un RESUMEN MATUTINO (tareas de hoy/vencidas + alertas + precios).

Reutiliza nexus_alertas, nexus_tareas, nexus_ninjatrader y nexus_telegram.
Pensado para correr en segundo plano (un hilo dentro del servidor web, o como
proceso aparte). Las funciones de logica son puras y faciles de testear.

Configuracion:
    NEXUS_BRIEFING_HORA          Hora del resumen matutino, HH:MM (vacio = desactivado).
    NEXUS_BRIEFING_INSTRUMENTOS  Instrumentos a incluir en el resumen (coma).
    NEXUS_SCHED_INTERVALO        Segundos entre comprobaciones (defecto 60).
"""

import time
import datetime
import threading

import nexus
import nexus_alertas as alertas
import nexus_tareas as tareas
import nexus_ninjatrader as nt
import nexus_telegram as telegram
import nexus_noticias as noticias

BRIEFING_HORA = nexus._env("NEXUS_BRIEFING_HORA", "")           # "08:00" o vacio
INSTRUMENTOS = [s.strip().upper() for s in nexus._env("NEXUS_BRIEFING_INSTRUMENTOS", "").split(",") if s.strip()]
INTERVALO = int(nexus._env("NEXUS_SCHED_INTERVALO", "60"))


# --------------------------- Logica pura (testeable) ---------------------------

def _parse_hora(hhmm: str):
    """'08:00' -> (8, 0). Devuelve None si esta vacio o mal formado."""
    try:
        h, m = hhmm.strip().split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return None


def toca_briefing(ahora: datetime.datetime, ultima_fecha, hora: str = None) -> bool:
    """True si toca enviar el resumen: ya paso la hora configurada hoy y no se ha
    enviado todavia en esta fecha."""
    hora = BRIEFING_HORA if hora is None else hora
    hm = _parse_hora(hora)
    if hm is None:
        return False
    objetivo = ahora.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    return ahora >= objetivo and ultima_fecha != ahora.date()


def componer_briefing(instrumentos=None) -> str:
    """Arma el texto del resumen matutino con datos del lado servidor."""
    instrumentos = INSTRUMENTOS if instrumentos is None else instrumentos
    partes = ["☀️ Buenos días. Tu resumen de hoy:"]

    venc = tareas.filtrar("vencidas")
    hoy = tareas.filtrar("hoy")
    pend = tareas.filtrar("pendientes")
    partes.append(f"\n✅ Tareas: {len(pend)} pendientes" +
                  (f", {len(venc)} vencidas" if venc else "") +
                  (f", {len(hoy)} para hoy" if hoy else "."))
    for t in (venc + hoy)[:6]:
        partes.append(f"  • {t['texto']}")

    al = alertas.cargar()
    activas = [a for a in al if not a.get("disparada")]
    if activas:
        partes.append(f"\n🔔 Alertas activas: {len(activas)}")
        for a in activas[:6]:
            partes.append(f"  • {a['instrument']} {a['op']} {a['precio']}")

    if instrumentos:
        partes.append("\n📈 Precios:")
        for ins in instrumentos[:8]:
            try:
                val = nt.leer_precio(ins, "LAST", espera=1.0)
            except Exception:
                val = "s/d"
            partes.append(f"  • {ins}: {val}")

    try:
        titulares = noticias.texto_titulares(4)
    except Exception:
        titulares = ""
    if titulares:
        partes.append("\n📰 Mercado:\n" + titulares)

    return "\n".join(partes)


def revisar_alertas() -> list:
    """Evalua las alertas; devuelve mensajes de las que se dispararon (para enviar)."""
    disparadas = alertas.evaluar()
    return [f"🔔 Alerta: {d['instrument']} {d['op']} {d['precio']}  (actual {d['actual']})"
            for d in disparadas]


# --------------------------- Bucle ---------------------------

def correr(intervalo: int = None, _max_ciclos: int = None):
    """Bucle del scheduler (bloqueante). `_max_ciclos` es solo para tests."""
    intervalo = INTERVALO if intervalo is None else intervalo
    ultima_briefing = None
    ciclos = 0
    while True:
        try:
            for msg in revisar_alertas():
                telegram.enviar(msg)
        except Exception:
            pass
        try:
            ahora = datetime.datetime.now()
            if toca_briefing(ahora, ultima_briefing):
                telegram.enviar(componer_briefing())
                ultima_briefing = ahora.date()
        except Exception:
            pass
        ciclos += 1
        if _max_ciclos is not None and ciclos >= _max_ciclos:
            return
        time.sleep(intervalo)


def iniciar_en_hilo():
    """Arranca el scheduler en un hilo daemon (para llamar desde el servidor web)."""
    h = threading.Thread(target=correr, daemon=True, name="nexus-scheduler")
    h.start()
    return h


if __name__ == "__main__":
    print("NEXUS scheduler en marcha…")
    correr()
