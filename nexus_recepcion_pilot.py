#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RECEPCIONISTA IA — PILOTO de validacion.

El objetivo NO es mas producto: es responder la unica pregunta que importa antes
de construir cobro y canales — ¿un negocio real quiere esto y lo probaria?

Aporta lo minimo para ponerlo delante de duenos reales y MEDIR el resultado:

  - Una landing (/pilot) que explica el recepcionista, enlaza a una DEMO en vivo
    (/r/<demo>) y recoge el interes del dueño (nombre, negocio, email).
  - Un negocio de DEMO sembrado (idempotente) para que la demo funcione al instante.
  - Metricas del embudo: visitas a la landing, clics a la demo, interesados y, por
    negocio, leads capturados y cualificados. Asi el piloto se lee con numeros, no
    con opiniones.

Se apoya en la capa multi-tenant (nexus_recepcion_saas). Opt-in con el mismo flag
NEXUS_RECEPCION_SAAS=1. Datos en la misma base SQLite (nexus_db).

Configurable por entorno:
    NEXUS_PILOT_DEMO_SLUG   Slug del negocio de demo (defecto: "demo").
    NEXUS_PILOT_TOKEN       Si se define, /pilot/metricas exige ?token=... (protege
                            las metricas cuando la app esta expuesta en internet).
"""

import datetime
import os
import re
import sqlite3
import uuid

import nexus_db
import nexus_recepcion_saas as saas
import nexus_util

DEMO_SLUG = os.environ.get("NEXUS_PILOT_DEMO_SLUG") or "demo"
PILOT_TOKEN = os.environ.get("NEXUS_PILOT_TOKEN") or ""

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TIPOS_EVENTO = ("landing", "demo_click", "interes")


# --------------------------- Base de datos ---------------------------

def _conn():
    conn = sqlite3.connect(nexus_db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Crea las tablas del piloto si no existen. Idempotente."""
    saas.init()  # el piloto se apoya en la capa multi-tenant
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS pilot_interesados(
            id TEXT PRIMARY KEY,
            creado TEXT NOT NULL,
            nombre TEXT DEFAULT '',
            negocio TEXT DEFAULT '',
            email TEXT NOT NULL,
            mensaje TEXT DEFAULT '',
            origen TEXT DEFAULT 'landing')""")
        c.execute("""CREATE TABLE IF NOT EXISTS pilot_eventos(
            id TEXT PRIMARY KEY,
            creado TEXT NOT NULL,
            tipo TEXT NOT NULL,
            ref TEXT DEFAULT '')""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pilot_eventos_tipo ON pilot_eventos(tipo)")


def _ahora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------- Eventos y embudo ---------------------------

def registrar_evento(tipo: str, ref: str = "") -> None:
    """Anota un evento del embudo (landing / demo_click / interes). Nunca lanza."""
    if tipo not in _TIPOS_EVENTO:
        return
    try:
        init()
        with _conn() as c:
            c.execute("INSERT INTO pilot_eventos(id, creado, tipo, ref) VALUES(?,?,?,?)",
                      (uuid.uuid4().hex[:10], _ahora(), tipo, (ref or "")[:64]))
    except Exception as e:
        nexus_util.log(f"pilot: no pude registrar evento {tipo}: {e}", "WARN")


def _contar_eventos() -> dict:
    with _conn() as c:
        filas = c.execute("SELECT tipo, COUNT(*) AS n FROM pilot_eventos GROUP BY tipo").fetchall()
    d = {t: 0 for t in _TIPOS_EVENTO}
    for f in filas:
        d[f["tipo"]] = f["n"]
    return d


# --------------------------- Interes del dueño ---------------------------

def registrar_interes(email: str, nombre: str = "", negocio: str = "",
                      mensaje: str = "", origen: str = "landing", avisar: bool = True) -> dict:
    """Guarda el interes de un dueño. Lanza ValueError si el email es invalido."""
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Email invalido.")
    init()
    fila = {
        "id": uuid.uuid4().hex[:10],
        "creado": _ahora(),
        "nombre": (nombre or "").strip(),
        "negocio": (negocio or "").strip(),
        "email": email,
        "mensaje": (mensaje or "").strip(),
        "origen": (origen or "landing").strip(),
    }
    with _conn() as c:
        c.execute("""INSERT INTO pilot_interesados(id, creado, nombre, negocio, email, mensaje, origen)
                     VALUES(?,?,?,?,?,?,?)""",
                  (fila["id"], fila["creado"], fila["nombre"], fila["negocio"],
                   fila["email"], fila["mensaje"], fila["origen"]))
    registrar_evento("interes", fila["negocio"] or email)
    if avisar:
        _avisar_interes(fila)
    return fila


def listar_interesados() -> list:
    init()
    with _conn() as c:
        rows = c.execute("SELECT * FROM pilot_interesados ORDER BY creado DESC").fetchall()
    return [dict(r) for r in rows]


