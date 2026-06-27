#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS - Tu asistente personal con IA, en la terminal.
Construido sobre la API de Claude (Anthropic).

Que puede hacer:
  - Conversar contigo en espanol.
  - RECORDAR cosas entre sesiones (memoria persistente en memoria.json).
  - RASTREAR ofertas de trabajo freelance/remoto reales.
  - Buscar en la web informacion actual.
  - Ejecutar comandos en tu PC (siempre con tu confirmacion).
  - Leer y escribir archivos.

Requisitos:
  pip install anthropic
  y una API key de Anthropic en la variable de entorno ANTHROPIC_API_KEY.
"""

import os
import sys
import json
import uuid
import datetime

# Hacer que la salida soporte acentos/emoji en la terminal de Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import anthropic
except ImportError:
    sys.exit("Falta la libreria 'anthropic'. Ejecuta:  pip install anthropic")

import nexus_util  # utilidades base (escritura atomica, logging)
import nexus_ninjatrader as nt  # puente con NinjaTrader 8 (trading via AT Interface)
import nexus_tareas as tareas  # productividad: tareas, recordatorios y notas
import nexus_alertas as alertas  # alertas de precio sobre NinjaTrader
import nexus_docs as docs  # RAG-lite sobre documentos del usuario


# ============================================================
#  CONFIGURACION  (cambia estas variables a tu gusto)
# ============================================================

def _env(nombre: str, defecto: str) -> str:
    """Lee una variable de entorno; si no existe o esta vacia, usa el defecto."""
    valor = os.environ.get(nombre)
    return valor if valor not in (None, "") else defecto


# Modelo a usar. El mas capaz es claude-opus-4-8.
# Para gastar MENOS dinero puedes cambiarlo (o exportar NEXUS_MODEL) por:
#   "claude-sonnet-4-6"  -> mas barato y casi tan bueno   ($3 / $15 por millon de tokens)
#   "claude-haiku-4-5"   -> el mas barato y rapido         ($1 / $5  por millon de tokens)
# (claude-opus-4-8 cuesta $5 / $25 por millon de tokens)
# TODO es configurable por variables de entorno NEXUS_* (sin tocar el codigo).
MODEL = _env("NEXUS_MODEL", "claude-opus-4-8")

# Backend del modelo: "claude" (API de Anthropic, por defecto) u "ollama" (modelo
# LOCAL en tu PC, coste $0). Con ollama no se consumen tokens de la API.
BACKEND = _env("NEXUS_BACKEND", "claude").lower()

MAX_TOKENS = int(_env("NEXUS_MAX_TOKENS", "8000"))             # longitud maxima por respuesta
TU_NOMBRE = _env("NEXUS_NOMBRE", "Senor")                      # como quieres que Nexus te llame
PEDIR_CONFIRMACION = _env("NEXUS_CONFIRMAR", "1").lower() not in ("0", "false", "no")  # permiso antes de comandos/escritura
MAX_MENSAJES_CONTEXTO = int(_env("NEXUS_MAX_MENSAJES", "40"))  # tope de mensajes enviados a la API
MAX_NOTAS = int(_env("NEXUS_MAX_NOTAS", "200"))               # tope de notas en memoria (evita crecimiento infinito)

# Precios por MILLON de tokens (USD): (entrada, salida). Para estimar el costo por turno.
# Las claves se comparan por prefijo, asi que cubren ids con fecha (claude-haiku-4-5-2025...).
PRECIOS = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4": (1.0, 5.0),
}


def costo_estimado(model: str, tokens_in: int, tokens_out: int) -> float:
    """Costo estimado en USD de un intercambio, segun el modelo y los tokens usados."""
    precio_in, precio_out = 5.0, 25.0  # fallback: opus
    for clave, (pin, pout) in PRECIOS.items():
        if model.startswith(clave):
            precio_in, precio_out = pin, pout
            break
    return (tokens_in / 1_000_000) * precio_in + (tokens_out / 1_000_000) * precio_out


def thinking_para(model: str):
    """Config de 'thinking' segun el modelo: adaptive si lo soporta (Opus/Sonnet),
    o None (desactivado) para los que no lo soportan (Haiku)."""
    return None if model.startswith("claude-haiku") else {"type": "adaptive"}

# Archivo donde Nexus guarda lo que debe recordar (junto a este script).
CARPETA = os.path.dirname(os.path.abspath(__file__))
MEMORIA_PATH = os.path.join(CARPETA, "memoria.json")

HOY = datetime.date.today().isoformat()

BASE_PROMPT = f"""Eres NEXUS, el asistente personal de {TU_NOMBRE}.
Hoy es {HOY}. Hablas en espanol, con un tono cordial, directo y eficiente.

