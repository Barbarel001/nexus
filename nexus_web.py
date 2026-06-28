#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS WEB - Interfaz web (HUD) para tu asistente Nexus, con HISTORIAL de
conversaciones persistente (estilo ChatGPT: panel lateral con todas tus charlas),
voz, contador de costo, ajustes y confirmacion en el navegador.

Reutiliza la logica y herramientas de nexus.py. Respuestas en streaming (SSE).

Arranque:
  pip install -r requirements.txt
  python nexus_web.py
(se abre solo en el navegador: http://127.0.0.1:5000)

Las conversaciones se guardan en  conversaciones.json  (junto a este archivo).

SEGURIDAD: por defecto, en la web NO se ejecutan comandos del sistema ni se
escriben archivos (run_command / write_file deshabilitados). Puedes habilitarlos
con la variable de entorno NEXUS_WEB_ACCIONES=1: en ese caso CADA accion peligrosa
requiere tu aprobacion explicita en un modal de confirmacion del navegador.
"""

import os
import sys
import json
import uuid
import datetime
import threading

try:
    import anthropic  # noqa: F401
except ImportError:
    sys.exit("Falta 'anthropic'. Ejecuta: pip install anthropic")
import hmac
try:
    from flask import (Flask, request, Response, send_from_directory, jsonify,
                       session, redirect, render_template_string)
except ImportError:
    sys.exit("Falta 'flask'. Ejecuta: pip install flask")

import anthropic
import nexus_util  # escritura atomica / logging
import nexus  # reutilizamos toda la logica del Nexus de terminal
import nexus_ollama  # backend LOCAL opcional (Ollama), coste $0
import nexus_ninjatrader as nt  # puente con NinjaTrader (trading)
import nexus_tareas as tareas  # productividad (tareas/recordatorios)
import nexus_alertas as alertas  # alertas de precio
import nexus_docs as docs  # RAG-lite sobre documentos
import nexus_noticias as noticias  # titulares de mercado
import nexus_gastos as gastos  # control de gastos
import nexus_clima as clima  # clima
import nexus_google as google  # Google Calendar + Gmail
import nexus_backtest as backtest  # backtesting
import nexus_pagos as pagos  # pagos / suscripciones (Stripe)

CARPETA = os.path.dirname(os.path.abspath(__file__))
CONV_PATH = nexus._env("NEXUS_CONV_PATH", os.path.join(CARPETA, "conversaciones.json"))

# Herramientas seguras, siempre disponibles en la web: lectura general, lectura de
# NinjaTrader (estado/precio/posicion, no mueven dinero) y productividad (tareas).
SEGURAS = ({"recordar", "buscar_memoria", "olvidar_memoria", "rastrear_ofertas",
            "read_file", "list_directory"}
           | nt.NT_SEGURAS | tareas.TAREAS_SEGURAS | alertas.ALERTAS_SEGURAS | docs.DOCS_SEGURAS
           | noticias.NEWS_SEGURAS | gastos.GASTOS_SEGURAS | clima.CLIMA_SEGURAS
           | google.GOOGLE_SEGURAS | backtest.BACKTEST_SEGURAS)
# Herramientas peligrosas (sistema o dinero): solo si NEXUS_WEB_ACCIONES=1, y con
# confirmacion. Fuente unica compartida con la terminal (nexus.py).
PELIGROSAS = nexus.HERRAMIENTAS_PELIGROSAS

WEB_ACCIONES = nexus._env("NEXUS_WEB_ACCIONES", "0").lower() in ("1", "true", "yes", "on")

if WEB_ACCIONES:
    TOOLS_WEB = list(nexus.TOOLS)  # todas; las peligrosas pasan por el modal
    SYSTEM_WEB_EXTRA = (
        "\n\nEstas en la interfaz WEB de Nexus. Puedes usar run_command y write_file, "
        "pero CADA uso requiere que el usuario lo apruebe en un modal de confirmacion "
        "del navegador. Usalas solo cuando de verdad ayuden."
    )
else:
    TOOLS_WEB = [t for t in nexus.TOOLS if t.get("name") not in PELIGROSAS]
    SYSTEM_WEB_EXTRA = (
        "\n\nEstas en la interfaz WEB de Nexus: por seguridad NO tienes run_command ni "
        "write_file. Si el usuario pide ejecutar comandos o escribir archivos, indicale "
        "amablemente que use la version de terminal."
    )

# Modelos que la interfaz puede elegir (el resto cae al de por defecto).
MODELOS_OK = {"claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"}

app = Flask(__name__, static_folder=None)

# ---------------- Autenticacion opcional (para exponer Nexus fuera de casa) -------
# Si defines NEXUS_PASSWORD, Nexus pide login antes de dar acceso. Sin esa variable,
# no hay login (uso local de siempre). Pensado para abrirlo por un tunel publico.
NEXUS_PASSWORD = nexus._env("NEXUS_PASSWORD", "")
# Modo MULTIUSUARIO (SaaS): NEXUS_MULTIUSER=1 activa cuentas (registro/login con
# email+contraseña) sobre SQLite. Si esta off, se usa el modo de una sola
# contraseña (NEXUS_PASSWORD) o ninguno (uso local). Opt-in para no romper nada.
import nexus_db
NEXUS_MULTIUSER = nexus._env("NEXUS_MULTIUSER", "0").lower() in ("1", "true", "yes", "on")
if NEXUS_MULTIUSER:
    nexus_db.init()
app.secret_key = nexus._env("NEXUS_SECRET", "") or os.urandom(24)
app.permanent_session_lifetime = datetime.timedelta(days=30)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

LOGIN_HTML = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>NEXUS — Acceso</title>
<style>
 *{box-sizing:border-box} html,body{height:100%;margin:0}
 body{font-family:system-ui,'Segoe UI',Roboto,sans-serif;background:radial-gradient(900px 500px at 60% -160px,rgba(56,189,248,.10),transparent 70%),#0a0f1a;
   color:#e6edf5;display:flex;align-items:center;justify-content:center}
 .box{width:100%;max-width:340px;padding:30px 26px;background:#121a28;border:1px solid rgba(148,163,184,.20);border-radius:16px;box-shadow:0 24px 60px rgba(0,0,0,.5)}
 .logo{font-family:'Orbitron',sans-serif;font-weight:800;font-size:26px;letter-spacing:6px;text-align:center;margin-bottom:4px;color:#f1f7fb}
 .sub{text-align:center;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#5f6e82;margin-bottom:22px}
 input{width:100%;height:46px;background:#0d1420;border:1px solid rgba(148,163,184,.30);color:#e6edf5;font-size:15px;padding:0 14px;border-radius:11px;outline:none;margin-bottom:14px}
 input:focus{border-color:#38bdf8;box-shadow:0 0 0 3px rgba(56,189,248,.12)}
 button{width:100%;height:46px;background:#38bdf8;border:none;color:#04121d;font-weight:600;font-size:15px;border-radius:11px;cursor:pointer}
 button:hover{filter:brightness(1.08)}
 .err{color:#f87171;font-size:13px;text-align:center;margin-bottom:12px;min-height:18px}
</style></head><body>
 <form class="box" method="POST" action="/login">
   <div class="logo">NEXUS</div><div class="sub">Acceso privado</div>
   <div class="err">{{ error }}</div>
   <input type="password" name="password" placeholder="Contraseña" autofocus autocomplete="current-password">
   <button type="submit">Entrar</button>
 </form>
</body></html>"""

# Pagina de login/registro para el modo multiusuario (email + contraseña).
MULTIUSER_LOGIN_HTML = LOGIN_HTML.replace(
    '<div class="sub">Acceso privado</div>',
    '<div class="sub">{{ modo_sub }}</div>'
).replace(
    '<input type="password" name="password" placeholder="Contraseña" autofocus autocomplete="current-password">\n   <button type="submit">Entrar</button>',
    '<input type="email" name="email" placeholder="Email" autofocus autocomplete="email">\n'
    '   <input type="password" name="password" placeholder="Contraseña" autocomplete="current-password">\n'
    '   <button type="submit" formaction="/login">Entrar</button>\n'
    '   <div style="text-align:center;margin-top:12px;font-size:13px;color:#94a6bd">¿Sin cuenta?</div>\n'
    '   <button type="submit" formaction="/register" style="background:transparent;color:#38bdf8;border:1px solid rgba(56,189,248,.3);margin-top:8px">Crear cuenta</button>'
)


def _auth_requerida() -> bool:
    return bool(NEXUS_MULTIUSER or NEXUS_PASSWORD)


@app.before_request
def _guardia_acceso():
    """Exige login si hay multiusuario o NEXUS_PASSWORD. La landing y los iconos
    son publicos."""
    if not _auth_requerida():
        return None
    if request.endpoint in ("login", "register", "landing", "landing_en", "stripe_webhook",
                            "health", "icon192", "icon512", "manifest") or session.get("auth"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "no autorizado"}), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _auth_requerida():
        return redirect("/")
    error = ""
    if NEXUS_MULTIUSER:
        if request.method == "POST":
            u = nexus_db.autenticar(request.form.get("email", ""), request.form.get("password", ""))
            if u:
                session["auth"] = True
                session["user_id"] = u["id"]
                session["email"] = u["email"]
                session.permanent = True
                return redirect("/")
            error = "Email o contraseña incorrectos."
        return render_template_string(MULTIUSER_LOGIN_HTML, error=error, modo_sub="Inicia sesión")
    # Modo de una sola contraseña.
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), NEXUS_PASSWORD):
            session["auth"] = True
            session.permanent = True
            return redirect("/")
        error = "Contraseña incorrecta."
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/register", methods=["POST"])
def register():
    if not NEXUS_MULTIUSER:
        return redirect("/login")
    try:
        u = nexus_db.crear_usuario(request.form.get("email", ""), request.form.get("password", ""))
    except ValueError as e:
        return render_template_string(MULTIUSER_LOGIN_HTML, error=str(e), modo_sub="Crear cuenta")
    session["auth"] = True
    session["user_id"] = u["id"]
    session["email"] = u["email"]
    session.permanent = True
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# Registro de confirmaciones pendientes (handshake SSE <-> /api/confirm).
_pendientes = {}
_lock = threading.Lock()


