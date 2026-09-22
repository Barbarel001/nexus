#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RECEPCIONISTA IA — PANEL del dueño (multi-tenant).

Cada negocio (nexus_recepcion_saas) tiene su propio panel privado en /panel/<slug>
donde el dueño entra con contraseña y puede:
  - ver y filtrar sus leads y cambiar su estado (nuevo/contactado/ganado/perdido),
  - añadir/actualizar sus servicios (tarifas aprobadas) y sus FAQ.

Todo esta AISLADO por negocio: una sesion del negocio A jamas puede leer ni tocar
los datos del negocio B. Reutiliza el CRUD y la logica de precios de
nexus_recepcion_saas (una sola fuente de verdad; la IA sigue sin inventar precios).

Auth de piloto (a proposito, minima): una contraseña por negocio, guardada como
hash PBKDF2 en la columna `owner_hash`. Sesion por cookie con token en memoria y
caducidad. Es suficiente para un piloto; el endurecimiento real (cuentas de
persona, sesiones firmadas) llega con el modulo de cobro.

Opt-in con el mismo flag NEXUS_RECEPCION_SAAS=1.

Configurable por entorno:
    NEXUS_PANEL_TTL   Vida de la sesion del panel, en segundos (defecto 28800 = 8h).
"""

import os
import secrets
import sqlite3
import time

import nexus_db
import nexus_recepcion_saas as saas

try:
    SESSION_TTL = int(os.environ.get("NEXUS_PANEL_TTL") or 28800)
except ValueError:
    SESSION_TTL = 28800

COOKIE = "recep_panel"
_TOKENS = {}  # token -> {"slug", "ts"}  (sesiones del panel, en memoria del proceso)


# --------------------------- Base de datos / migracion ---------------------------

def _conn():
    conn = sqlite3.connect(nexus_db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Asegura la capa SaaS y añade la columna owner_hash a negocios. Idempotente."""
    saas.init()
    with _conn() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(negocios)").fetchall()}
        if "owner_hash" not in cols:
            c.execute("ALTER TABLE negocios ADD COLUMN owner_hash TEXT")


# --------------------------- Contraseña del dueño ---------------------------

def fijar_password(slug: str, password: str) -> None:
    """Fija/cambia la contraseña del panel de un negocio. Lanza ValueError si el
    negocio no existe o la contraseña es corta."""
    if saas.obtener_negocio(slug) is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    if len(password or "") < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    init()
    with _conn() as c:
        c.execute("UPDATE negocios SET owner_hash=? WHERE slug=?",
                  (nexus_db._hash_password(password), slug))


def tiene_password(slug: str) -> bool:
    init()
    with _conn() as c:
        row = c.execute("SELECT owner_hash FROM negocios WHERE slug=?", (slug,)).fetchone()
    return bool(row and row["owner_hash"])


def verificar_password(slug: str, password: str) -> bool:
    init()
    with _conn() as c:
        row = c.execute("SELECT owner_hash FROM negocios WHERE slug=?", (slug,)).fetchone()
    if not row or not row["owner_hash"]:
        return False
    return nexus_db._verificar_password(password or "", row["owner_hash"])


# --------------------------- Sesiones (token en memoria) ---------------------------

def crear_token(slug: str) -> str:
    token = secrets.token_urlsafe(24)
    _TOKENS[token] = {"slug": slug, "ts": time.time()}
    return token


def slug_de_token(token: str):
    """Devuelve el slug de una sesion valida, o None si no existe/caduco."""
    ses = _TOKENS.get(token or "")
    if not ses:
        return None
    if time.time() - ses["ts"] > SESSION_TTL:
        _TOKENS.pop(token, None)
        return None
    return ses["slug"]


def cerrar(token: str) -> None:
    _TOKENS.pop(token or "", None)


def _autorizado(token: str, slug: str) -> bool:
    """True solo si el token es una sesion valida DE ESE negocio (aislamiento)."""
    return slug_de_token(token) == slug


# --------------------------- Panel (Flask blueprint) ---------------------------