Tienes herramientas REALES. Usalas cuando de verdad ayuden:
- recordar: guarda un dato importante en tu memoria a largo plazo.
- rastrear_ofertas: busca ofertas de trabajo freelance/remoto reales por palabras clave.
- web_search: para datos actuales o cosas que no sabes con certeza.
- run_command: para ejecutar comandos en la PC (Windows / PowerShell).
- read_file / write_file / list_directory: para trabajar con archivos.
- nt_estado / nt_precio / nt_posicion / nt_historial / nt_diario: consultar NinjaTrader
  (conexion, precios, posiciones, bitacora y diario de trading).
- nt_orden / nt_cancelar / nt_cerrar: operar en NinjaTrader (DINERO REAL; pide confirmacion;
  sujeto a las reglas de gestion de riesgo configuradas).
- agregar_tarea / listar_tareas / completar_tarea / eliminar_tarea: gestionar tareas y
  recordatorios del usuario (con fecha de vencimiento y prioridad).
- alerta_precio: crear/listar/eliminar/evaluar alertas de precio (ej. "avisame si el ES toca 5000").
- buscar_memoria / olvidar_memoria: consultar o borrar notas de tu memoria a largo plazo.
- buscar_documentos: responder con base en los documentos personales del usuario (.txt/.md/.pdf).

Contexto del usuario:
- Sabe programar (Python) y quiere conseguir ingresos como freelance de bots
  y automatizacion. Cuando pida oportunidades de trabajo, usa rastrear_ofertas.

Reglas:
- Si una tarea necesita una accion real (ejecutar algo, crear un archivo, buscar
  ofertas), usa la herramienta correspondiente; no te limites a explicar.
- Cuando el usuario comparta algo que deberias recordar a futuro (su nombre,
  preferencias, metas, datos de proyectos), usa la herramienta 'recordar'.
- Se conciso. Al terminar, resume en una linea lo que hiciste.
- Si algo es destructivo o arriesgado, avisalo claramente antes de hacerlo.
- Si no estas seguro de un dato reciente, buscalo en la web en vez de inventarlo.
- TRADING: las ordenes de NinjaTrader mueven DINERO REAL. Antes de enviar una,
  confirma el instrumento, accion, cantidad y tipo; nunca operes sin que el usuario
  lo pida de forma explicita, y resume claramente lo que vas a hacer.
