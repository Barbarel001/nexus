#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integracion con Google (Calendar + Gmail) para NEXUS.

Permite a Nexus ver tu agenda, crear eventos, leer tus ultimos correos y enviar
emails. Usa OAuth de Google. Las librerias se importan de forma PEREZOSA: si no
las tienes instaladas, Nexus sigue funcionando y estas herramientas avisan con
instrucciones (no rompen nada).

--- Puesta en marcha (una vez) ---
1) Instala las dependencias:
       pip install -r requirements-google.txt
2) En https://console.cloud.google.com crea un proyecto, habilita las APIs de
   Calendar y Gmail, y crea credenciales OAuth de tipo "App de escritorio".
   Descarga el JSON y guardalo como  credentials.json  junto a este archivo.
3) Autoriza tu cuenta (abre el navegador una vez):
       python nexus_google.py
   Se creara  token.json  y ya estara listo.

Configuracion:
    NEXUS_GOOGLE_CREDENTIALS   Ruta del credentials.json (defecto: credentials.json).
    NEXUS_GOOGLE_TOKEN         Ruta del token.json (defecto: token.json).
"""

import base64
import datetime
import os
from email.mime.text import MIMEText

_CARPETA = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS = os.environ.get("NEXUS_GOOGLE_CREDENTIALS") or os.path.join(_CARPETA, "credentials.json")
TOKEN = os.environ.get("NEXUS_GOOGLE_TOKEN") or os.path.join(_CARPETA, "token.json")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_AYUDA = ("Google no esta configurado. Instala 'pip install -r requirements-google.txt', "
          "pon tu credentials.json y ejecuta 'python nexus_google.py' para autorizar.")


def librerias_ok() -> bool:
    try:
        import google_auth_oauthlib  # noqa: F401
        import googleapiclient  # noqa: F401
        return True
    except ImportError:
        return False


def configurado() -> bool:
    """True si hay token de autorizacion y librerias disponibles."""
    return librerias_ok() and os.path.isfile(TOKEN)


def _credenciales():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.isfile(TOKEN) else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def _servicio(nombre: str, version: str):
    from googleapiclient.discovery import build
    creds = _credenciales()
    if not creds:
        raise RuntimeError("Sin autorizacion de Google.")
    return build(nombre, version, credentials=creds, cache_discovery=False)


def autorizar():
    """Lanza el flujo OAuth (abre el navegador) y guarda token.json. Para correr una vez."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not os.path.isfile(CREDENTIALS):
        raise FileNotFoundError(f"Falta {CREDENTIALS}. Descargalo de Google Cloud (OAuth de escritorio).")
    flujo = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
    creds = flujo.run_local_server(port=0)
    with open(TOKEN, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return True


# --------------------------- Calendar ---------------------------

def proximos_eventos(dias: int = 7, maximo: int = 10) -> list:
    cal = _servicio("calendar", "v3")
    ahora = datetime.datetime.utcnow().isoformat() + "Z"
    hasta = (datetime.datetime.utcnow() + datetime.timedelta(days=dias)).isoformat() + "Z"
    res = cal.events().list(calendarId="primary", timeMin=ahora, timeMax=hasta,
                            singleEvents=True, orderBy="startTime", maxResults=maximo).execute()
    out = []
    for e in res.get("items", []):
        ini = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
        out.append({"titulo": e.get("summary", "(sin titulo)"), "inicio": ini})
    return out


def crear_evento(titulo: str, inicio: str, fin: str = "") -> str:
    cal = _servicio("calendar", "v3")
    if not fin:
        # +1h por defecto si solo se da el inicio
        try:
            dt = datetime.datetime.fromisoformat(inicio)
            fin = (dt + datetime.timedelta(hours=1)).isoformat()
        except ValueError:
            fin = inicio
    cuerpo = {"summary": titulo,
              "start": {"dateTime": inicio}, "end": {"dateTime": fin}}
    ev = cal.events().insert(calendarId="primary", body=cuerpo).execute()
    return ev.get("htmlLink", "evento creado")


# --------------------------- Gmail ---------------------------

def correos_recientes(n: int = 5) -> list:
    gmail = _servicio("gmail", "v1")
    res = gmail.users().messages().list(userId="me", maxResults=n, labelIds=["INBOX"]).execute()
    out = []
    for m in res.get("messages", []):
        msg = gmail.users().messages().get(userId="me", id=m["id"], format="metadata",
                                           metadataHeaders=["From", "Subject"]).execute()
        cabeceras = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        out.append({"de": cabeceras.get("From", ""), "asunto": cabeceras.get("Subject", "(sin asunto)"),
                    "resumen": msg.get("snippet", "")})
    return out


def enviar_correo(para: str, asunto: str, cuerpo: str) -> str:
    gmail = _servicio("gmail", "v1")
    mensaje = MIMEText(cuerpo)
    mensaje["to"] = para
    mensaje["subject"] = asunto
    raw = base64.urlsafe_b64encode(mensaje.as_bytes()).decode()
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    return f"Correo enviado a {para}."


# ============================================================
#  HERRAMIENTAS
# ============================================================

def _guard(fn, *a, **k):
    """Ejecuta una operacion de Google capturando errores comunes con mensajes claros."""
    if not librerias_ok():
        return _AYUDA
    if not os.path.isfile(TOKEN):
        return _AYUDA
    try:
        return fn(*a, **k)
    except Exception as e:
        return f"Error con Google: {e}"


def tool_agenda(args: dict) -> str:
    def _f():
        try:
            dias = int(args.get("dias", 7))
        except (TypeError, ValueError):
            dias = 7
        evs = proximos_eventos(dias)
        if not evs:
            return f"No tienes eventos en los proximos {dias} dias."
        return "📅 Proximos eventos:\n" + "\n".join(f"  • {e['inicio']}  {e['titulo']}" for e in evs)
    return _guard(_f)


def tool_correos(args: dict) -> str:
    def _f():
        try:
            n = int(args.get("n", 5))
        except (TypeError, ValueError):
            n = 5
        cs = correos_recientes(n)
        if not cs:
            return "No hay correos recientes."
        return "📧 Correos recientes:\n" + "\n".join(
            f"  • {c['asunto']} — {c['de']}\n    {c['resumen'][:120]}" for c in cs)
    return _guard(_f)


def tool_crear_evento(args: dict) -> str:
    titulo = (args.get("titulo") or "").strip()
    inicio = (args.get("inicio") or "").strip()
    if not titulo or not inicio:
        return "Indica al menos 'titulo' e 'inicio' (AAAA-MM-DDTHH:MM:SS)."
    return _guard(crear_evento, titulo, inicio, (args.get("fin") or "").strip())


def tool_enviar_correo(args: dict) -> str:
    para = (args.get("para") or "").strip()
    asunto = (args.get("asunto") or "").strip()
    cuerpo = (args.get("cuerpo") or "").strip()
    if not para or not cuerpo:
        return "Indica al menos 'para' y 'cuerpo'."
    return _guard(enviar_correo, para, asunto, cuerpo)


GOOGLE_TOOLS = [
    {
        "name": "google_agenda",
        "description": "Muestra tus proximos eventos de Google Calendar. Opcional 'dias' (defecto 7).",
        "input_schema": {"type": "object",
                         "properties": {"dias": {"type": "integer", "description": "Dias hacia adelante."}},
                         "required": []},
    },
    {
        "name": "google_correos",
        "description": "Muestra tus correos recientes de Gmail (remitente, asunto y resumen). Opcional 'n'.",
        "input_schema": {"type": "object",
                         "properties": {"n": {"type": "integer", "description": "Cuantos correos (defecto 5)."}},
                         "required": []},
    },
    {
        "name": "google_crear_evento",
        "description": ("Crea un evento en Google Calendar. 'titulo' e 'inicio' "
                        "(AAAA-MM-DDTHH:MM:SS); 'fin' opcional (por defecto +1h)."),
        "input_schema": {"type": "object", "properties": {
            "titulo": {"type": "string", "description": "Titulo del evento."},
            "inicio": {"type": "string", "description": "Inicio ISO (AAAA-MM-DDTHH:MM:SS)."},
            "fin": {"type": "string", "description": "Fin ISO opcional."}},
            "required": ["titulo", "inicio"]},
    },
    {
        "name": "google_enviar_correo",
        "description": "Envia un correo por Gmail. 'para' (email), 'asunto' y 'cuerpo'.",
        "input_schema": {"type": "object", "properties": {
            "para": {"type": "string", "description": "Email del destinatario."},
            "asunto": {"type": "string", "description": "Asunto."},
            "cuerpo": {"type": "string", "description": "Texto del correo."}},
            "required": ["para", "cuerpo"]},
    },
]

# Lectura = seguras; acciones (crear evento / enviar correo) = piden confirmacion.
GOOGLE_SEGURAS = {"google_agenda", "google_correos"}
GOOGLE_PELIGROSAS = {"google_crear_evento", "google_enviar_correo"}

GOOGLE_EJECUTORES = {
    "google_agenda": tool_agenda,
    "google_correos": tool_correos,
    "google_crear_evento": tool_crear_evento,
    "google_enviar_correo": tool_enviar_correo,
}


def resumen_accion(name: str, args: dict) -> str:
    if name == "google_crear_evento":
        return f"Crear evento '{args.get('titulo', '')}' el {args.get('inicio', '')}"
    if name == "google_enviar_correo":
        return f"Enviar correo a {args.get('para', '')}: {args.get('asunto', '')}"
    return name


if __name__ == "__main__":
    if not librerias_ok():
        print(_AYUDA)
    else:
        print("Abriendo el navegador para autorizar Google…")
        autorizar()
        print(f"Listo. Token guardado en {TOKEN}.")