def _avisar_interes(fila: dict) -> bool:
    """Avisa (best-effort) de un nuevo interesado por Web Push. Nunca lanza."""
    titulo = "Nuevo interesado — piloto recepcionista"
    cuerpo = f"{fila.get('nombre') or '(sin nombre)'} · {fila.get('negocio') or '-'} · {fila['email']}"
    try:
        import nexus_push
        if nexus_push.configurado():
            return bool(nexus_push.enviar(titulo, cuerpo, url="/pilot/metricas"))
    except Exception as e:
        nexus_util.log(f"pilot: aviso interes fallo: {e}", "WARN")
    return False


# --------------------------- Metricas del embudo ---------------------------

def metricas() -> dict:
    """Resumen del piloto: embudo (landing -> demo -> interes) y, por negocio, leads
    capturados y cualificados. Es lo que se mira para decidir si seguir."""
    init()
    ev = _contar_eventos()
    landing, demo, interes = ev["landing"], ev["demo_click"], ev["interes"]
    con_interes = len(listar_interesados())
    por_negocio = []
    total_leads = total_cual = 0
    for n in saas.listar_negocios():
        leads = saas.listar_leads(n["slug"])
        cual = [l for l in leads if l.get("calificado")]
        total_leads += len(leads)
        total_cual += len(cual)
        por_negocio.append({
            "slug": n["slug"], "nombre": n["nombre"],
            "leads": len(leads), "cualificados": len(cual),
        })
    return {
        "embudo": {
            "landing": landing,
            "demo_click": demo,
            "interes": max(interes, con_interes),
            "tasa_demo": round(demo / landing, 3) if landing else 0.0,
            "tasa_interes": round(max(interes, con_interes) / landing, 3) if landing else 0.0,
        },
        "leads": {"total": total_leads, "cualificados": total_cual,
                  "tasa_cualificacion": round(total_cual / total_leads, 3) if total_leads else 0.0},
        "negocios": por_negocio,
    }


# --------------------------- Sembrar la demo ---------------------------

def sembrar_demo(slug: str = None) -> dict:
    """Crea (idempotente) un negocio de DEMO listo para la landing: una empresa de
    limpieza con tarifas y FAQ, para que /r/<slug> funcione al instante."""
    slug = slug or DEMO_SLUG
    negocio = saas.obtener_negocio(slug)
    if negocio is None:
        saas.crear_negocio("Limpiezas Demo", slug=slug, sector="limpieza",
                           zona="tu ciudad", horario="L-V 9:00-18:00", idioma="es")
    saas.actualizar_negocio(slug, politica="Presupuesto sin compromiso. Productos incluidos.")
    saas.agregar_servicio(slug, "limpieza de casa", base=80, por_unidad=20,
                          unidad="habitacion", unidades_incluidas=1,
                          notas="incluye productos y materiales")
    saas.agregar_servicio(slug, "limpieza de oficina", base=120, por_unidad=0.5,
                          unidad="m2", unidades_incluidas=100, margen=0.15)
    saas.agregar_servicio(slug, "limpieza fin de obra", base=250, margen=0.2,
                          notas="segun estado y superficie")
    saas.agregar_faq(slug, "¿Que zona cubris?", "Trabajamos en tu ciudad y alrededores.")
    saas.agregar_faq(slug, "¿Cuando podeis venir?", "De lunes a viernes, de 9 a 18h. Dinos tu fecha preferida.")
    saas.agregar_faq(slug, "¿Los productos van incluidos?", "Si, llevamos todo el material y los productos.")
    return saas.obtener_negocio(slug)


# --------------------------- Landing (Flask blueprint) ---------------------------