"""


# ============================================================
#  MEMORIA PERSISTENTE
# ============================================================

def _normalizar_nota(item) -> dict:
    """Acepta tanto el formato antiguo (texto plano) como el nuevo (objeto con
    categoria) y devuelve siempre un objeto. Compatibilidad hacia atras."""
    if isinstance(item, dict):
        return {"id": item.get("id") or uuid.uuid4().hex[:6],
                "texto": str(item.get("texto", "")).strip(),
                "categoria": (item.get("categoria") or "general").strip().lower(),
                "creada": item.get("creada", "")}
    return {"id": uuid.uuid4().hex[:6], "texto": str(item).strip(),
            "categoria": "general", "creada": ""}


def cargar_notas() -> list:
    """Memoria completa como lista de objetos {id, texto, categoria, creada}."""
    try:
        with open(MEMORIA_PATH, "r", encoding="utf-8") as f:
            crudas = json.load(f).get("notas", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [n for n in (_normalizar_nota(x) for x in crudas) if n["texto"]]


def cargar_memoria() -> list:
    """Lista de textos recordados (compatibilidad: lo usa el system prompt)."""
    return [n["texto"] for n in cargar_notas()]


def _guardar_notas(notas: list) -> None:
    nexus_util.guardar_json(MEMORIA_PATH, {"notas": notas})


def guardar_nota(nota: str, categoria: str = "general") -> bool:
    """Guarda una nota (con categoria opcional). Deduplica por texto (ignorando
    mayusculas) y aplica un tope FIFO (MAX_NOTAS). Devuelve True si la guardo."""
    nota = (nota or "").strip()
    if not nota:
        return False
    notas = cargar_notas()
    if any(n["texto"].lower() == nota.lower() for n in notas):
        return False  # ya la recordaba
    notas.append({"id": uuid.uuid4().hex[:6], "texto": nota,
                  "categoria": (categoria or "general").strip().lower(),
                  "creada": HOY})
    if len(notas) > MAX_NOTAS:
        notas = notas[-MAX_NOTAS:]
    _guardar_notas(notas)
    return True


def buscar_notas(consulta: str) -> list:
    """Busca notas cuyo texto o categoria contengan la consulta (sin mayus/minus)."""
    q = (consulta or "").strip().lower()
    if not q:
        return cargar_notas()
    return [n for n in cargar_notas() if q in n["texto"].lower() or q in n["categoria"]]


def olvidar_nota(ref: str) -> str:
    """Borra una nota por id (prefijo) o por substring de su texto."""
    ref = (ref or "").strip().lower()
    if not ref:
        return "Indica que quieres olvidar (id o parte del texto)."
    notas = cargar_notas()
    coincide = [n for n in notas if n["id"].lower().startswith(ref)] or \
               [n for n in notas if ref in n["texto"].lower()]
    if not coincide:
        return f"No encontre nada en memoria que coincida con '{ref}'."
    if len(coincide) > 1:
        ids = ", ".join(f"{n['id']} ({n['texto'][:30]})" for n in coincide[:5])
        return f"Hay varias notas que coinciden. Precisa el id: {ids}"
    objetivo = coincide[0]
    _guardar_notas([n for n in notas if n["id"] != objetivo["id"]])
    return f"Olvidado: {objetivo['texto']}"


def construir_system_prompt() -> str:
    notas = cargar_notas()
    if not notas:
        return BASE_PROMPT
    # Agrupadas por categoria para que el modelo las use con mas contexto.
    por_cat = {}
    for n in notas:
        por_cat.setdefault(n["categoria"], []).append(n["texto"])
    bloques = []
    for cat, items in por_cat.items():
        bloques.append(f"[{cat}]\n" + "\n".join(f"- {t}" for t in items))
    lista = "\n".join(bloques)
    return BASE_PROMPT + f"\n\nESTO ES LO QUE RECUERDAS de antes (usalo con naturalidad):\n{lista}\n"


def recortar_contexto(messages: list, max_mensajes: int = MAX_MENSAJES_CONTEXTO) -> list:
    """Limita el historial enviado a la API para no exceder el limite de tokens en
    sesiones largas.

    Recorta SOLO en una frontera 'limpia' (un mensaje de usuario de texto), para no
    dejar un tool_use sin su tool_result -- lo que romperia la peticion a la API.
    Si dentro de la ventana permitida no hay una frontera limpia, conserva todo
    (es mas seguro que cortar el hilo de herramientas a la mitad).
    """
    if len(messages) <= max_mensajes:
        return messages
    corte = len(messages) - max_mensajes
    for i in range(corte, len(messages)):
        m = messages[i]
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return messages[i:]
    return messages


# ============================================================
#  DEFINICION DE HERRAMIENTAS  (lo que Claude "ve")
# ============================================================
TOOLS = [
    {
        "name": "recordar",
        "description": (
            "Guarda un dato importante en tu memoria a largo plazo para recordarlo en "
            "futuras sesiones (el nombre del usuario, sus preferencias, sus metas, datos "
            "de sus proyectos, o cualquier cosa que pida recordar). Puedes indicar una "
            "categoria (ej. 'personal', 'trabajo', 'trading', 'salud')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nota": {"type": "string", "description": "El dato a recordar, en una frase clara."},
                "categoria": {"type": "string", "description": "Categoria opcional (ej. personal, trabajo, trading)."},
            },
            "required": ["nota"],
        },
    },
    {
        "name": "buscar_memoria",
        "description": "Busca en tu memoria a largo plazo notas que coincidan con una consulta o categoria.",
        "input_schema": {
            "type": "object",
            "properties": {"consulta": {"type": "string", "description": "Texto o categoria a buscar."}},
            "required": [],
        },
    },
    {
        "name": "olvidar_memoria",
        "description": "Borra una nota de la memoria a largo plazo, por su id o por parte de su texto.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Id de la nota o parte de su texto."}},
            "required": ["ref"],
        },
    },
    {
        "name": "rastrear_ofertas",
        "description": (
            "Rastrea ofertas de trabajo freelance/remoto REALES en sitios publicos "
            "(Remotive y RemoteOK) segun palabras clave. Usalo cuando el usuario quiera "
            "ver oportunidades para conseguir clientes o trabajo (ej. 'python', "
            "'bot telegram', 'web scraping', 'automation')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "palabras_clave": {"type": "string", "description": "Palabras clave de busqueda, ej. 'python bot' o 'web scraping'."}
            },
            "required": ["palabras_clave"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Ejecuta un comando en la terminal de Windows (PowerShell) y devuelve su "
            "salida. Util para tareas del sistema: abrir programas, consultar el estado "
            "del equipo, gestionar archivos por linea de comandos, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "El comando de PowerShell a ejecutar."},
                "motivo": {"type": "string", "description": "Breve explicacion de para que sirve."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Lee y devuelve el contenido de un archivo de texto.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Ruta del archivo."}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Escribe (o sobrescribe) un archivo de texto con el contenido dado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta del archivo a crear/sobrescribir."},
                "content": {"type": "string", "description": "Contenido a escribir."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "Lista los archivos y carpetas dentro de una ruta.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Ruta de la carpeta (por defecto la actual)."}},
            "required": [],
        },
    },
    # Busqueda web: se ejecuta en los servidores de Anthropic (no en tu PC).
    # allowed_callers=["direct"] lo hace compatible con modelos sin "programmatic
    # tool calling" (p. ej. Haiku), ademas de seguir funcionando en Opus/Sonnet.
    {"type": "web_search_20260209", "name": "web_search", "allowed_callers": ["direct"]},
]

# Herramientas de NinjaTrader (trading), productividad y alertas. Se anaden al set general.
TOOLS += nt.NT_TOOLS
TOOLS += tareas.TAREAS_TOOLS
TOOLS += alertas.ALERTAS_TOOLS
TOOLS += docs.DOCS_TOOLS

# Unica fuente de verdad de las herramientas PELIGROSAS (mueven dinero o tocan el
# sistema): piden confirmacion en la terminal y van detras del modal en la web,
# donde ademas estan desactivadas por defecto. La web y el backend Ollama leen
# este set para no tener que repetir la lista.
HERRAMIENTAS_PELIGROSAS = {"run_command", "write_file"} | nt.NT_PELIGROSAS


# ============================================================
#  IMPLEMENTACION DE LAS HERRAMIENTAS  (lo que corre en tu PC)
# ============================================================

def _confirmar(texto: str) -> bool:
    if not PEDIR_CONFIRMACION:
        return True
    try:
        resp = input(f"\n[!] {texto}\n    Permitir? [s/N] ").strip().lower()
    except EOFError:
        return False
    return resp in ("s", "si", "y", "yes")


def tool_recordar(args: dict) -> str:
    nota = (args.get("nota") or "").strip()
    if not nota:
        return "No se indico que recordar."
    cat = (args.get("categoria") or "general").strip().lower()
    if guardar_nota(nota, cat):
        return f"Anotado en memoria [{cat}]: {nota}"
    return f"Ya lo tenia recordado: {nota}"


def tool_buscar_memoria(args: dict) -> str:
    notas = buscar_notas(args.get("consulta", ""))
    if not notas:
        return "No encontre nada en memoria con esa consulta."
    return "\n".join(f"[{n['id']}] ({n['categoria']}) {n['texto']}" for n in notas[:30])


def tool_olvidar_memoria(args: dict) -> str:
    return olvidar_nota(args.get("ref", ""))


def tool_rastrear_ofertas(args: dict) -> str:
    """Descarga ofertas reales de varias fuentes (Remotive, RemoteOK, Arbeitnow) y
    las filtra por palabras clave, DEDUPLICANDO por URL para no repetir."""
    import urllib.request
    import urllib.parse
    consulta = (args.get("palabras_clave") or "python").strip()
    palabras = [p.lower() for p in consulta.split() if p]
    headers = {"User-Agent": "Mozilla/5.0 (NEXUS-job-tracker)"}
    ofertas = []          # lineas ya formateadas (incluye avisos de fuentes caidas)
    vistos = set()        # claves ya incluidas, para deduplicar

    def _agregar(fuente, titulo, empresa, url, extra=""):
        clave = (url or f"{titulo}|{empresa}").strip().lower()
        if not titulo or clave in vistos:
            return False
        vistos.add(clave)
        cola = f" ({extra})" if extra else ""
        ofertas.append(f"[{fuente}] {titulo} - {empresa}{cola}\n   {url}")
        return True

    # --- Fuente 1: Remotive (busqueda en el servidor) ---
    try:
        q = urllib.parse.quote(consulta)
        url = f"https://remotive.com/api/remote-jobs?search={q}&limit=12"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        n = 0
        for j in (data.get("jobs", []) if isinstance(data, dict) else []):
            blob = (str(j.get("title", "")) + " " + str(j.get("category", "")) + " "
                    + " ".join(j.get("tags", []) or [])).lower()
            if not any(p in blob for p in palabras):
                continue
            if _agregar("Remotive", j.get("title"), j.get("company_name"),
                        j.get("url"), j.get("candidate_required_location") or "remoto"):
                n += 1
            if n >= 12:
                break
    except Exception as e:
        ofertas.append(f"(Remotive no disponible ahora: {e})")

    # --- Fuente 2: RemoteOK (filtramos localmente por palabras clave) ---
    try:
        req = urllib.request.Request("https://remoteok.com/api", headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        n = 0
        for it in (data if isinstance(data, list) else []):
            if not isinstance(it, dict) or not it.get("position"):
                continue
            blob = (str(it.get("position", "")) + " " + " ".join(it.get("tags", []) or [])).lower()
            if any(p in blob for p in palabras):
                if _agregar("RemoteOK", it.get("position"), it.get("company"), it.get("url")):
                    n += 1
                if n >= 12:
                    break
    except Exception as e:
        ofertas.append(f"(RemoteOK no disponible ahora: {e})")

    # --- Fuente 3: Arbeitnow (job board publico) ---
    try:
        req = urllib.request.Request("https://www.arbeitnow.com/api/job-board-api", headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        n = 0
        for j in (data.get("data", []) if isinstance(data, dict) else []):
            blob = (str(j.get("title", "")) + " " + " ".join(j.get("tags", []) or [])).lower()
            if any(p in blob for p in palabras):
                if _agregar("Arbeitnow", j.get("title"), j.get("company_name"), j.get("url")):
                    n += 1
                if n >= 12:
                    break
    except Exception as e:
        ofertas.append(f"(Arbeitnow no disponible ahora: {e})")

    # --- Fuente 4: Jobicy (job board remoto; filtra por palabra clave EN EL SERVIDOR) ---
    try:
        tag = urllib.parse.quote(palabras[0] if palabras else consulta)
        jurl = f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}"
        req = urllib.request.Request(jurl, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        n = 0
        for j in (data.get("jobs", []) if isinstance(data, dict) else []):
            if _agregar("Jobicy", j.get("jobTitle"), j.get("companyName"), j.get("url")):
                n += 1
            if n >= 12:
                break
    except Exception as e:
        ofertas.append(f"(Jobicy no disponible ahora: {e})")

    utiles = [o for o in ofertas if not o.startswith("(")]
    if not utiles:
        return ("No encontre ofertas con esas palabras (o las fuentes no respondieron). "
                "Prueba con otras como 'python', 'bot', 'scraping', 'automation'.\n"
                + "\n".join(ofertas))
    return "\n".join(ofertas[:24])


def ejecutar_powershell(cmd: str) -> str:
    """Ejecuta un comando de PowerShell y devuelve su salida, SIN pedir confirmacion.
    La confirmacion se maneja afuera (en la terminal con _confirmar; en la web con el
    modal de aprobacion). Asi ambos frentes reutilizan esta misma logica."""
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=120,
        )
        salida = (result.stdout or "") + (result.stderr or "")
        return salida.strip() or "(comando ejecutado, sin salida)"
    except subprocess.TimeoutExpired:
        return "Error: el comando tardo demasiado (timeout de 120s)."
    except Exception as e:
        return f"Error al ejecutar el comando: {e}"


def tool_run_command(args: dict) -> str:
    cmd = args.get("command", "")
    if not _confirmar(f"Nexus quiere EJECUTAR:\n    {cmd}"):
        return "El usuario denego la ejecucion de este comando."
    return ejecutar_powershell(cmd)


def tool_read_file(args: dict) -> str:
    path = args.get("path", "")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"Error al leer '{path}': {e}"


def escribir_archivo(path: str, content: str) -> str:
    """Escribe (o sobrescribe) un archivo de texto, SIN pedir confirmacion."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Archivo guardado: {path} ({len(content)} caracteres)."
    except Exception as e:
        return f"Error al escribir '{path}': {e}"


