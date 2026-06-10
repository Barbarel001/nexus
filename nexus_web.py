#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS WEB - Interfaz web (HUD) para tu asistente Nexus, con HISTORIAL de
conversaciones persistente (estilo ChatGPT: panel lateral con todas tus charlas).

Reutiliza la logica y herramientas de nexus.py. Respuestas en streaming.

Arranque:
  pip install -r requirements.txt
  python nexus_web.py
(se abre solo en el navegador: http://127.0.0.1:5000)

Las conversaciones se guardan en  conversaciones.json  (junto a este archivo).

SEGURIDAD: en la web, por defecto NO se ejecutan comandos del sistema ni se
escriben archivos (run_command / write_file deshabilitados). Para eso usa la
version de terminal (nexus.py).
"""

import os
import sys
import json
import uuid
import datetime

try:
    import anthropic  # noqa: F401
except ImportError:
    sys.exit("Falta 'anthropic'. Ejecuta: pip install anthropic")
try:
    from flask import Flask, request, Response, send_from_directory, jsonify
except ImportError:
    sys.exit("Falta 'flask'. Ejecuta: pip install flask")

import anthropic
import nexus  # reutilizamos toda la logica del Nexus de terminal

CARPETA = os.path.dirname(os.path.abspath(__file__))
CONV_PATH = os.path.join(CARPETA, "conversaciones.json")

SEGURAS = {"recordar", "rastrear_ofertas", "read_file", "list_directory"}
TOOLS_WEB = [t for t in nexus.TOOLS if t.get("name") not in ("run_command", "write_file")]

SYSTEM_WEB_EXTRA = (
    "\n\nEstas en la interfaz WEB de Nexus: por seguridad NO tienes run_command "
    "ni write_file. Si el usuario pide ejecutar comandos o escribir archivos, "
    "indicale amablemente que use la version de terminal."
)

app = Flask(__name__, static_folder=None)


# ---------------- Persistencia de conversaciones ----------------

def cargar_convs() -> dict:
    try:
        with open(CONV_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"convs": []}


def guardar_convs(data: dict) -> None:
    with open(CONV_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def buscar_conv(data: dict, cid: str):
    for c in data["convs"]:
        if c["id"] == cid:
            return c
    return None


def ahora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------- Herramientas (solo seguras en web) ----------------

def ejecutar_web(name: str, args: dict) -> str:
    if name in SEGURAS:
        try:
            return nexus.EJECUTORES[name](args)
        except Exception as e:
            return f"Error en {name}: {e}"
    return (f"La herramienta '{name}' esta deshabilitada en la web por seguridad. "
            "Indica al usuario que use la terminal.")


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------- Rutas ----------------

@app.route("/")
def index():
    return send_from_directory(os.path.join(CARPETA, "web"), "index.html")


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


@app.route("/api/nueva", methods=["POST"])
def nueva_conv():
    # Devuelve un id; la conversacion se persiste al primer mensaje.
    return jsonify({"id": uuid.uuid4().hex[:12]})


@app.route("/api/stream")
def stream():
    msg = (request.args.get("msg") or "").strip()
    cid = (request.args.get("cid") or "").strip()
    if not msg or not cid:
        return Response(sse("done", {}), mimetype="text/event-stream")

    client = anthropic.Anthropic()
    system_prompt = nexus.construir_system_prompt() + SYSTEM_WEB_EXTRA

    def gen():
        data = cargar_convs()
        conv = buscar_conv(data, cid)
        nueva = conv is None
        if nueva:
            conv = {"id": cid, "titulo": msg[:42] or "Conversacion",
                    "creado": ahora(), "turnos": []}
            data["convs"].insert(0, conv)

        # Reconstruimos el contexto (texto simple) y agregamos el nuevo mensaje.
        api_messages = [{"role": t["role"], "content": t["text"]} for t in conv["turnos"]]
        api_messages.append({"role": "user", "content": msg})
        api_messages = nexus.recortar_contexto(api_messages)

        texto_final = ""
        try:
            for _ in range(10):
                with client.messages.stream(
                    model=nexus.MODEL,
                    max_tokens=nexus.MAX_TOKENS,
                    system=system_prompt,
                    thinking={"type": "adaptive"},
                    tools=TOOLS_WEB,
                    messages=api_messages,
                ) as s:
                    for texto in s.text_stream:
                        texto_final += texto
                        yield sse("delta", {"text": texto})
                    final = s.get_final_message()

                api_messages.append({"role": "assistant", "content": final.content})

                if final.stop_reason == "end_turn":
                    break
                if final.stop_reason == "pause_turn":
                    continue
                if final.stop_reason == "tool_use":
                    resultados = []
                    for b in final.content:
                        if b.type == "tool_use":
                            yield sse("tool", {"name": b.name})
                            salida = ejecutar_web(b.name, b.input)
                            resultados.append({
                                "type": "tool_result",
                                "tool_use_id": b.id,
                                "content": salida,
                            })
                    api_messages.append({"role": "user", "content": resultados})
                    continue
                break
        except Exception as e:
            yield sse("error", {"msg": str(e)})

        # Persistimos el turno (texto simple, suficiente para mostrar y continuar).
        conv["turnos"].append({"role": "user", "text": msg})
        conv["turnos"].append({"role": "assistant", "text": texto_final})
        guardar_convs(data)

        yield sse("done", {"cid": cid, "nueva": nueva, "titulo": conv["titulo"]})

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit('Falta ANTHROPIC_API_KEY. Configurala con:  setx ANTHROPIC_API_KEY "sk-ant-..."')
    import webbrowser
    import threading
    url = "http://127.0.0.1:5000"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"NEXUS web encendido en {url}   (Ctrl+C para detener)")
    app.run(host="127.0.0.1", port=5000, threaded=True)


if __name__ == "__main__":
    main()
