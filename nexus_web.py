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
try:
    from flask import Flask, request, Response, send_from_directory, jsonify
except ImportError:
    sys.exit("Falta 'flask'. Ejecuta: pip install flask")

import anthropic
import nexus  # reutilizamos toda la logica del Nexus de terminal
import nexus_ollama  # backend LOCAL opcional (Ollama), coste $0
import nexus_ninjatrader as nt  # puente con NinjaTrader (trading)
import nexus_tareas as tareas  # productividad (tareas/recordatorios)
import nexus_alertas as alertas  # alertas de precio

CARPETA = os.path.dirname(os.path.abspath(__file__))
CONV_PATH = nexus._env("NEXUS_CONV_PATH", os.path.join(CARPETA, "conversaciones.json"))

# Herramientas seguras, siempre disponibles en la web: lectura general, lectura de
# NinjaTrader (estado/precio/posicion, no mueven dinero) y productividad (tareas).
SEGURAS = ({"recordar", "rastrear_ofertas", "read_file", "list_directory"}
           | nt.NT_SEGURAS | tareas.TAREAS_SEGURAS | alertas.ALERTAS_SEGURAS)
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
    with open(CONV_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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

@app.route("/")
def index():
    return send_from_directory(os.path.join(CARPETA, "web"), "index.html")


@app.route("/api/config")
def config():
    return jsonify({"acciones": WEB_ACCIONES, "modelo": nexus.MODEL, "modelos": sorted(MODELOS_OK),
                    "backend": nexus.BACKEND, "ollama_model": nexus_ollama.OLLAMA_MODEL,
                    "ollama_disponible": nexus_ollama.disponible()})


@app.route("/api/panel")
def panel():
    """Datos para el panel-dashboard: estado de NinjaTrader y tareas pendientes."""
    return jsonify({
        "nt": {"ok": nt.carpeta_ok(), "carpeta": nt.NT_FOLDER, "cuenta": nt.NT_ACCOUNT},
        "tareas": [tareas.dto(t) for t in tareas.filtrar("pendientes")],
        "resumen": tareas.resumen_pendientes(),
    })


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
        try:
            for _ in range(10):
                _kw = dict(model=model, max_tokens=nexus.MAX_TOKENS, system=system_prompt,
                           tools=TOOLS_WEB, messages=api_messages)
                _th = nexus.thinking_para(model)
                if _th:
                    _kw["thinking"] = _th
                with client.messages.stream(**_kw) as s:
                    for texto in s.text_stream:
                        texto_final += texto
                        yield sse("delta", {"text": texto})
                    final = s.get_final_message()

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
    url = f"http://127.0.0.1:{port}"
    if nexus._env("NEXUS_OPEN", "1").lower() not in ("0", "false", "no"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    extra = "  [acciones de sistema ON]" if WEB_ACCIONES else ""
    print(f"NEXUS web encendido en {url}{extra}   (Ctrl+C para detener)")
    app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    main()