_LOGIN = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Panel — {nombre}</title>
<style>
:root{{color-scheme:light dark}}
body{{font-family:system-ui,sans-serif;margin:0;background:#f4f4f5;color:#18181b;display:grid;place-items:center;height:100vh}}
@media(prefers-color-scheme:dark){{body{{background:#0b0b0c;color:#e5e5e5}}}}
form{{background:#8881;padding:24px;border-radius:14px;width:min(92vw,340px)}}
h1{{font-size:1.2rem;margin:0 0 12px}}
input{{width:100%;padding:10px;border-radius:10px;border:1px solid #8886;background:transparent;color:inherit;margin:6px 0}}
button{{width:100%;padding:11px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;margin-top:8px}}
.err{{color:#dc2626;font-size:.9rem;min-height:1.2em}}
</style></head><body>
<form method="post" action="/panel/{slug}/login">
<h1>Panel de {nombre}</h1>
<input name="password" type="password" placeholder="Contraseña" required autofocus>
<div class="err">{error}</div>
<button>Entrar</button>
</form></body></html>"""

_PANEL = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Panel — {nombre}</title>
<style>
:root{{color-scheme:light dark;--fg:#18181b;--bg:#fff;--muted:#6b7280;--card:#f4f4f5;--acc:#2563eb}}
@media(prefers-color-scheme:dark){{:root{{--fg:#e5e5e5;--bg:#0b0b0c;--muted:#9ca3af;--card:#17171a}}}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,sans-serif;color:var(--fg);background:var(--bg)}}
.wrap{{max-width:900px;margin:0 auto;padding:16px}}
header{{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}}
h1{{font-size:1.2rem;margin:0}}
.tabs{{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}}
.tabs button,.f button{{padding:6px 12px;border:1px solid #8886;border-radius:999px;background:transparent;color:inherit;cursor:pointer}}
.tabs button.on{{background:var(--acc);color:#fff;border-color:var(--acc)}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid #8883;font-size:.92rem;vertical-align:top}}
select,input,textarea{{padding:6px;border-radius:8px;border:1px solid #8886;background:transparent;color:inherit;font:inherit}}
.badge{{font-size:.75rem;padding:2px 8px;border-radius:999px;background:#8882}}
.q{{color:#16a34a;font-weight:600}}
.card{{background:var(--card);border-radius:12px;padding:14px;margin-top:14px}}
.row{{display:grid;gap:8px;grid-template-columns:1fr 1fr;margin-bottom:8px}}
.row input{{width:100%}}
button.act{{padding:9px 14px;border:0;border-radius:10px;background:var(--acc);color:#fff;font-weight:600;cursor:pointer}}
a.logout{{color:var(--muted);font-size:.9rem}}
.muted{{color:var(--muted)}}
</style></head><body><div class="wrap">
<header><h1>{nombre}</h1><a class="logout" href="/panel/{slug}/logout">Salir</a></header>
<p class="muted">Chat publico: <code>/r/{slug}</code></p>
<div class="tabs" id="filtros">
<button data-f="todos" class="on">Todos</button><button data-f="nuevos">Nuevos</button>
<button data-f="cualificados">Cualificados</button><button data-f="ganados">Ganados</button>
<button data-f="perdidos">Perdidos</button></div>
<table><thead><tr><th>Creado</th><th>Cliente</th><th>Servicio</th><th>Detalles</th><th>Estado</th></tr></thead>
<tbody id="leads"></tbody></table>

<div class="card"><h3>Añadir servicio (tarifa)</h3>
<div class="row"><input id="s_nombre" placeholder="Nombre (p. ej. limpieza casa)">
<input id="s_base" type="number" placeholder="Precio base"></div>
<div class="row"><input id="s_unidad" placeholder="Unidad (habitacion, m2…)">
<input id="s_por" type="number" placeholder="Precio por unidad extra"></div>
<button class="act" onclick="addServicio()">Guardar servicio</button> <span id="s_msg" class="muted"></span></div>

<div class="card"><h3>Añadir FAQ</h3>
<div class="row"><input id="q_p" placeholder="Pregunta"><input id="q_r" placeholder="Respuesta"></div>
<button class="act" onclick="addFaq()">Guardar FAQ</button> <span id="q_msg" class="muted"></span></div>
</div>
<script>
const slug={slug_json}, base="/panel/"+slug, ESTADOS=["nuevo","contactado","ganado","perdido"];
let filtro="todos";
async function api(path,opt){{const r=await fetch(path,opt);if(!r.ok)throw new Error(r.status);return r.json();}}
function esc(s){{return (s||"").replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));}}
async function cargar(){{
 const j=await api(base+'/api/leads?filtro='+filtro);
 document.getElementById('leads').innerHTML = j.leads.length? j.leads.map(l=>{{
  const sel='<select onchange="marcar(\\''+l.id+'\\',this.value)">'+ESTADOS.map(e=>'<option '+(e===l.estado?'selected':'')+'>'+e+'</option>').join('')+'</select>';
  const q=l.calificado?' <span class="q">★</span>':'';
  return '<tr><td class="muted">'+esc(l.creado)+'</td><td>'+esc(l.nombre||'—')+q+'<br><span class="muted">'+esc(l.contacto)+'</span></td><td>'+esc(l.servicio)+'</td><td>'+esc(l.detalles)+'</td><td>'+sel+'</td></tr>';
 }}).join(''):'<tr><td colspan=5 class="muted">Sin leads todavia.</td></tr>';
}}
async function marcar(id,estado){{await api(base+'/api/lead/'+id+'/estado',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{estado}})}});cargar();}}
document.getElementById('filtros').addEventListener('click',e=>{{if(e.target.dataset.f){{filtro=e.target.dataset.f;
 document.querySelectorAll('#filtros button').forEach(b=>b.classList.toggle('on',b===e.target));cargar();}}}});
async function addServicio(){{const m=document.getElementById('s_msg');try{{
 await api(base+'/api/servicio',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{
  nombre:document.getElementById('s_nombre').value,base:parseFloat(document.getElementById('s_base').value),
  unidad:document.getElementById('s_unidad').value,por_unidad:parseFloat(document.getElementById('s_por').value||'0')}})}});
 m.textContent='Guardado.';}}catch(e){{m.textContent='Revisa los datos.';}}}}
async function addFaq(){{const m=document.getElementById('q_msg');try{{
 await api(base+'/api/faq',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{
  pregunta:document.getElementById('q_p').value,respuesta:document.getElementById('q_r').value}})}});
 m.textContent='Guardada.';}}catch(e){{m.textContent='Revisa los datos.';}}}}
cargar();
</script></body></html>"""


def crear_blueprint():
    """Blueprint del panel del dueño:
        GET  /panel/<slug>                 login o dashboard (segun sesion)
        POST /panel/<slug>/login           valida contraseña, abre sesion
        GET  /panel/<slug>/logout          cierra sesion
        GET  /panel/<slug>/api/leads       leads del negocio (filtro=...)
        POST /panel/<slug>/api/lead/<id>/estado   cambia estado de un lead
        POST /panel/<slug>/api/servicio    añade/actualiza una tarifa
        POST /panel/<slug>/api/faq         añade una FAQ
    Todo exige sesion valida DEL MISMO negocio (aislamiento)."""
    from flask import Blueprint, abort, jsonify, make_response, redirect, request

    bp = Blueprint("recepcion_panel", __name__)

    def _negocio_o_404(slug):
        n = saas.obtener_negocio(slug)
        if n is None:
            abort(404)
        return n

    def _auth_o_none(slug):
        return _autorizado(request.cookies.get(COOKIE, ""), slug)

    def _api_guard(slug):
        _negocio_o_404(slug)
        if not _auth_o_none(slug):
            abort(401)

    @bp.get("/panel/<slug>")
    def panel(slug):
        n = _negocio_o_404(slug)
        nombre = (n.get("nombre", "Panel")).replace("<", "&lt;").replace(">", "&gt;")
        if _auth_o_none(slug):
            import json as _json
            return _PANEL.format(nombre=nombre, slug=slug, slug_json=_json.dumps(slug))
        return _LOGIN.format(nombre=nombre, slug=slug, error="")

    @bp.post("/panel/<slug>/login")
    def login(slug):
        n = _negocio_o_404(slug)
        pw = (request.form.get("password") or (request.get_json(silent=True) or {}).get("password") or "")
        if not verificar_password(slug, pw):
            nombre = (n.get("nombre", "Panel")).replace("<", "&lt;").replace(">", "&gt;")
            return _LOGIN.format(nombre=nombre, slug=slug, error="Contraseña incorrecta."), 401
        token = crear_token(slug)
        resp = make_response(redirect(f"/panel/{slug}", code=302))
        resp.set_cookie(COOKIE, token, httponly=True, samesite="Lax", max_age=SESSION_TTL)
        return resp

    @bp.get("/panel/<slug>/logout")
    def logout(slug):
        cerrar(request.cookies.get(COOKIE, ""))
        resp = make_response(redirect(f"/panel/{slug}", code=302))
        resp.delete_cookie(COOKIE)
        return resp

    @bp.get("/panel/<slug>/api/leads")
    def api_leads(slug):
        _api_guard(slug)
        return jsonify({"leads": saas.listar_leads(slug, request.args.get("filtro", "todos"))})

    @bp.post("/panel/<slug>/api/lead/<lead_id>/estado")
    def api_marcar(slug, lead_id):
        _api_guard(slug)
        estado = (request.get_json(silent=True) or {}).get("estado", "")
        msg = saas.marcar_lead(slug, lead_id, estado)
        ok = "->" in msg
        return jsonify({"ok": ok, "mensaje": msg}), (200 if ok else 400)

    @bp.post("/panel/<slug>/api/servicio")
    def api_servicio(slug):
        _api_guard(slug)
        d = request.get_json(silent=True) or {}
        try:
            s = saas.agregar_servicio(
                slug, nombre=d.get("nombre", ""), base=d.get("base"),
                por_unidad=d.get("por_unidad", 0.0), unidad=d.get("unidad", ""),
                unidades_incluidas=d.get("unidades_incluidas", 1),
                minimo=d.get("minimo"), maximo=d.get("maximo"),
                margen=d.get("margen"), notas=d.get("notas", ""))
        except (ValueError, TypeError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "servicio": s})

    @bp.post("/panel/<slug>/api/faq")
    def api_faq(slug):
        _api_guard(slug)
        d = request.get_json(silent=True) or {}
        try:
            item = saas.agregar_faq(slug, d.get("pregunta", ""), d.get("respuesta", ""))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "faq": item})

    return bp