def tool_write_file(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    if not _confirmar(f"Nexus quiere ESCRIBIR el archivo:\n    {path}"):
        return "El usuario denego escribir el archivo."
    return escribir_archivo(path, content)


def tool_list_directory(args: dict) -> str:
    path = args.get("path") or "."
    try:
        entradas = os.listdir(path)
        return "\n".join(sorted(entradas)) if entradas else "(carpeta vacia)"
    except Exception as e:
        return f"Error al listar '{path}': {e}"


def tool_nt_orden(args: dict) -> str:
    if not _confirmar(f"Nexus quiere ENVIAR esta ORDEN REAL a NinjaTrader:\n    {nt.resumen_orden(args)}"):
        return "El usuario denego la orden."
    return nt.colocar_orden(args)


def tool_nt_cancelar(args: dict) -> str:
    que = "TODAS las ordenes" if (args.get("todas") or args.get("order_id") in (None, "", "todas")) \
        else f"la orden {args.get('order_id')}"
    if not _confirmar(f"Nexus quiere CANCELAR {que} en NinjaTrader"):
        return "El usuario denego la cancelacion."
    return nt.cancelar(args)


def tool_nt_cerrar(args: dict) -> str:
    que = "APLANAR TODO (cerrar posiciones y cancelar ordenes)" if (args.get("todo") or not args.get("instrument")) \
        else f"cerrar la posicion de {args.get('instrument')}"
    if not _confirmar(f"Nexus quiere {que} en NinjaTrader"):
        return "El usuario denego el cierre."
    return nt.cerrar(args)


EJECUTORES = {
    "recordar": tool_recordar,
    "buscar_memoria": tool_buscar_memoria,
    "olvidar_memoria": tool_olvidar_memoria,
    "rastrear_ofertas": tool_rastrear_ofertas,
    "run_command": tool_run_command,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_directory": tool_list_directory,
    # NinjaTrader: lectura directa; las ordenes pasan por confirmacion (wrappers).
    "nt_estado": nt.NT_EJECUTORES["nt_estado"],
    "nt_precio": nt.NT_EJECUTORES["nt_precio"],
    "nt_posicion": nt.NT_EJECUTORES["nt_posicion"],
    "nt_historial": nt.NT_EJECUTORES["nt_historial"],
    "nt_diario": nt.NT_EJECUTORES["nt_diario"],
    "nt_orden": tool_nt_orden,
    "nt_cancelar": tool_nt_cancelar,
    "nt_cerrar": tool_nt_cerrar,
}
# Productividad (tareas/recordatorios) y alertas de precio: herramientas seguras.
EJECUTORES.update(tareas.TAREAS_EJECUTORES)
EJECUTORES.update(alertas.ALERTAS_EJECUTORES)
EJECUTORES.update(docs.DOCS_EJECUTORES)


def ejecutar_herramienta(name: str, args: dict) -> str:
    funcion = EJECUTORES.get(name)
    if funcion is None:
        return f"Herramienta desconocida: {name}"
    try:
        return funcion(args)
    except Exception as e:
        # Una herramienta que falla NUNCA debe tumbar el turno del agente: devolvemos
        # el error como resultado para que el modelo pueda reaccionar o avisar.
        return f"Error ejecutando la herramienta {name}: {e}"


def conversar(messages: list, system_prompt: str = None, tools: list = None,
              ejecutar=None, model: str = None, max_iter: int = 10) -> tuple:
    """Ejecuta un turno agentico COMPLETO (sin streaming) y devuelve (texto, usage).

    Reutilizable por canales que no necesitan streaming (Telegram, scheduler, etc.).
    `messages` se modifica in-place anadiendo las respuestas del modelo y los
    resultados de herramientas, asi el llamador puede continuar la conversacion.
    """
    client = anthropic.Anthropic()
    system_prompt = system_prompt if system_prompt is not None else construir_system_prompt()
    tools = TOOLS if tools is None else tools
    ejecutar = ejecutar or ejecutar_herramienta
    model = model or MODEL
    texto = ""
    tin = tout = 0
    for _ in range(max_iter):
        kwargs = dict(model=model, max_tokens=MAX_TOKENS, system=system_prompt,
                      tools=tools, messages=messages)
        _th = thinking_para(model)
        if _th:
            kwargs["thinking"] = _th
        resp = client.messages.create(**kwargs)
        if getattr(resp, "usage", None):
            tin += resp.usage.input_tokens
            tout += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        for b in resp.content:
            if getattr(b, "type", None) == "text":
                texto += b.text
        if resp.stop_reason == "tool_use":
            resultados = []
            for b in resp.content:
                if getattr(b, "type", None) == "tool_use":
                    salida = ejecutar(b.name, b.input)
                    resultados.append({"type": "tool_result", "tool_use_id": b.id, "content": salida})
            messages.append({"role": "user", "content": resultados})
            continue
        if resp.stop_reason == "pause_turn":
            continue
        break
    return texto.strip(), {"in": tin, "out": tout}


MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
               "gif": "image/gif", "webp": "image/webp"}


