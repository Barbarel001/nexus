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
import nexus_docs as docs
import nexus_noticias as noticias
import nexus_gastos as gastos
import nexus_clima as clima
import nexus_google as google

TOKEN = nexus._env("NEXUS_TELEGRAM_TOKEN", "")
_API = f"https://api.telegram.org/bot{TOKEN}"

# Chats autorizados (allowlist). Vacio = cualquiera (no recomendado).
_ids = [s.strip() for s in nexus._env("NEXUS_TELEGRAM_CHAT_ID", "").replace(";", ",").split(",") if s.strip()]
CHATS_PERMITIDOS = set(_ids)

# Herramientas SEGURAS disponibles por Telegram (no mueven dinero).
SEGURAS = ({"recordar", "buscar_memoria", "olvidar_memoria", "rastrear_ofertas",
            "read_file", "list_directory"}
           | nt.NT_SEGURAS | tareas.TAREAS_SEGURAS | alertas.ALERTAS_SEGURAS | docs.DOCS_SEGURAS
           | noticias.NEWS_SEGURAS | gastos.GASTOS_SEGURAS | clima.CLIMA_SEGURAS
           | google.GOOGLE_SEGURAS)

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


def extraer_foto(update: dict):
    """Saca (chat_id, file_id, caption) si el update trae una foto; si no, (None, None, None)."""
    msg = update.get("message") or update.get("edited_message") or {}
    chat = (msg.get("chat") or {}).get("id")
    fotos = msg.get("photo") or []
    if chat is None or not fotos:
        return None, None, None
    file_id = fotos[-1].get("file_id")  # la ultima es la de mayor resolucion
    return chat, file_id, (msg.get("caption") or "")


def descargar_archivo(file_id: str) -> bytes:
    """Descarga un archivo de Telegram por su file_id (getFile + descarga)."""
    url = _API + "/getFile?" + urllib.parse.urlencode({"file_id": file_id})
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    path = data["result"]["file_path"]
    furl = f"https://api.telegram.org/file/bot{TOKEN}/{path}"
    with urllib.request.urlopen(furl, timeout=40) as r:
        return r.read()


def analizar_foto(file_id: str, caption: str) -> str:
    """Descarga una foto de Telegram y la analiza con la vision de Claude."""
    import base64
    try:
        crudo = descargar_archivo(file_id)
        b64 = base64.b64encode(crudo).decode("ascii")
        texto, _ = nexus.analizar_imagen(b64, "image/jpeg", caption or "")
        return texto or "(no pude analizar la imagen)"
    except Exception as e:
        return f"No pude analizar la imagen: {e}"


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
    partes = t.split(maxsplit=1)
    cmd = partes[0].lower() if partes else ""
    arg = partes[1].strip() if len(partes) > 1 else ""
    if cmd in ("/start", "/help", "/ayuda"):
        return ("Soy NEXUS. Háblame normal y te ayudo. Comandos rápidos:\n"
                "/nuevo — reinicia la charla\n"
                "/tareas — tus pendientes\n"
                "/alertas — tus alertas de precio\n"
                "/gastos — gastos del mes\n"
                "/noticias — titulares de mercado\n"
                "/clima <ciudad> — el tiempo\n"
                "/agenda — tu Google Calendar\n"
                "/correos — tus últimos correos\n"
                "También puedes enviarme una FOTO y la analizo.")
    if cmd == "/nuevo":
        _historiales.pop(chat_id, None)
        return "Listo, empezamos de cero."
    if cmd == "/tareas":
        return _ejecutar_seguro("listar_tareas", {"filtro": "pendientes"})
    if cmd == "/alertas":
        return _ejecutar_seguro("alerta_precio", {"accion": "listar"})
    if cmd == "/gastos":
        return _ejecutar_seguro("resumen_gastos", {})
    if cmd == "/noticias":
        return _ejecutar_seguro("noticias_mercado", {})
    if cmd == "/clima":
        return _ejecutar_seguro("clima", {"ciudad": arg})
    if cmd == "/agenda":
        return _ejecutar_seguro("google_agenda", {})
    if cmd == "/correos":
        return _ejecutar_seguro("google_correos", {})
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
            # Foto: analisis de imagen (vision)
            fchat, file_id, caption = extraer_foto(u)
            if fchat is not None:
                if not permitido(fchat):
                    enviar("No estas autorizado para usar este bot.", fchat)
                    continue
                enviar(analizar_foto(file_id, caption), fchat)
                continue
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