# ---------------- Persistencia de conversaciones ----------------

def cargar_convs() -> dict:
    try:
        with open(CONV_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"convs": []}


def guardar_convs(data: dict) -> None:
    nexus_util.guardar_json(CONV_PATH, data)


def buscar_conv(data: dict, cid: str):
    for c in data["convs"]:
        if c["id"] == cid:
            return c
    return None


def ahora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------- Ejecucion de herramientas ----------------

def ejecutar_web(name: str, args: dict) -> str:
    """Ejecuta una herramienta de SOLO LECTURA (segura) reutilizando nexus.py."""
    if name in SEGURAS:
        try:
            return nexus.EJECUTORES[name](args)
        except Exception as e:
            return f"Error en {name}: {e}"
    return (f"La herramienta '{name}' esta deshabilitada en la web por seguridad. "
            "Indica al usuario que use la terminal.")


def ejecutar_peligrosa(name: str, args: dict) -> str:
    """Ejecuta una accion peligrosa YA APROBADA por el usuario (modal)."""
    if name == "run_command":
        return nexus.ejecutar_powershell(args.get("command", ""))
    if name == "write_file":
        return nexus.escribir_archivo(args.get("path", ""), args.get("content", ""))
    if name in nt.NT_PELIGROSAS:  # ordenes de NinjaTrader (ya aprobadas en el modal)
        return nt.NT_EJECUTORES[name](args)
    if name in google.GOOGLE_PELIGROSAS:  # crear evento / enviar correo (ya aprobado)
        return google.GOOGLE_EJECUTORES[name](args)
    return f"Herramienta desconocida: {name}"