_LANDING = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recepcionista IA para tu negocio</title>
<style>
:root{{color-scheme:light dark;--fg:#18181b;--bg:#ffffff;--muted:#6b7280;--card:#f4f4f5;--acc:#2563eb}}
@media(prefers-color-scheme:dark){{:root{{--fg:#e5e5e5;--bg:#0b0b0c;--muted:#9ca3af;--card:#17171a}}}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,sans-serif;color:var(--fg);background:var(--bg);line-height:1.5}}
.wrap{{max-width:760px;margin:0 auto;padding:0 16px}}
.hero{{padding:56px 16px 24px;text-align:center}}
h1{{font-size:2rem;margin:0 0 12px}}
.sub{{color:var(--muted);font-size:1.1rem;max-width:36rem;margin:0 auto 24px}}
.cta{{display:inline-block;padding:12px 22px;border-radius:12px;background:var(--acc);color:#fff;text-decoration:none;font-weight:600}}
.cta.sec{{background:transparent;color:var(--acc);border:1px solid var(--acc);margin-left:8px}}
.grid{{display:grid;gap:12px;grid-template-columns:1fr;margin:32px 0}}
@media(min-width:640px){{.grid{{grid-template-columns:1fr 1fr 1fr}}}}
.card{{background:var(--card);border-radius:14px;padding:16px}}
.card h3{{margin:0 0 6px;font-size:1rem}}
.card p{{margin:0;color:var(--muted);font-size:.95rem}}
form{{background:var(--card);border-radius:14px;padding:20px;margin:24px 0 56px}}
label{{display:block;font-size:.9rem;margin:10px 0 4px}}
input,textarea{{width:100%;padding:10px;border-radius:10px;border:1px solid #8886;background:transparent;color:inherit;font:inherit}}
button{{margin-top:14px;padding:12px 22px;border:0;border-radius:12px;background:var(--acc);color:#fff;font-weight:600;cursor:pointer}}
.ok{{color:#16a34a;font-weight:600}}
small{{color:var(--muted)}}
</style></head><body>
<div class="hero"><div class="wrap">
<h1>Un recepcionista con IA que responde a tus clientes 24/7</h1>
<p class="sub">Contesta las preguntas de siempre, da presupuestos con TUS precios (nunca inventados)
y te pasa el cliente ya cualificado. Pensado para negocios pequeños.</p>
<a class="cta" href="/pilot/ir-demo">Probar la demo</a>
<a class="cta sec" href="#interes">Quiero probarlo en mi negocio</a>
</div></div>
<div class="wrap">
<div class="grid">
<div class="card"><h3>Responde solo</h3><p>Atiende dudas frecuentes y precios aprobados a cualquier hora.</p></div>
<div class="card"><h3>Precios que tu decides</h3><p>La IA nunca inventa una cifra: usa tus tarifas.</p></div>
<div class="card"><h3>Leads cualificados</h3><p>Te avisa con el contacto y el servicio ya recogidos.</p></div>
</div>
<form id="f" name="interes">
<h3 id="interes">¿Lo probamos en tu negocio?</h3>
<small>Sin compromiso. Te preparamos tu recepcionista y te pasamos el enlace.</small>
<label>Tu nombre</label><input name="nombre" autocomplete="name">
<label>Tu negocio</label><input name="negocio" autocomplete="organization">
<label>Email *</label><input name="email" type="email" required autocomplete="email">
<label>¿Que necesitas?</label><textarea name="mensaje" rows="3"></textarea>
<button>Enviar</button>
<p id="msg"></p>
</form>
</div>
<script>
fetch('/pilot/evento/landing',{{method:'POST'}}).catch(()=>{{}});
const f=document.getElementById('f'),msg=document.getElementById('msg');
f.addEventListener('submit',async e=>{{e.preventDefault();
 const d=Object.fromEntries(new FormData(f).entries());
 try{{const r=await fetch('/pilot/interes',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
 const j=await r.json();
 if(r.ok){{f.reset();msg.className='ok';msg.textContent=j.mensaje||'¡Gracias! Te escribimos pronto.';}}
 else{{msg.textContent=j.error||'Revisa el email e intentalo de nuevo.';}}
 }}catch(err){{msg.textContent='No se pudo enviar. Intentalo de nuevo.';}}}});
</script></body></html>"""


def crear_blueprint():
    """Blueprint del piloto:
        GET  /pilot                landing
        GET  /pilot/ir-demo        cuenta el clic y redirige a la demo (/r/<slug>)
        POST /pilot/evento/<tipo>  anota un evento del embudo
        POST /pilot/interes        guarda el interes del dueño
        GET  /pilot/metricas       embudo + leads (protegible con NEXUS_PILOT_TOKEN)
    """
    from flask import Blueprint, abort, jsonify, redirect, request

    bp = Blueprint("recepcion_pilot", __name__)

    @bp.get("/pilot")
    def landing():
        return _LANDING.format()

    @bp.get("/pilot/ir-demo")
    def ir_demo():
        registrar_evento("demo_click", DEMO_SLUG)
        return redirect(f"/r/{DEMO_SLUG}", code=302)

    @bp.post("/pilot/evento/<tipo>")
    def evento(tipo):
        registrar_evento(tipo)
        return jsonify({"ok": True})

    @bp.post("/pilot/interes")
    def interes():
        ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "?")
              .split(",")[0].strip())
        if not saas.permitido(f"pilot-interes|{ip}", limite=10, ventana=3600):
            return jsonify({"error": "Demasiados envios; intentalo mas tarde."}), 429
        datos = request.get_json(silent=True) or request.form.to_dict() or {}
        try:
            registrar_interes(email=datos.get("email", ""), nombre=datos.get("nombre", ""),
                              negocio=datos.get("negocio", ""), mensaje=datos.get("mensaje", ""))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "mensaje": "¡Gracias! Te escribimos pronto con tu recepcionista."})

    @bp.get("/pilot/metricas")
    def ver_metricas():
        if PILOT_TOKEN and request.args.get("token") != PILOT_TOKEN:
            abort(403)
        return jsonify(metricas())

    return bp
