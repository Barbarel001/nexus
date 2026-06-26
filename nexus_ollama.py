#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backend LOCAL para Nexus usando Ollama (https://ollama.com).

Permite que Nexus funcione con un modelo que corre en TU PC, sin consumir tokens
de la API de Anthropic (coste $0). Se activa con la variable de entorno:

    NEXUS_BACKEND=ollama

y opcionalmente:

    NEXUS_OLLAMA_MODEL=qwen2.5:7b     (modelo a usar; debe estar 'ollama pull'-eado)
    OLLAMA_HOST=http://localhost:11434

Reutiliza las herramientas y la logica de nexus.py. Habla con la API nativa de
Ollama (/api/chat), que soporta tool-calling y streaming. El formato de mensajes
es role/content (estilo OpenAI), distinto al de Anthropic, asi que aqui va su
propio bucle agentico.
"""

import json
import urllib.request

import nexus

OLLAMA_HOST = nexus._env("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = nexus._env("NEXUS_OLLAMA_MODEL", "qwen2.5:7b")


def disponible() -> bool:
    """True si el servidor de Ollama responde."""
    try:
        with urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=3) as r:
            r.read()
        return True
    except Exception:
        return False


def modelos_instalados() -> list:
    """Lista los modelos descargados en Ollama (por nombre)."""
    try:
        with urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def tools_ollama(incluir_peligrosas: bool = False) -> list:
    """Convierte las herramientas de Nexus (formato Anthropic) al formato de Ollama
    (estilo OpenAI: type=function). Omite web_search (es server-side de Anthropic)."""
    out = []
    for t in nexus.TOOLS:
        if str(t.get("type", "")).startswith("web_search"):
            continue
        name = t.get("name")
        if not incluir_peligrosas and name in nexus.HERRAMIENTAS_PELIGROSAS:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _stream_chat(payload: dict):
    """Llama a /api/chat en streaming y va devolviendo cada objeto JSON (una linea)."""
    req = urllib.request.Request(
        OLLAMA_HOST + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        for linea in r:
            linea = linea.strip()
            if linea:
                yield json.loads(linea.decode("utf-8", "replace"))


def chat_eventos(messages: list, system: str, tools: list, ejecutar, max_iter: int = 8):
    """Bucle agentico contra Ollama. Es un GENERADOR que produce tuplas de evento:

        ('delta', texto)        -> fragmento de respuesta
        ('tool',  nombre)       -> se va a ejecutar una herramienta
        ('fin',   {text,in,out})-> terminado (texto final + tokens usados)

    `messages` van en formato role/content. `ejecutar(nombre, args)->str` ejecuta
    la herramienta. El coste siempre es 0 (corre en tu maquina).
    """
    msgs = ([{"role": "system", "content": system}] if system else []) + list(messages)
    texto_final = ""
    tin = tout = 0

    for _ in range(max_iter):
        contenido = ""
        tool_calls = []
        payload = {"model": OLLAMA_MODEL, "messages": msgs, "stream": True}
        if tools:
            payload["tools"] = tools

        for chunk in _stream_chat(payload):
            m = chunk.get("message") or {}
            if m.get("content"):
                contenido += m["content"]
                texto_final += m["content"]
                yield ("delta", m["content"])
            if m.get("tool_calls"):
                tool_calls.extend(m["tool_calls"])
            if chunk.get("done"):
                tin += chunk.get("prompt_eval_count") or 0
                tout += chunk.get("eval_count") or 0

        asistente = {"role": "assistant", "content": contenido}
        if tool_calls:
            asistente["tool_calls"] = tool_calls
        msgs.append(asistente)

        if not tool_calls:
            break

        for tc in tool_calls:
            fn = tc.get("function") or {}
            nombre = fn.get("name") or ""
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            yield ("tool", nombre)
            salida = ejecutar(nombre, args)
            msgs.append({"role": "tool", "content": str(salida)})

    yield ("fin", {"text": texto_final, "in": tin, "out": tout})