def resumen_accion(name: str, args: dict) -> str:
    if name == "run_command":
        return args.get("command", "")
    if name == "write_file":
        n = len(args.get("content", "") or "")
        return f"Escribir archivo: {args.get('path', '')}   ({n} caracteres)"
    if name == "nt_orden":
        return f"Orden NinjaTrader: {nt.resumen_orden(args)}"
    if name == "nt_cancelar":
        return "Cancelar TODAS las ordenes" if (args.get("todas") or not args.get("order_id")) \
            else f"Cancelar orden {args.get('order_id')}"
    if name == "nt_cerrar":
        return "Aplanar TODO en NinjaTrader" if (args.get("todo") or not args.get("instrument")) \
            else f"Cerrar posicion {args.get('instrument')}"
    if name in google.GOOGLE_PELIGROSAS:
        return google.resumen_accion(name, args)
    return name


def detalle_tool(name: str, args: dict) -> str:
    """Resumen corto y legible de la ENTRADA de una herramienta (para persistir y
    mostrar los bloques de tool-use al recargar)."""
    especifico = resumen_accion(name, args)
    if especifico != name:
        return especifico
    # Generico: muestra los argumentos no vacios, recortados.
    partes = []
    for k, v in (args or {}).items():
        v = str(v)
        if v:
            partes.append(f"{k}={v[:60]}")
    return ", ".join(partes)[:200]


