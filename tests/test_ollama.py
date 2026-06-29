# -*- coding: utf-8 -*-
"""Tests del backend local Ollama: conversión de herramientas, disponibilidad
(sin servidor) y el bucle agéntico con un stream simulado."""

import urllib.request

import nexus_ollama


# --------------------------- Conversión de herramientas ---------------------------

def test_tools_ollama_filtra_peligrosas_y_websearch():
    out = nexus_ollama.tools_ollama(False)
    nombres = {t["function"]["name"] for t in out}
    assert "run_command" not in nombres and "write_file" not in nombres
    assert "web_search" not in nombres                  # web_search es server-side de Anthropic
    assert all(t["type"] == "function" for t in out)
    assert all("parameters" in t["function"] for t in out)


def test_tools_ollama_incluye_peligrosas_si_se_pide():
    off = {t["function"]["name"] for t in nexus_ollama.tools_ollama(False)}
    on = {t["function"]["name"] for t in nexus_ollama.tools_ollama(True)}
    assert "run_command" in on and "run_command" not in off


# --------------------------- Disponibilidad (sin Ollama) ---------------------------

def test_disponible_false_sin_servidor(monkeypatch):
    def boom(*a, **k):
        raise OSError("sin conexión")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert nexus_ollama.disponible() is False
    assert nexus_ollama.modelos_instalados() == []


# --------------------------- Bucle agéntico (stream simulado) ---------------------------

def test_chat_eventos_flujo_con_herramienta(monkeypatch):
    # Ronda 1: el modelo pide una herramienta. Ronda 2: responde con texto.
    rondas = iter([
        [{"message": {"content": "", "tool_calls": [{"function": {"name": "nt_estado", "arguments": {}}}]},
          "done": True, "prompt_eval_count": 5, "eval_count": 2}],
        [{"message": {"content": "Listo"}, "done": True, "prompt_eval_count": 3, "eval_count": 4}],
    ])

    def fake_stream(payload):
        yield from next(rondas)

    monkeypatch.setattr(nexus_ollama, "_stream_chat", fake_stream)

    llamadas = []
    def ejecutar(nombre, args):
        llamadas.append(nombre)
        return "resultado-" + nombre

    eventos = list(nexus_ollama.chat_eventos(
        [{"role": "user", "content": "hola"}], "sistema", [], ejecutar))
    tipos = [e[0] for e in eventos]

    assert llamadas == ["nt_estado"]              # ejecutó la herramienta pedida
    assert ("tool", "nt_estado") in eventos
    assert ("delta", "Listo") in eventos
    fin = [pl for ev, pl in eventos if ev == "fin"][0]
    assert fin["text"] == "Listo"
    assert fin["in"] == 8 and fin["out"] == 6      # tokens acumulados de ambas rondas