def analizar_imagen(image_b64: str, media_type: str = "image/jpeg",
                    prompt: str = "", model: str = None) -> tuple:
    """Analiza una imagen con la vision de Claude. Devuelve (texto, usage).

    `image_b64` es la imagen en base64 (sin el prefijo data:). Requiere el backend
    de Claude (la vision no esta disponible en el modelo local de texto)."""
    client = anthropic.Anthropic()
    model = model or MODEL
    contenido = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
        {"type": "text", "text": prompt or "Analiza esta imagen en detalle y dime lo relevante."},
    ]
    resp = client.messages.create(model=model, max_tokens=MAX_TOKENS,
                                  system=construir_system_prompt(),
                                  messages=[{"role": "user", "content": contenido}])
    texto = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    usage = {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens} if getattr(resp, "usage", None) else {"in": 0, "out": 0}
    return texto.strip(), usage


# ============================================================
#  PROGRAMA PRINCIPAL
# ============================================================

def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "No encuentro tu API key.\n"
            'Configurala con (y reinicia la terminal):\n'
            '   setx ANTHROPIC_API_KEY "sk-ant-..."'
        )

    client = anthropic.Anthropic()
    system_prompt = construir_system_prompt()
    messages = []

    print("=" * 52)
    print("  N.E.X.U.S.  - a su disposicion.")
    recordadas = len(cargar_memoria())
    if recordadas:
        print(f"  (memoria: {recordadas} cosas recordadas)")
    pendientes = tareas.resumen_pendientes()
    if pendientes:
        print(f"  (tareas: {pendientes})")
    print("  (escribe 'salir' para terminar)")
    print("=" * 52)

    while True:
        try:
            entrada = input("\nTu > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nHasta luego.")
            break

        if entrada.lower() in ("salir", "exit", "quit", "adios"):
            print("Nexus > A su disposicion. Hasta luego.")
            break
        if not entrada:
            continue

        messages.append({"role": "user", "content": entrada})
        messages = recortar_contexto(messages)

        turno_in = turno_out = 0
        for _ in range(10):  # tope de seguridad de iteraciones por turno
            kwargs = dict(model=MODEL, max_tokens=MAX_TOKENS, system=system_prompt,
                          tools=TOOLS, messages=messages)
            _th = thinking_para(MODEL)
            if _th:
                kwargs["thinking"] = _th
            try:
                with client.messages.stream(**kwargs) as stream:
                    primera = True
                    for texto in stream.text_stream:
                        if primera:
                            print("\nNexus > ", end="", flush=True)
                            primera = False
                        print(texto, end="", flush=True)
                    if not primera:
                        print()
                    response = stream.get_final_message()
            except anthropic.APIError as e:
                print(f"\n[Error de la API: {e}]")
                break

            if getattr(response, "usage", None):
                turno_in += response.usage.input_tokens
                turno_out += response.usage.output_tokens

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                break
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "tool_use":
                resultados = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"   - usando herramienta: {block.name}")
                        salida = ejecutar_herramienta(block.name, block.input)
                        resultados.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": salida,
                        })
                messages.append({"role": "user", "content": resultados})
                continue
            break

        if turno_in or turno_out:
            costo = costo_estimado(MODEL, turno_in, turno_out)
            print(f"\n   [tokens: {turno_in:,} in / {turno_out:,} out  ~${costo:.4f}]")


if __name__ == "__main__":
    main()
