#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Embeddings y búsqueda semántica para NEXUS — RAG "de verdad" (por significado, no
solo por palabras), 100% local y gratis con Ollama.

Si Ollama está disponible con un modelo de embeddings (por defecto
'nomic-embed-text'), Nexus puede comparar textos por su SIGNIFICADO. Si no lo está,
todo el sistema cae con elegancia a la búsqueda por palabras clave (nexus_docs).

La parte matemática (coseno, ranking) es pura y se puede testear sin Ollama
inyectando una función de embedding.

Configuración:
    NEXUS_EMBED_MODEL   Modelo de embeddings en Ollama (defecto 'nomic-embed-text').
    OLLAMA_HOST         Host de Ollama (lo comparte con nexus_ollama).
"""

import os
import json
import math
import urllib.request

import nexus_ollama

EMBED_MODEL = os.environ.get("NEXUS_EMBED_MODEL", "nomic-embed-text")


def disponible() -> bool:
    """True si Ollama responde y el modelo de embeddings está instalado."""
    if not nexus_ollama.disponible():
        return False
    instalados = nexus_ollama.modelos_instalados()
    return any(m == EMBED_MODEL or m.startswith(EMBED_MODEL + ":") for m in instalados)


def embed(texto: str):
    """Vector de embedding de un texto vía Ollama, o None si falla/está vacío."""
    texto = (texto or "").strip()
    if not texto:
        return None
    payload = {"model": EMBED_MODEL, "prompt": texto}
    req = urllib.request.Request(
        nexus_ollama.OLLAMA_HOST + "/api/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        vec = data.get("embedding")
        return vec if vec else None
    except Exception:
        return None


def coseno(a, b) -> float:
    """Similitud coseno entre dos vectores (0 si alguno es nulo/incompatible)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    punto = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return punto / (na * nb)


def rank(consulta_vec, items, key: str = "vec", k: int = 4) -> list:
    """Ordena `items` (cada uno con item[key] = vector) por similitud a consulta_vec.
    Devuelve los k mejores, cada uno con 'score' añadido."""
    if not consulta_vec:
        return []
    salida = []
    for it in items:
        v = it.get(key)
        if not v:
            continue
        s = coseno(consulta_vec, v)
        if s > 0:
            salida.append({**it, "score": round(s, 4)})
    salida.sort(key=lambda r: r["score"], reverse=True)
    return salida[:k]
