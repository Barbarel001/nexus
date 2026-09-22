#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RECEPCIONISTA IA — canal de WhatsApp (Twilio), multi-tenant.

Da una segunda puerta de entrada al MISMO motor: el cliente escribe por WhatsApp
al numero del negocio y el recepcionista responde igual que en el chat web
(mismos precios aprobados, misma captura de leads, mismo aislamiento por negocio).

Como funciona (sin SDK ni credenciales para responder):
  - Twilio envia un POST (form) a  /wa/webhook  con From (cliente), To (numero del
    negocio) y Body (mensaje).
  - Enrutamos por `To` -> negocio (columna wa_number). Ejecutamos el mismo
    responder_cliente del chat web y DEVOLVEMOS la respuesta como TwiML
    (<Response><Message>...). Twilio la manda al cliente: no hace falta llamar a
    la API de Twilio para responder.
  - Verificamos la firma X-Twilio-Signature con hmac (stdlib) cuando hay token
    configurado; asi el webhook no acepta mensajes falsos.

Diseño para probar SIN credenciales ni red:
  - `responder_whatsapp(slug, from, body)` envuelve responder_cliente (los tests lo
    monkeypatchean para no tocar la IA).
  - `verificar_firma(url, params, firma)` es pura (hmac-sha1 + base64).
  - `twiml(texto)` genera el XML de respuesta.

Configuracion:
    NEXUS_TWILIO_AUTH_TOKEN   Token de Twilio para verificar la firma del webhook.
                              Sin el, el webhook responde igual pero NO verifica
                              (solo para pruebas locales; en produccion, ponlo).
"""

import base64
import hashlib
import hmac
import os
import sqlite3

import nexus_db
import nexus_recepcion_saas as saas
import nexus_recepcionista as recep
import nexus_util

AUTH_TOKEN = os.environ.get("NEXUS_TWILIO_AUTH_TOKEN", "")

_SESIONES = {}  # (slug, from) -> {"historial", "estado"}  (memoria del proceso)


# --------------------------- Base de datos / migracion ---------------------------

def _conn():
    conn = sqlite3.connect(nexus_db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Asegura la capa SaaS y añade la columna wa_number a negocios. Idempotente."""
    saas.init()
    with _conn() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(negocios)").fetchall()}
        if "wa_number" not in cols:
            c.execute("ALTER TABLE negocios ADD COLUMN wa_number TEXT")


def _normalizar_wa(numero: str) -> str:
    """Normaliza un numero de WhatsApp al formato de Twilio: 'whatsapp:+34...'."""
    n = (numero or "").strip().lower().replace(" ", "")
    if not n:
        return ""
    if not n.startswith("whatsapp:"):
        n = "whatsapp:" + n
    return n


def set_wa_number(slug: str, numero: str) -> str:
    """Asocia un numero de WhatsApp (el del negocio en Twilio) a un negocio."""
    if saas.obtener_negocio(slug) is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    n = _normalizar_wa(numero)
    init()
    with _conn() as c:
        c.execute("UPDATE negocios SET wa_number=? WHERE slug=?", (n, slug))
    return n


def negocio_por_wa(numero: str):
    """Devuelve el slug del negocio dueño de ese numero de WhatsApp, o None."""
    n = _normalizar_wa(numero)
    if not n:
        return None
    init()
    with _conn() as c:
        row = c.execute("SELECT slug FROM negocios WHERE wa_number=?", (n,)).fetchone()
    return row["slug"] if row else None


# --------------------------- Firma del webhook (Twilio) ---------------------------

def verificar_firma(url: str, params: dict, firma: str, token: str = None) -> bool:
    """Verifica X-Twilio-Signature: base64(HMAC-SHA1(token, url + params ordenados)).
    Sin token configurado devuelve False (el llamador decide si exigirla)."""
    token = AUTH_TOKEN if token is None else token
    if not token or not firma:
        return False
    base = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    mac = hmac.new(token.encode(), base.encode("utf-8"), hashlib.sha1).digest()
    esperado = base64.b64encode(mac).decode()
    return hmac.compare_digest(esperado, firma)


# --------------------------- TwiML ---------------------------

def _escapar_xml(texto: str) -> str:
    return (texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def twiml(texto: str) -> str:
    """Respuesta TwiML con un mensaje (lo que Twilio envia de vuelta al cliente)."""
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Message>{_escapar_xml(texto)}</Message></Response>")


# --------------------------- Conversacion por WhatsApp ---------------------------

def responder_whatsapp(slug: str, numero_cliente: str, mensaje: str,
                       max_leads: int = None) -> str:
    """Atiende un mensaje de WhatsApp para el negocio `slug`. Mantiene la
    conversacion por (negocio, numero del cliente). Devuelve el texto de respuesta."""
    clave = f"{slug}|{numero_cliente}"
    ses = _SESIONES.setdefault(clave, {"historial": [], "estado": recep.nuevo_estado()})
    r = saas.responder_cliente(slug, mensaje, historial=ses["historial"],
                               estado=ses["estado"], max_leads=max_leads)
    return r.get("texto", "")


# --------------------------- Webhook (Flask blueprint) ---------------------------

def crear_blueprint():
    """Blueprint del canal WhatsApp:
        POST /wa/webhook   webhook de Twilio (From/To/Body) -> respuesta TwiML
    Enruta por el numero destino (To) al negocio; responde con el recepcionista."""
    from flask import Blueprint, Response, request

    bp = Blueprint("recepcion_whatsapp", __name__)

    @bp.post("/wa/webhook")
    def webhook():
        params = request.form.to_dict()
        # Verificacion de firma (si hay token). En pruebas locales sin token, se omite.
        if AUTH_TOKEN:
            firma = request.headers.get("X-Twilio-Signature", "")
            if not verificar_firma(request.url, params, firma):
                return Response(twiml("No autorizado."), status=403, mimetype="text/xml")
        destino = params.get("To", "")
        origen = params.get("From", "")
        cuerpo = (params.get("Body") or "").strip()
        slug = negocio_por_wa(destino)
        negocio = saas.obtener_negocio(slug) if slug else None
        if not slug or not saas.negocio_activo(negocio):
            return Response(twiml("Este servicio no esta disponible ahora mismo."),
                            mimetype="text/xml")
        if not cuerpo:
            return Response(twiml("¡Hola! ¿En que puedo ayudarte?"), mimetype="text/xml")
        try:
            texto = responder_whatsapp(slug, origen, cuerpo)
        except Exception as e:
            nexus_util.log(f"whatsapp: error atendiendo {slug}: {e}", "ERROR")
            texto = "Ha ocurrido un problema; intentalo de nuevo en un momento."
        return Response(twiml(texto), mimetype="text/xml")

    return bp
