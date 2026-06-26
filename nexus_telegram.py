#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de Telegram para NEXUS: controla tu asistente y recibe notificaciones desde
CUALQUIER lugar (con datos moviles, sin tunel ni IP publica).

Sin dependencias externas: habla con la Bot API de Telegram por HTTPS (urllib).

Configuracion (variables de entorno):
    NEXUS_TELEGRAM_TOKEN     Token del bot (te lo da @BotFather en Telegram).  [REQUERIDO]
    NEXUS_TELEGRAM_CHAT_ID   Tu chat id (uno o varios separados por coma). Solo se
                             responde a estos chats. Muy recomendado por seguridad.
                             Si lo dejas vacio, el bot responde a CUALQUIERA que lo
                             escriba (no recomendado).

Como obtener tu chat id: escribe algo a tu bot y luego abre
    https://api.telegram.org/bot<TOKEN>/getUpdates
y busca "chat":{"id": ... }.

Por SEGURIDAD, por Telegram solo se exponen las herramientas seguras (memoria,
tareas, alertas, precios, lectura). Las ordenes que mueven dinero NO se ejecutan
por aqui; para operar usa la web/terminal (con su confirmacion).

Uso:
    python nexus_telegram.py      # arranca el bot (polling)
"""

import json
import time
import urllib.parse
import urllib.request

import nexus
import nexus_ollama
import nexus_ninjatrader as nt
import nexus_tareas as tareas
import nexus_alertas as alertas

TOKEN = nexus._env("NEXUS_TELEGRAM_TOKEN", "")
_API = f"https://api.telegram.org/bot{TOKEN}"

# Chats autorizados (allowlist). Vacio = cualquiera (no recomendado).
_ids = [s.strip() for s in nexus._env("NEXUS_TELEGRAM_CHAT_ID", "").replace(";", ",").split(",") if s.strip()]
CHATS_PERMITIDOS = set(_ids)

# Herramientas SEGURAS disponibles por Telegram (no mueven dinero).
SEGURAS = ({"recordar", "rastrear_ofertas", "read_file", "list_directory"}
           | nt.NT_SEGURAS | tareas.TAREAS_SEGURAS | alertas.ALERTAS_SEGURAS)

# Historial de conversacion por chat (en memoria; se reinicia con /nuevo).
_historiales = {}
MAX_TURNOS = 20


def configurado() -> bool:
    return bool(TOKEN)


def permitido(chat_id) -> bool:
    """True si el chat puede usar el bot (o si no hay allowlist configurada)."""
    if not CHATS_PERMITIDOS:
        return True
    return str(chat_id) in CHATS_PERMITIDOS


# --------------------------- API de Telegram ---------------------------

def enviar(texto: str, chat_id=None) -> bool:
    """Envia un mensaje. Si no se da chat_id, lo manda al primer chat permitido
    (para notificaciones del scheduler). Nunca lanza: devuelve True/False."""
    if not TOKEN:
        return False
    destino = chat_id if chat_id is not None else (next(iter(CHATS_PERMITIDOS), None))
    if destino is None:
        return False
    ok = True
    for trozo in partir_mensaje(texto):
        datos = urllib.parse.urlencode({"chat_id": destino, "text": trozo}).encode()
        try:
            with urllib.request.urlopen(_API + "/sendMessage", data=datos, timeout=20) as r:
                r.read()
        except Exception:
            ok = False
    return ok


def partir_mensaje(texto: str, limite: int = 4000):
    """Telegram limita a ~4096 caracteres por mensaje; troceamos si hace falta."""
    texto = texto or "(sin respuesta)"
    return [texto[i:i + limite] for i in range(0, len(texto), limite)] or ["(sin respuesta)"]


def obtener_updates(offset: int, timeout: int = 50):
    """Long-polling de mensajes nuevos. Devuelve la lista de updates."""
    url = _API + "/getUpdates?" + urllib.parse.urlencode({"offset": offset, "timeout": timeout})
    with urllib.request.urlopen(url, timeout=timeout + 15) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return data.get("result", []) if data.get("ok") else []


def extraer_mensaje(update: dict):
    """Saca (chat_id, texto) de un update, o (None, None) si no es un mensaje de texto."""
    msg = update.get("message") or update.get("edited_message") or {}
    chat = (msg.get("chat") or {}).get("id")
    texto = msg.get("text")
    if chat is None or not texto:
        return None, None
    return chat, texto


# --------------------------- Agente ---------------------------

def _ejecutar_seguro(name: str, args: dict) -> str:
    """Ejecuta solo herramientas seguras; bloquea las que mueven dinero."""
    if name in SEGURAS:
        try:
            return nexus.EJECUTORES[name](args)
        except Exception as e:
            return f"Error en {name}: {e}"
    return (f"La herramienta '{name}' no esta disponible por Telegram por seguridad. "
            "Para operar (ordenes) usa la version web o de terminal.")


def _usar_ollama() -> bool:
    return nexus.BACKEND == "ollama"


def responder(chat_id, texto_usuario: str) -> str:
    """Procesa un mensaje del usuario con el agente y devuelve la respuesta."""
    system = (nexus.construir_system_prompt() +
              "\n\nEstas hablando por TELEGRAM. Sé breve y claro (es un movil). Por aqui "
              "solo tienes herramientas seguras; las ordenes de trading se hacen en la web.")
    hist = _historiales.setdefault(chat_id, [])
    hist.append({"role": "user", "content": texto_usuario})
    hist[:] = hist[-MAX_TURNOS:]

    if _usar_ollama():
        texto = ""
        try:
            for evt, pl in nexus_ollama.chat_eventos(
                    list(hist), system, nexus_ollama.tools_ollama(False), _ejecutar_seguro):
                if evt == "delta":
                    texto += pl
                elif evt == "fin" and pl.get("text"):
                    texto = pl["text"]
        except Exception as e:
            return f"(error del modelo local: {e})"
        hist.append({"role": "assistant", "content": texto})
    else:
        tools = [t for t in nexus.TOOLS if t.get("name") not in nexus.HERRAMIENTAS_PELIGROSAS]
        msgs = [dict(m) for m in hist]
        try:
            texto, _ = nexus.conversar(msgs, system_prompt=system, tools=tools, ejecutar=_ejecutar_seguro)
        except Exception as e:
            return f"(error: {e})"
        hist.append({"role": "assistant", "content": texto})
    hist[:] = hist[-MAX_TURNOS:]
    return texto or "(sin respuesta)"


def _manejar(chat_id, texto: str) -> str:
    t = texto.strip()
    if t in ("/start", "/help", "/ayuda"):
        return ("Soy NEXUS. Hablame normal y te ayudo: tareas, recordatorios, alertas de "
                "precio, precios de NinjaTrader, memoria y mas.\n"
                "Comandos: /nuevo (reinicia la charla), /tareas, /alertas.")
    if t == "/nuevo":
        _historiales.pop(chat_id, None)
        return "Listo, empezamos de cero."
    if t == "/tareas":
        return _ejecutar_seguro("listar_tareas", {"filtro": "pendientes"})
    if t == "/alertas":
        return _ejecutar_seguro("alerta_precio", {"accion": "listar"})
    return responder(chat_id, texto)


# --------------------------- Bucle principal ---------------------------

def run():
    """Arranca el bot en polling (bloqueante)."""
    if not TOKEN:
        raise RuntimeError("Falta NEXUS_TELEGRAM_TOKEN. Crea un bot con @BotFather y exporta el token.")
    print("NEXUS Telegram: escuchando…")
    offset = 0
    while True:
        try:
            updates = obtener_updates(offset)
        except Exception:
            time.sleep(3)
            continue
        for u in updates:
            offset = u.get("update_id", offset) + 1
            chat_id, texto = extraer_mensaje(u)
            if chat_id is None:
                continue
            if not permitido(chat_id):
                enviar("No estas autorizado para usar este bot.", chat_id)
                continue
            try:
                respuesta = _manejar(chat_id, texto)
            except Exception as e:
                respuesta = f"(ups, error: {e})"
            enviar(respuesta, chat_id)


if __name__ == "__main__":
    run()