def modelo_pedido() -> str:
    m = (request.args.get("model") or "").strip()
    return m if m in MODELOS_OK else nexus.MODEL


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------- Rutas ----------------

# Carpeta de assets web. Si Nexus corre como .exe (PyInstaller), los archivos van
# empaquetados bajo sys._MEIPASS; si no, junto a este script.
WEBDIR = os.path.join(getattr(sys, "_MEIPASS", CARPETA), "web")


@app.route("/")
@app.route("/app")
def index():
    return send_from_directory(WEBDIR, "index.html")


@app.route("/landing")
@app.route("/inicio")
def landing():
    """Pagina de marketing en español (no requiere login)."""
    return send_from_directory(WEBDIR, "landing.html")


@app.route("/en")
@app.route("/landing/en")
def landing_en():
    """Marketing landing page in English (public)."""
    return send_from_directory(WEBDIR, "landing-en.html")


# --- PWA: manifest, service worker e iconos (servidos desde la raiz) ---

@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(WEBDIR, "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory(WEBDIR, "sw.js", mimetype="application/javascript")


@app.route("/icon-192.png")
def icon192():
    return send_from_directory(WEBDIR, "icon-192.png")


@app.route("/icon-512.png")
def icon512():
    return send_from_directory(WEBDIR, "icon-512.png")


@app.route("/api/config")
def config():
    return jsonify({"acciones": WEB_ACCIONES, "modelo": nexus.MODEL, "modelos": sorted(MODELOS_OK),
                    "backend": nexus.BACKEND, "ollama_model": nexus_ollama.OLLAMA_MODEL,
                    "ollama_disponible": nexus_ollama.disponible()})


@app.route("/api/checkout")
def checkout_api():
    """Crea una sesión de pago (Stripe) para un plan y devuelve la URL de Checkout."""
    plan = request.args.get("plan", "pro")
    email = session.get("email", "") if NEXUS_MULTIUSER else ""
    try:
        url = pagos.crear_checkout(plan, email)
    except (ValueError, RuntimeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "url": url})


@app.route("/api/health")
@app.route("/healthz")
def health():
    """Endpoint de salud para balanceadores/monitores de uptime (publico)."""
    return jsonify({"ok": True, "service": "nexus", "multiuser": NEXUS_MULTIUSER})


