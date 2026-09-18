#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RECEPCIONISTA IA — capa MULTI-TENANT (SaaS) para NEXUS.

Convierte el recepcionista de un solo dueño (nexus_recepcionista) en un producto
donde CADA negocio es una cuenta propia, con su configuracion, sus tarifas, sus
FAQ y sus leads AISLADOS, accesible por una URL publica que el negocio puede poner
en su web:  /r/<slug>  (chat del cliente).

Es la base sobre la que se montan el panel del dueño, el cobro (Stripe) y los
canales (WhatsApp/Telegram). Este modulo aporta:

  - Almacen multi-tenant en SQLite (tablas `negocios` y `saas_leads`), en la misma
    base que las cuentas de NEXUS (nexus_db). Datos de un negocio NUNCA se mezclan
    con los de otro: todo va con clave (negocio_id).
  - La MISMA logica de precios/FAQ/cualificacion que el modo de un dueño: se
    reutilizan las funciones PURAS de nexus_recepcionista (una sola fuente de
    verdad para el presupuesto; la IA sigue sin poder inventar un precio).
  - Un endpoint publico (blueprint de Flask) con:
      * limite por IP (anti-abuso a nivel de red), y
      * el tope de leads por conversacion (anti-spam) ya existente.
  - Un gate de actividad (`negocio_activo`) para que, cuando se conecte el cobro,
    un negocio sin plan al dia deje de atender sin tocar el resto del sistema.

Configurable por entorno:
    NEXUS_RECEPCION_SAAS         "1" para registrar el blueprint publico en la web.
    NEXUS_RECEPCION_RATE_MAX     Mensajes por ventana y por IP+negocio (defecto 20).
    NEXUS_RECEPCION_RATE_VENTANA Ventana del limite, en segundos (defecto 60).
    NEXUS_RECEPCION_MAX_LEADS    Tope de leads por conversacion (compartido; defecto 3).
