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


# ============================================================
#  CONFIGURACION  (cambia estas variables a tu gusto)
# ============================================================

# Modelo a usar. El mas capaz es claude-opus-4-8.
# Para gastar MENOS dinero puedes cambiarlo por:
#   "claude-sonnet-4-6"  -> mas barato y casi tan bueno   ($3 / $15 por millon de tokens)
#   "claude-haiku-4-5"   -> el mas barato y rapido         ($1 / $5  por millon de tokens)
# (claude-opus-4-8 cuesta $5 / $25 por millon de tokens)
MODEL = "claude-opus-4-8"

MAX_TOKENS = 8000           # longitud maxima por respuesta
TU_NOMBRE = "Senor"         # como quieres que Nexus te llame
PEDIR_CONFIRMACION = True    # pedir permiso antes de ejecutar comandos / escribir archivos
MAX_MENSAJES_CONTEXTO = 40   # tope de mensajes enviados a la API (evita exceder tokens en sesiones largas)

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
"""


# ============================================================
#  MEMORIA PERSISTENTE
# ============================================================

def cargar_memoria() -> list:
    try:
        with open(MEMORIA_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("notas", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def guardar_nota(nota: str) -> None:
    notas = cargar_memoria()
    notas.append(nota)
    with open(MEMORIA_PATH, "w", encoding="utf-8") as f:
        json.dump({"notas": notas}, f, ensure_ascii=False, indent=2)


def construir_system_prompt() -> str:
    notas = cargar_memoria()
    if not notas:
        return BASE_PROMPT
    lista = "\n".join(f"- {n}" for n in notas)
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
            "de sus proyectos, o cualquier cosa que pida recordar)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"nota": {"type": "string", "description": "El dato a recordar, en una frase clara."}},
            "required": ["nota"],
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
    {"type": "web_search_20260209", "name": "web_search"},
]


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
    guardar_nota(nota)
    return f"Anotado en memoria: {nota}"


def tool_rastrear_ofertas(args: dict) -> str:
    """Descarga ofertas reales de Remotive y RemoteOK y filtra por palabras clave."""
    import urllib.request
    import urllib.parse
    consulta = (args.get("palabras_clave") or "python").strip()
    palabras = [p.lower() for p in consulta.split() if p]
    headers = {"User-Agent": "Mozilla/5.0 (NEXUS-job-tracker)"}
    ofertas = []

    # --- Fuente 1: Remotive (busqueda en el servidor) ---
    try:
        q = urllib.parse.quote(consulta)
        url = f"https://remotive.com/api/remote-jobs?search={q}&limit=12"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        n = 0
        for j in data.get("jobs", []):
            blob = (str(j.get("title", "")) + " " + str(j.get("category", "")) + " "
                    + " ".join(j.get("tags", []) or [])).lower()
            if not any(p in blob for p in palabras):
                continue
            ofertas.append(
                f"[Remotive] {j.get('title')} - {j.get('company_name')} "
                f"({j.get('candidate_required_location') or 'remoto'})\n   {j.get('url')}"
            )
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
        for it in data:
            if not isinstance(it, dict) or not it.get("position"):
                continue
            blob = (str(it.get("position", "")) + " " + " ".join(it.get("tags", []) or [])).lower()
            if any(p in blob for p in palabras):
                ofertas.append(f"[RemoteOK] {it.get('position')} - {it.get('company')}\n   {it.get('url')}")
                n += 1
                if n >= 12:
                    break
    except Exception as e:
        ofertas.append(f"(RemoteOK no disponible ahora: {e})")

    utiles = [o for o in ofertas if not o.startswith("(")]
    if not utiles:
        return ("No encontre ofertas con esas palabras (o las fuentes no respondieron). "
                "Prueba con otras como 'python', 'bot', 'scraping', 'automation'.\n"
                + "\n".join(ofertas))
    return "\n".join(ofertas[:24])


def tool_run_command(args: dict) -> str:
    import subprocess
    cmd = args.get("command", "")
    if not _confirmar(f"Nexus quiere EJECUTAR:\n    {cmd}"):
        return "El usuario denego la ejecucion de este comando."
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


def tool_read_file(args: dict) -> str:
    path = args.get("path", "")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"Error al leer '{path}': {e}"


def tool_write_file(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    if not _confirmar(f"Nexus quiere ESCRIBIR el archivo:\n    {path}"):
        return "El usuario denego escribir el archivo."
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Archivo guardado: {path} ({len(content)} caracteres)."
    except Exception as e:
        return f"Error al escribir '{path}': {e}"


def tool_list_directory(args: dict) -> str:
    path = args.get("path") or "."
    try:
        entradas = os.listdir(path)
        return "\n".join(sorted(entradas)) if entradas else "(carpeta vacia)"
    except Exception as e:
        return f"Error al listar '{path}': {e}"


EJECUTORES = {
    "recordar": tool_recordar,
    "rastrear_ofertas": tool_rastrear_ofertas,
    "run_command": tool_run_command,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_directory": tool_list_directory,
}


def ejecutar_herramienta(name: str, args: dict) -> str:
    funcion = EJECUTORES.get(name)
    if funcion is None:
        return f"Herramienta desconocida: {name}"
    return funcion(args)


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

        for _ in range(10):  # tope de seguridad de iteraciones por turno
            try:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=system_prompt,
                    thinking={"type": "adaptive"},
                    tools=TOOLS,
                    messages=messages,
                )
            except anthropic.APIError as e:
                print(f"\n[Error de la API: {e}]")
                break

            for block in response.content:
                if block.type == "text":
                    print(f"\nNexus > {block.text}")

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


if __name__ == "__main__":
    main()