@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Webhook de Stripe: al completar el pago, activa el plan del usuario."""
    try:
        evento = pagos.verificar_webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if evento.get("type") == "checkout.session.completed":
        sesion = evento.get("data", {}).get("object", {})
        email = sesion.get("customer_email") or (sesion.get("customer_details") or {}).get("email")
        plan = (sesion.get("metadata") or {}).get("plan", "pro")
        if email:
            u = nexus_db.usuario_por_email(email)
            if u:
                nexus_db.cambiar_plan(u["id"], plan)
    return jsonify({"ok": True})


@app.route("/api/setup-status")
def setup_status():
    """Qué está configurado, para el asistente de onboarding."""
    return jsonify({
        "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "ollama": nexus_ollama.disponible(),
        "ninjatrader": nt.carpeta_ok(),
        "telegram": bool(nexus._env("NEXUS_TELEGRAM_TOKEN", "")),
        "google": google.configurado(),
    })


@app.route("/api/panel")
def panel():
    """Datos para el panel-dashboard: estado de NinjaTrader y tareas pendientes."""
    return jsonify({
        "nt": {"ok": nt.carpeta_ok(), "carpeta": nt.NT_FOLDER, "cuenta": nt.NT_ACCOUNT},
        "tareas": [tareas.dto(t) for t in tareas.filtrar("pendientes")],
        "resumen": tareas.resumen_pendientes(),
    })


@app.route("/api/memoria")
def memoria_api():
    """Lista la memoria a largo plazo (para gestionarla desde el panel)."""
    return jsonify({"notas": nexus.cargar_notas()})


@app.route("/api/memoria/agregar", methods=["POST"])
def memoria_agregar_api():
    body = request.get_json(silent=True) or {}
    texto = (body.get("texto") or "").strip()
    if not texto:
        return jsonify({"ok": False, "error": "texto vacio"}), 400
    ok = nexus.guardar_nota(texto, (body.get("categoria") or "general"))
    return jsonify({"ok": ok})


@app.route("/api/memoria/olvidar", methods=["POST"])
def memoria_olvidar_api():
    body = request.get_json(silent=True) or {}
    ref = (body.get("ref") or "").strip()
    if not ref:
        return jsonify({"ok": False, "error": "falta ref"}), 400
    msg = nexus.olvidar_nota(ref)
    return jsonify({"ok": "olvidado" in msg.lower(), "msg": msg})


@app.route("/api/diario")
def diario_api():
    """Diario de trading (resumen de la bitacora) para el panel."""
    return jsonify({"texto": nt.diario()})


@app.route("/api/noticias")
def noticias_api():
    """Titulares de mercado para el panel."""
    return jsonify({"texto": noticias.tool_noticias({})})


@app.route("/api/clima")
def clima_api():
    """Clima de una ciudad (o la de por defecto) para el panel."""
    return jsonify({"texto": clima.tool_clima({"ciudad": request.args.get("ciudad", "")})})


@app.route("/api/gastos")
def gastos_api():
    """Resumen de gastos del mes para el panel."""
    return jsonify({"texto": gastos.tool_resumen_gastos({"mes": request.args.get("mes", "")})})


@app.route("/api/gasto/agregar", methods=["POST"])
def gasto_agregar_api():
    """Registra un gasto desde el panel."""
    body = request.get_json(silent=True) or {}
    try:
        g = gastos.agregar(body.get("monto"), body.get("categoria", "general"),
                           body.get("descripcion", ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "gasto": g})


@app.route("/api/nt/precio")
def nt_precio_api():
    """Precio de un instrumento via NinjaTrader (para la watchlist del panel)."""
    inst = (request.args.get("instrument") or "").strip()
    tipo = (request.args.get("tipo") or "LAST").strip().upper()
    if not inst:
        return jsonify({"ok": False, "error": "falta el instrumento"}), 400
    try:
        valor = nt.leer_precio(inst, tipo)
        return jsonify({"ok": True, "instrument": inst.upper(), "tipo": tipo, "precio": valor})
    except Exception as e:
        return jsonify({"ok": False, "instrument": inst.upper(), "error": str(e)})


@app.route("/api/tarea/completar", methods=["POST"])
def completar_tarea_api():
    """Marca una tarea como completada desde el panel."""
    body = request.get_json(silent=True) or {}
    ref = (body.get("ref") or "").strip()
    if not ref:
        return jsonify({"ok": False, "error": "falta ref"}), 400
    msg = tareas.completar(ref)
    return jsonify({"ok": "completada" in msg.lower(), "msg": msg})


@app.route("/api/tarea/agregar", methods=["POST"])
def agregar_tarea_api():
    """Crea una tarea desde el panel."""
    body = request.get_json(silent=True) or {}
    try:
        t = tareas.agregar(body.get("texto", ""), body.get("vence", ""), body.get("prioridad", "media"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "tarea": tareas.dto(t)})


@app.route("/api/alertas")
def alertas_api():
    """Lista las alertas y, de paso, las evalua: las que se disparan se devuelven en
    'disparadas' para que el navegador notifique."""
    disparadas = alertas.evaluar()
    return jsonify({"alertas": [alertas.dto(a) for a in alertas.cargar()],
                    "disparadas": disparadas})


@app.route("/api/alerta", methods=["POST"])
def crear_alerta_api():
    body = request.get_json(silent=True) or {}
    try:
        a = alertas.agregar(body.get("instrument", ""), body.get("condicion", ">="), body.get("precio"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "alerta": alertas.dto(a)})


@app.route("/api/alerta/eliminar", methods=["POST"])
def eliminar_alerta_api():
    body = request.get_json(silent=True) or {}
    ref = (body.get("ref") or "").strip()
    if not ref:
        return jsonify({"ok": False, "error": "falta ref"}), 400
    msg = alertas.eliminar(ref)
    return jsonify({"ok": "eliminada" in msg.lower(), "msg": msg})


@app.route("/api/conversaciones")
def listar_convs():
    data = cargar_convs()
    return jsonify([{"id": c["id"], "titulo": c["titulo"], "creado": c.get("creado", "")}
                    for c in data["convs"]])


@app.route("/api/conversacion/<cid>")
def obtener_conv(cid):
    data = cargar_convs()
    c = buscar_conv(data, cid)
    if not c:
        return jsonify({"error": "no existe"}), 404
    return jsonify({"id": c["id"], "titulo": c["titulo"], "turnos": c["turnos"]})


@app.route("/api/conversacion/<cid>/borrar", methods=["POST"])
def borrar_conv(cid):
    data = cargar_convs()
    data["convs"] = [c for c in data["convs"] if c["id"] != cid]
    guardar_convs(data)
    return jsonify({"ok": True})


@app.route("/api/conversacion/<cid>/renombrar", methods=["POST"])
def renombrar_conv(cid):
    body = request.get_json(silent=True) or {}
    titulo = (body.get("titulo") or "").strip()[:60]
    if not titulo:
        return jsonify({"ok": False, "error": "titulo vacio"}), 400
    data = cargar_convs()
    c = buscar_conv(data, cid)
    if not c:
        return jsonify({"ok": False, "error": "no existe"}), 404
    c["titulo"] = titulo
    guardar_convs(data)
    return jsonify({"ok": True, "titulo": titulo})


@app.route("/api/nueva", methods=["POST"])
def nueva_conv():
    # Devuelve un id; la conversacion se persiste al primer mensaje.
    return jsonify({"id": uuid.uuid4().hex[:12]})


@app.route("/api/confirm", methods=["POST"])
def confirmar():
    """El navegador aprueba/deniega una accion peligrosa pendiente."""
    body = request.get_json(silent=True) or {}
    rid = (body.get("rid") or "").strip()
    ok = bool(body.get("ok"))
    with _lock:
        estado = _pendientes.get(rid)
        if estado:
            estado["ok"] = ok
            estado["event"].set()
    return jsonify({"ok": bool(estado)})


@app.route("/api/vision", methods=["POST"])
def vision_api():
    """Analiza una imagen con la vision de Claude y la guarda en la conversacion."""
    body = request.get_json(silent=True) or {}
    data = (body.get("image") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    cid = (body.get("cid") or "").strip()
    if not data:
        return jsonify({"ok": False, "error": "falta la imagen"}), 400
    # Acepta data-URL (data:image/png;base64,XXXX) o base64 puro.
    media_type = "image/jpeg"
    if data.startswith("data:"):
        try:
            cabecera, data = data.split(",", 1)
            media_type = cabecera.split(":", 1)[1].split(";", 1)[0] or media_type
        except (ValueError, IndexError):
            return jsonify({"ok": False, "error": "imagen invalida"}), 400
    try:
        texto, usage = nexus.analizar_imagen(data, media_type, prompt)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    # Persistimos el turno (la imagen no se guarda; sí el prompt y la respuesta).
    if cid:
        convs = cargar_convs()
        conv = buscar_conv(convs, cid)
        if conv is None:
            conv = {"id": cid, "titulo": (prompt or "Imagen")[:42], "creado": ahora(), "turnos": []}
            convs["convs"].insert(0, conv)
        conv["turnos"].append({"role": "user", "text": "🖼️ " + (prompt or "(imagen)")})
        conv["turnos"].append({"role": "assistant", "text": texto, "tools": ["vision"]})
        guardar_convs(convs)
    costo = round(nexus.costo_estimado(nexus.MODEL, usage.get("in", 0), usage.get("out", 0)), 5)
    return jsonify({"ok": True, "texto": texto, "usage": usage, "costo": costo})


@app.route("/api/stream")
def stream():
    msg = (request.args.get("msg") or "").strip()
    cid = (request.args.get("cid") or "").strip()
    if not msg or not cid:
        return Response(sse("done", {}), mimetype="text/event-stream")

    model = modelo_pedido()
    usar_ollama = nexus.BACKEND == "ollama" or (request.args.get("model") or "") == "ollama"
    regen = (request.args.get("regen") or "") == "1"
    nombre = (request.args.get("nombre") or "").strip()[:40]
    system_prompt = nexus.construir_system_prompt() + SYSTEM_WEB_EXTRA
    if nombre:
        system_prompt += f"\n\nEl usuario prefiere que lo llames: {nombre}."

    def gen():
        data = cargar_convs()
        conv = buscar_conv(data, cid)
        nueva = conv is None
        if nueva:
            conv = {"id": cid, "titulo": msg[:42] or "Conversacion",
                    "creado": ahora(), "turnos": []}
            data["convs"].insert(0, conv)
        elif regen and len(conv["turnos"]) >= 2:
            # Regenerar: descartamos el ultimo par (usuario + asistente) para rehacerlo.
            conv["turnos"] = conv["turnos"][:-2]

        # Reconstruimos el contexto (texto simple) y agregamos el nuevo mensaje.
        api_messages = [{"role": t["role"], "content": t["text"]} for t in conv["turnos"]]
        api_messages.append({"role": "user", "content": msg})
        api_messages = nexus.recortar_contexto(api_messages)

        texto_final = ""
        tin = tout = 0
        tools_usados = []
        tool_calls = []  # bloques completos: {name, detalle, resultado} para persistir

        # ---- Backend LOCAL (Ollama): coste 0, sin tokens de la API ----
        if usar_ollama:
            oll_msgs = [{"role": t["role"], "content": t["text"]} for t in conv["turnos"]]
            oll_msgs.append({"role": "user", "content": msg})
            oll_msgs = nexus.recortar_contexto(oll_msgs)
            try:
                for evt, pl in nexus_ollama.chat_eventos(
                        oll_msgs, system_prompt, nexus_ollama.tools_ollama(False), ejecutar_web):
                    if evt == "delta":
                        texto_final += pl
                        yield sse("delta", {"text": pl})
                    elif evt == "tool":
                        tools_usados.append(pl)
                        yield sse("tool", {"name": pl})
                    elif evt == "fin":
                        tin, tout = pl["in"], pl["out"]
                        if pl["text"]:
                            texto_final = pl["text"]
            except Exception as e:
                yield sse("error", {"msg": f"Ollama: {e}"})
            conv["turnos"].append({"role": "user", "text": msg})
            conv["turnos"].append({"role": "assistant", "text": texto_final,
                                   "tools": list(dict.fromkeys(tools_usados))})
            guardar_convs(data)
            if tin or tout:
                yield sse("usage", {"in": tin, "out": tout,
                                    "modelo": nexus_ollama.OLLAMA_MODEL, "costo": 0})
            yield sse("done", {"cid": cid, "nueva": nueva, "titulo": conv["titulo"]})
            return

        # ---- Backend Claude (API de Anthropic) ----
        client = anthropic.Anthropic()
        # Si la cuenta/modelo no admite funciones avanzadas (thinking adaptativo o la
        # busqueda web del servidor), reintentamos automaticamente en "modo compatible"
        # (sin thinking y sin web_search) en vez de fallar con un error.
        degradado = False
        try:
            for _ in range(10):
                tools_actuales = TOOLS_WEB if not degradado else [
                    t for t in TOOLS_WEB if not str(t.get("type", "")).startswith("web_search")]
                _kw = dict(model=model, max_tokens=nexus.MAX_TOKENS, system=system_prompt,
                           tools=tools_actuales, messages=api_messages)
                _th = None if degradado else nexus.thinking_para(model)
                if _th:
                    _kw["thinking"] = _th
                try:
                    with client.messages.stream(**_kw) as s:
                        for texto in s.text_stream:
                            texto_final += texto
                            yield sse("delta", {"text": texto})
                        final = s.get_final_message()
                except Exception as e:
                    # Solo reintentamos si aun no hay texto (error de validacion inicial).
                    if not degradado and not texto_final:
                        degradado = True
                        nexus_util.log(f"Claude: reintentando en modo compatible ({e})", "WARN")
                        continue
                    raise

                if getattr(final, "usage", None):
                    tin += final.usage.input_tokens
                    tout += final.usage.output_tokens

                api_messages.append({"role": "assistant", "content": final.content})

                if final.stop_reason == "end_turn":
                    break
                if final.stop_reason == "pause_turn":
                    continue
                if final.stop_reason == "tool_use":
                    resultados = []
                    for b in final.content:
                        if b.type != "tool_use":
                            continue
                        tools_usados.append(b.name)
                        if b.name in PELIGROSAS and WEB_ACCIONES:
                            # --- Handshake de confirmacion con el navegador ---
                            rid = uuid.uuid4().hex[:10]
                            ev = threading.Event()
                            with _lock:
                                _pendientes[rid] = {"event": ev, "ok": False}
                            yield sse("confirm", {
                                "rid": rid, "name": b.name,
                                "resumen": resumen_accion(b.name, b.input),
                            })
                            aprobado = ev.wait(timeout=150)
                            with _lock:
                                estado = _pendientes.pop(rid, None)
                            if aprobado and estado and estado["ok"]:
                                yield sse("tool", {"name": b.name})
                                salida = ejecutar_peligrosa(b.name, b.input)
                            else:
                                salida = ("El usuario no aprobo la accion "
                                          "(denegada o sin respuesta a tiempo).")
                        else:
                            yield sse("tool", {"name": b.name})
                            salida = ejecutar_web(b.name, b.input)
                        resultados.append({
                            "type": "tool_result",
                            "tool_use_id": b.id,
                            "content": salida,
                        })
                        tool_calls.append({"name": b.name, "detalle": detalle_tool(b.name, b.input),
                                           "resultado": str(salida)[:500]})
                    api_messages.append({"role": "user", "content": resultados})
                    continue
                break
        except Exception as e:
            yield sse("error", {"msg": str(e)})

        # Persistimos el turno (texto + bloques de tool-use, para re-renderizar al recargar).
        conv["turnos"].append({"role": "user", "text": msg})
        conv["turnos"].append({"role": "assistant", "text": texto_final,
                               "tools": list(dict.fromkeys(tools_usados)),
                               "tool_calls": tool_calls})
        guardar_convs(data)

        if tin or tout:
            yield sse("usage", {
                "in": tin, "out": tout, "modelo": model,
                "costo": round(nexus.costo_estimado(model, tin, tout), 5),
            })
        yield sse("done", {"cid": cid, "nueva": nueva, "titulo": conv["titulo"]})

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main():
    if nexus.BACKEND != "ollama" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit('Falta ANTHROPIC_API_KEY. Configurala con:  setx ANTHROPIC_API_KEY "sk-ant-..."')
    import webbrowser
    port = int(nexus._env("NEXUS_PORT", "5000"))
    # Por seguridad escucha solo en 127.0.0.1 (solo esta PC). Para abrir Nexus desde
    # el movil en tu red local (misma WiFi), arranca con NEXUS_HOST=0.0.0.0 y entra
    # desde el telefono a http://<IP-de-tu-PC>:5000  (averigua la IP con 'ipconfig').
    host = nexus._env("NEXUS_HOST", "127.0.0.1")
    url = f"http://127.0.0.1:{port}"
    if nexus._env("NEXUS_OPEN", "1").lower() not in ("0", "false", "no"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    extra = "  [acciones de sistema ON]" if WEB_ACCIONES else ""
    red = "  [accesible en tu red local]" if host not in ("127.0.0.1", "localhost") else ""
    print(f"NEXUS web encendido en {url}{extra}{red}   (Ctrl+C para detener)")
    if host not in ("127.0.0.1", "localhost") and not NEXUS_PASSWORD:
        print("  AVISO: estas exponiendo Nexus sin contrasena. Define NEXUS_PASSWORD "
              "para protegerlo antes de abrirlo fuera de tu red.")
    # Canales proactivos: bot de Telegram + scheduler (resumen matutino / alertas).
    _arrancar_proactivo()
    app.run(host=host, port=port, threaded=True)


def _arrancar_proactivo():
    """Arranca, en hilos daemon, el bot de Telegram y el scheduler si estan configurados."""
    try:
        import nexus_telegram, nexus_scheduler
        if nexus_telegram.configurado():
            threading.Thread(target=nexus_telegram.run, daemon=True, name="nexus-telegram").start()
            nexus_scheduler.iniciar_en_hilo()
            print("  [Telegram + scheduler proactivo activos]")
            nexus_util.log("Modo proactivo iniciado (Telegram + scheduler)")
    except Exception as e:
        print(f"  (no se pudo iniciar el modo proactivo: {e})")
        nexus_util.log(f"Fallo al iniciar modo proactivo: {e}", "ERROR")


if __name__ == "__main__":
    main()