"""

import datetime
import json
import os
import re
import sqlite3
import time
import uuid

import nexus_db
import nexus_recepcionista as recep
import nexus_util


def _env_int(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre) or defecto)
    except (ValueError, TypeError):
        return defecto


RATE_MAX = _env_int("NEXUS_RECEPCION_RATE_MAX", 20)
RATE_VENTANA = _env_int("NEXUS_RECEPCION_RATE_VENTANA", 60)

# Campos de texto simples del negocio (los guardamos como columnas).
_CAMPOS_TEXTO = ("nombre", "sector", "zona", "horario", "moneda", "idioma",
                 "politica", "telefono_aviso", "dueno_email", "plan")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")  # 1-49 chars, empieza en alfanumerico


# --------------------------- Base de datos ---------------------------

def _conn():
    conn = sqlite3.connect(nexus_db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Crea las tablas multi-tenant si no existen. Idempotente."""
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS negocios(
            slug TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            sector TEXT DEFAULT '',
            zona TEXT DEFAULT '',
            horario TEXT DEFAULT '',
            moneda TEXT DEFAULT '€',
            idioma TEXT DEFAULT 'es',
            politica TEXT DEFAULT '',
            telefono_aviso TEXT DEFAULT '',
            dueno_email TEXT DEFAULT '',
            servicios TEXT DEFAULT '[]',
            faq TEXT DEFAULT '[]',
            plan TEXT DEFAULT 'trial',
            activo INTEGER DEFAULT 1,
            creado TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS saas_leads(
            id TEXT PRIMARY KEY,
            negocio_id TEXT NOT NULL,
            creado TEXT NOT NULL,
            nombre TEXT DEFAULT '',
            contacto TEXT DEFAULT '',
            servicio TEXT DEFAULT '',
            detalles TEXT DEFAULT '',
            presupuesto TEXT DEFAULT '',
            estado TEXT DEFAULT 'nuevo',
            calificado INTEGER DEFAULT 0,
            origen TEXT DEFAULT 'chat',
            FOREIGN KEY(negocio_id) REFERENCES negocios(slug))""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_saas_leads_negocio ON saas_leads(negocio_id)")


def _ahora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------- Slug ---------------------------

def slugify(texto: str) -> str:
    """Convierte el nombre de un negocio en un slug de URL (a-z, 0-9, guiones)."""
    base = recep._normalizar(texto).strip()
    base = re.sub(r"\s+", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")
    return base[:48] or "negocio"


# --------------------------- Negocios (CRUD) ---------------------------

def _fila_a_negocio(row) -> dict:
    n = dict(row)
    for k in ("servicios", "faq"):
        try:
            n[k] = json.loads(n.get(k) or "[]")
        except (ValueError, TypeError):
            n[k] = []
    n["activo"] = bool(n.get("activo"))
    return n


def crear_negocio(nombre: str, slug: str = None, **campos) -> dict:
    """Crea un negocio. Lanza ValueError si el nombre falta, el slug es invalido o
    ya existe. Devuelve el negocio creado."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El negocio necesita un nombre.")
    slug = (slug or slugify(nombre)).strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError("Slug invalido: usa 1-49 caracteres a-z, 0-9 y guiones (empieza en letra o numero).")
    init()
    campos = {k: v for k, v in campos.items() if k in _CAMPOS_TEXTO and v is not None}
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO negocios(slug, nombre, creado) VALUES(?,?,?)",
                (slug, nombre, _ahora()))
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe un negocio con el slug '{slug}'.")
    if campos:
        actualizar_negocio(slug, **campos)
    return obtener_negocio(slug)


def obtener_negocio(slug: str):
    """Devuelve el negocio (con servicios/faq ya como listas) o None."""
    init()
    with _conn() as c:
        row = c.execute("SELECT * FROM negocios WHERE slug=?", (slug or "",)).fetchone()
    return _fila_a_negocio(row) if row else None


def actualizar_negocio(slug: str, **campos) -> dict:
    """Actualiza campos de texto del negocio. Devuelve el negocio o lanza ValueError."""
    if obtener_negocio(slug) is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    sets, valores = [], []
    for k, v in campos.items():
        if k in _CAMPOS_TEXTO and v is not None:
            sets.append(f"{k}=?")
            valores.append(v)
    if sets:
        valores.append(slug)
        with _conn() as c:
            c.execute(f"UPDATE negocios SET {', '.join(sets)} WHERE slug=?", valores)
    return obtener_negocio(slug)


def _guardar_lista(slug: str, campo: str, lista: list) -> None:
    if obtener_negocio(slug) is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    with _conn() as c:
        c.execute(f"UPDATE negocios SET {campo}=? WHERE slug=?",
                  (json.dumps(lista, ensure_ascii=False), slug))


def agregar_servicio(slug: str, nombre: str, base: float, **kw) -> dict:
    """Añade/actualiza una tarifa aprobada del negocio (misma forma que el modo dueño).
    Reutiliza la validacion/normalizacion PURA del modulo base (una sola fuente de
    verdad para el presupuesto)."""
    negocio = obtener_negocio(slug)
    if negocio is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    servicio = recep.construir_servicio(nombre, base, **kw)
    servicios = recep.upsert_servicio_en(list(negocio["servicios"]), servicio)
    _guardar_lista(slug, "servicios", servicios)
    return servicio


def agregar_faq(slug: str, pregunta: str, respuesta: str) -> dict:
    pregunta, respuesta = (pregunta or "").strip(), (respuesta or "").strip()
    if not pregunta or not respuesta:
        raise ValueError("La FAQ necesita pregunta y respuesta.")
    negocio = obtener_negocio(slug)
    if negocio is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    faq = list(negocio["faq"])
    for item in faq:
        if recep._normalizar(item.get("pregunta", "")) == recep._normalizar(pregunta):
            item["respuesta"] = respuesta
            break
    else:
        faq.append({"pregunta": pregunta, "respuesta": respuesta})
    _guardar_lista(slug, "faq", faq)
    return {"pregunta": pregunta, "respuesta": respuesta}


def listar_negocios() -> list:
    init()
    with _conn() as c:
        rows = c.execute("SELECT * FROM negocios ORDER BY creado DESC").fetchall()
    return [_fila_a_negocio(r) for r in rows]


def fijar_estado_cuenta(slug: str, activo: bool = None, plan: str = None) -> dict:
    """Activa/desactiva el negocio y/o cambia su plan (gancho para el cobro)."""
    if obtener_negocio(slug) is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    sets, valores = [], []
    if activo is not None:
        sets.append("activo=?")
        valores.append(1 if activo else 0)
    if plan is not None:
        sets.append("plan=?")
        valores.append(plan)
    if sets:
        valores.append(slug)
        with _conn() as c:
            c.execute(f"UPDATE negocios SET {', '.join(sets)} WHERE slug=?", valores)
    return obtener_negocio(slug)


def negocio_activo(negocio: dict) -> bool:
    """True si el negocio puede atender clientes (cuenta activa). Cuando se conecte
    el cobro, aqui se añadira la comprobacion de plan vigente."""
    return bool(negocio) and bool(negocio.get("activo"))


# --------------------------- Leads (por negocio) ---------------------------

def capturar_lead(slug: str, nombre: str = "", contacto: str = "", servicio: str = "",
                  detalles: str = "", presupuesto: str = "", origen: str = "chat",
                  avisar: bool = True) -> dict:
    """Guarda un lead del negocio `slug`, lo califica y (opcional) avisa al dueño."""
    negocio = obtener_negocio(slug)
    if negocio is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    lead = {
        "id": uuid.uuid4().hex[:8],
        "negocio_id": slug,
        "creado": _ahora(),
        "nombre": (nombre or "").strip(),
        "contacto": (contacto or "").strip(),
        "servicio": (servicio or "").strip(),
        "detalles": (detalles or "").strip(),
        "presupuesto": (presupuesto or "").strip(),
        "estado": "nuevo",
        "origen": (origen or "chat").strip(),
    }
    lead["calificado"] = recep.calificar_lead(lead)
    with _conn() as c:
        c.execute("""INSERT INTO saas_leads(id, negocio_id, creado, nombre, contacto,
                     servicio, detalles, presupuesto, estado, calificado, origen)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (lead["id"], slug, lead["creado"], lead["nombre"], lead["contacto"],
                   lead["servicio"], lead["detalles"], lead["presupuesto"], lead["estado"],
                   1 if lead["calificado"] else 0, lead["origen"]))
    if avisar and lead["calificado"]:
        avisar_dueno(negocio, lead)
    return lead


def listar_leads(slug: str, filtro: str = "todos") -> list:
    init()
    f = (filtro or "todos").lower()
    consulta = "SELECT * FROM saas_leads WHERE negocio_id=?"
    params = [slug]
    if f in ("nuevos", "nuevo"):
        consulta += " AND estado='nuevo'"
    elif f in ("cualificados", "calificados"):
        consulta += " AND calificado=1"
    elif f in ("ganados", "ganado"):
        consulta += " AND estado='ganado'"
    elif f in ("perdidos", "perdido"):
        consulta += " AND estado='perdido'"
    consulta += " ORDER BY creado DESC"
    with _conn() as c:
        rows = c.execute(consulta, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["calificado"] = bool(d.get("calificado"))
        out.append(d)
    return out


def marcar_lead(slug: str, lead_id: str, estado: str) -> str:
    estado = (estado or "").strip().lower()
    if estado not in recep.ESTADOS_LEAD:
        return f"Estado invalido. Usa uno de: {', '.join(recep.ESTADOS_LEAD)}."
    with _conn() as c:
        cur = c.execute("UPDATE saas_leads SET estado=? WHERE negocio_id=? AND id=?",
                        (estado, slug, lead_id))
    if cur.rowcount == 0:
        return f"No encontre el lead '{lead_id}' en '{slug}'."
    return f"Lead {lead_id} -> {estado}."


# --------------------------- Aviso al dueño (por negocio) ---------------------------

def avisar_dueno(negocio: dict, lead: dict) -> bool:
    """Avisa al dueño del negocio de un nuevo lead. Best-effort; nunca lanza."""
    titulo = f"Nuevo lead — {negocio.get('nombre', 'tu negocio')}"
    cuerpo = recep.resumen_lead(lead)
    enviado = False
    try:
        import nexus_telegram
        chat = negocio.get("telefono_aviso") or None
        if chat and nexus_telegram.configurado():
            enviado = nexus_telegram.enviar(f"{titulo}\n{cuerpo}", chat_id=chat) or enviado
    except Exception as e:
        nexus_util.log(f"recepcion_saas: aviso telegram fallo: {e}", "WARN")
    try:
        import nexus_push
        if nexus_push.configurado():
            enviado = bool(nexus_push.enviar(titulo, cuerpo, url="/")) or enviado
    except Exception as e:
        nexus_util.log(f"recepcion_saas: aviso push fallo: {e}", "WARN")
    return enviado


# --------------------------- Limite por IP (anti-abuso de red) ---------------------------

_HITS = {}  # clave -> lista de timestamps (ventana deslizante en memoria)


def permitido(clave: str, limite: int = None, ventana: int = None) -> bool:
    """Rate limit sencillo en memoria: <=limite eventos por `ventana` segundos y
    `clave` (normalmente ip+negocio). Devuelve False si se supera. `limite` <= 0
    desactiva el limite."""
    limite = RATE_MAX if limite is None else limite
    ventana = RATE_VENTANA if ventana is None else ventana
    if limite <= 0:
        return True
    ahora = time.monotonic()
    recientes = [t for t in _HITS.get(clave, []) if ahora - t < ventana]
    if len(recientes) >= limite:
        _HITS[clave] = recientes
        return False
    recientes.append(ahora)
    _HITS[clave] = recientes
    return True


# --------------------------- Chat del cliente (por negocio) ---------------------------

def _ejecutor_de(slug: str, negocio: dict, estado: dict, max_leads: int):
    """Dispatcher de herramientas del cliente ATADO a un negocio concreto. Reutiliza
    la logica pura de precios/FAQ; captura leads en el negocio correcto; respeta el
    tope por conversacion. Aislado: solo conoce las 3 herramientas del recepcionista."""
    def _estimar(args: dict) -> str:
        est = recep.estimar_precio_en(negocio, args.get("servicio", ""), args.get("cantidad"))
        return recep.formato_presupuesto(est)

    def _faq(args: dict) -> str:
        item = recep.buscar_faq_en(negocio.get("faq", []), args.get("pregunta", ""))
        if not item:
            return ("No tengo esa informacion a mano; puedo pedir que el responsable te "
                    "lo confirme si me dejas tu contacto.")
        return item["respuesta"]

    def _lead(args: dict) -> str:
        if max_leads > 0 and estado.get("leads_capturados", 0) >= max_leads:
            return ("Ya he registrado tu solicitud; el responsable te contactara. "
                    "Si necesitas algo mas, te atendera directamente.")
        lead = capturar_lead(
            slug, nombre=args.get("nombre", ""), contacto=args.get("contacto", ""),
            servicio=args.get("servicio", ""), detalles=args.get("detalles", ""),
            presupuesto=args.get("presupuesto", ""), origen=args.get("origen", "chat"))
        if max_leads > 0:
            estado["leads_capturados"] = estado.get("leads_capturados", 0) + 1
        if lead["calificado"]:
            return ("¡Gracias! He tomado tus datos y el responsable te contactara pronto. "
                    f"(referencia {lead['id']})")
        faltan = []
        if not recep._es_contacto(lead.get("contacto", "")):
            faltan.append("un telefono o email de contacto")
        if not lead.get("servicio"):
            faltan.append("que servicio necesitas")
        return "Casi lo tengo; ¿me confirmas " + " y ".join(faltan) + "?"

    ejecutores = {"estimar_precio": _estimar, "buscar_faq": _faq, "capturar_lead": _lead}

    def _dispatch(name: str, args: dict) -> str:
        fn = ejecutores.get(name)
        if fn is None:
            return f"Herramienta no disponible en recepcion: {name}"
        try:
            return fn(args)
        except Exception as e:
            nexus_util.log(f"recepcion_saas: error en {name} ({slug}): {e}", "ERROR")
            return "Ha ocurrido un problema al procesar tu solicitud; lo intento de nuevo."
    return _dispatch


def responder_cliente(slug: str, mensaje: str, historial: list = None,
                      estado: dict = None, model: str = None,
                      max_leads: int = None) -> dict:
    """Atiende un turno del cliente para el negocio `slug`. Devuelve
    {"texto", "historial", "estado", "ok"}. Si el negocio no existe o esta
    inactivo (p. ej. plan no vigente), responde sin tocar el modelo (ok=False)."""
    import nexus  # import diferido
    negocio = obtener_negocio(slug)
    historial = historial if historial is not None else []
    estado = estado if estado is not None else recep.nuevo_estado()
    if not negocio_activo(negocio):
        return {"ok": False, "historial": historial, "estado": estado,
                "texto": "Este servicio no esta disponible ahora mismo."}
    tope = recep.MAX_LEADS_POR_CONV if max_leads is None else max_leads
    historial.append({"role": "user", "content": mensaje})
    system = recep.system_prompt_cliente(negocio)
    ejecutar = _ejecutor_de(slug, negocio, estado, tope)
    texto, _usage = nexus.conversar(
        historial, system_prompt=system, tools=recep.RECEPCION_CLIENTE_TOOLS,
        ejecutar=ejecutar, model=model, max_iter=6)
    return {"ok": True, "texto": texto, "historial": historial, "estado": estado}


# --------------------------- Endpoint publico (Flask blueprint) ---------------------------

_SESIONES = {}  # sid -> {"historial", "estado", "ts"}  (memoria del proceso)
_SESION_TTL = 3600  # 1h de inactividad


def _limpiar_sesiones() -> None:
    ahora = time.time()
    for sid in [s for s, v in _SESIONES.items() if ahora - v.get("ts", 0) > _SESION_TTL]:
        _SESIONES.pop(sid, None)


_PAGINA = """<!doctype html><html lang="{idioma}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{nombre}</title>
<style>
:root{{color-scheme:light dark}}
body{{font-family:system-ui,sans-serif;margin:0;background:#f4f4f5;color:#18181b}}
@media(prefers-color-scheme:dark){{body{{background:#0b0b0c;color:#e5e5e5}}}}
.wrap{{max-width:640px;margin:0 auto;height:100vh;display:flex;flex-direction:column}}
header{{padding:16px;font-weight:600;border-bottom:1px solid #8883}}
#log{{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px}}
.msg{{padding:8px 12px;border-radius:12px;max-width:80%;white-space:pre-wrap;line-height:1.35}}
.u{{align-self:flex-end;background:#2563eb;color:#fff}}
.a{{align-self:flex-start;background:#8882}}
form{{display:flex;gap:8px;padding:12px;border-top:1px solid #8883}}
input{{flex:1;padding:10px;border-radius:10px;border:1px solid #8886;background:transparent;color:inherit}}
button{{padding:10px 16px;border:0;border-radius:10px;background:#2563eb;color:#fff;cursor:pointer}}
</style></head><body><div class="wrap">
<header>{nombre}</header>
<div id="log"></div>
<form id="f"><input id="m" autocomplete="off" placeholder="Escribe tu consulta…" required>
<button>Enviar</button></form></div>
<script>
const slug={slug_json}, log=document.getElementById('log'), f=document.getElementById('f'), m=document.getElementById('m');
let sid=localStorage.getItem('recep_sid_'+slug)||(crypto.randomUUID?crypto.randomUUID():String(Math.random()));
try{{localStorage.setItem('recep_sid_'+slug,sid)}}catch(e){{}}
function add(t,cls){{const d=document.createElement('div');d.className='msg '+cls;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;}}
f.addEventListener('submit',async e=>{{e.preventDefault();const t=m.value.trim();if(!t)return;add(t,'u');m.value='';
 try{{const r=await fetch('chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{mensaje:t,sid}})}});
 const j=await r.json();add(j.texto||'…','a');}}catch(err){{add('No he podido responder ahora mismo. Intentalo de nuevo.','a');}}}});
</script></body></html>"""


def crear_blueprint():
    """Devuelve un blueprint de Flask con el chat publico del cliente:
        GET  /r/<slug>        pagina de chat del negocio
        POST /r/<slug>/chat   {mensaje, sid} -> {texto}
    Aislado del resto de NEXUS: solo expone el recepcionista del negocio pedido."""
    from flask import Blueprint, abort, jsonify, request

    bp = Blueprint("recepcion_saas", __name__)

    @bp.get("/r/<slug>")
    def pagina(slug):
        negocio = obtener_negocio(slug)
        if not negocio_activo(negocio):
            abort(404)
        return _PAGINA.format(
            idioma=negocio.get("idioma", "es"),
            nombre=(negocio.get("nombre", "Recepcion")
                    .replace("<", "&lt;").replace(">", "&gt;")),
            slug_json=json.dumps(slug))

    @bp.post("/r/<slug>/chat")
    def chat(slug):
        negocio = obtener_negocio(slug)
        if not negocio_activo(negocio):
            abort(404)
        datos = request.get_json(silent=True) or {}
        mensaje = (datos.get("mensaje") or "").strip()
        if not mensaje:
            return jsonify({"texto": "¿En que puedo ayudarte?"})
        ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "?")
              .split(",")[0].strip())
        if not permitido(f"{slug}|{ip}"):
            return jsonify({"texto": "Vas muy rapido; espera unos segundos e intentalo de nuevo."}), 429
        _limpiar_sesiones()
        sid = (datos.get("sid") or uuid.uuid4().hex)[:64]
        ses = _SESIONES.setdefault(f"{slug}|{sid}",
                                   {"historial": [], "estado": recep.nuevo_estado(), "ts": 0})
        ses["ts"] = time.time()
        r = responder_cliente(slug, mensaje, historial=ses["historial"], estado=ses["estado"])
        return jsonify({"texto": r["texto"]})

    return bp
