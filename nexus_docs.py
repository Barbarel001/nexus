#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Documentos / RAG-lite para NEXUS.

Permite que Nexus responda con base en TUS documentos: pones archivos en una
carpeta y Nexus busca los fragmentos mas relevantes para una pregunta. No usa
embeddings de pago: hace una recuperacion por solapamiento de palabras (TF),
suficiente para notas, manuales y apuntes, y 100% local/gratis.

Formatos: .txt y .md siempre; .pdf si tienes 'pypdf' instalado (opcional).

Configuracion:
    NEXUS_DOCS_DIR   Carpeta de documentos (defecto: ./documentos junto a este script).
"""

import os
import re
import glob

_CARPETA = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.environ.get("NEXUS_DOCS_DIR") or os.path.join(_CARPETA, "documentos")

_PALABRA = re.compile(r"[\wáéíóúüñ]+", re.IGNORECASE)
# Palabras vacias comunes (es/en) que no aportan a la relevancia.
_STOP = set("de la el en y a los las un una que con por para se su al lo como mas pero "
            "the of to and in is it for on with as at by an be or this that".split())


def _tokens(texto: str):
    return [w.lower() for w in _PALABRA.findall(texto or "") if w.lower() not in _STOP and len(w) > 2]


def _leer_pdf(path: str) -> str:
    try:
        import pypdf  # opcional
    except ImportError:
        return ""
    try:
        lector = pypdf.PdfReader(path)
        return "\n".join((p.extract_text() or "") for p in lector.pages)
    except Exception:
        return ""


def _leer(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _leer_pdf(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _trozos(texto: str, tam: int = 600):
    """Parte un texto en fragmentos por parrafos, agrupando hasta ~tam caracteres."""
    bloques, actual = [], ""
    for parrafo in re.split(r"\n\s*\n", texto):
        parrafo = parrafo.strip()
        if not parrafo:
            continue
        if len(actual) + len(parrafo) + 1 > tam and actual:
            bloques.append(actual.strip())
            actual = parrafo
        else:
            actual = (actual + "\n" + parrafo).strip()
    if actual:
        bloques.append(actual.strip())
    return bloques


def indexar(carpeta: str = None) -> list:
    """Lee la carpeta y devuelve una lista de fragmentos: {archivo, texto, tokens}."""
    carpeta = carpeta or DOCS_DIR
    if not os.path.isdir(carpeta):
        return []
    frags = []
    for path in sorted(glob.glob(os.path.join(carpeta, "**", "*"), recursive=True)):
        if not os.path.isfile(path):
            continue
        if os.path.splitext(path)[1].lower() not in (".txt", ".md", ".pdf"):
            continue
        contenido = _leer(path)
        for tr in _trozos(contenido):
            frags.append({"archivo": os.path.basename(path), "texto": tr, "tokens": _tokens(tr)})
    return frags


def buscar(consulta: str, k: int = 4, carpeta: str = None) -> list:
    """Devuelve los k fragmentos mas relevantes para la consulta (por solapamiento
    de palabras). Cada item: {archivo, texto, score}."""
    q = set(_tokens(consulta))
    if not q:
        return []
    resultados = []
    for fr in indexar(carpeta):
        if not fr["tokens"]:
            continue
        comunes = sum(1 for t in fr["tokens"] if t in q)
        if comunes:
            score = comunes / (len(fr["tokens"]) ** 0.5)  # normaliza por longitud
            resultados.append({"archivo": fr["archivo"], "texto": fr["texto"], "score": round(score, 3)})
    resultados.sort(key=lambda r: r["score"], reverse=True)
    return resultados[:k]


# ============================================================
#  HERRAMIENTA  (SEGURA)
# ============================================================

def tool_buscar_documentos(args: dict) -> str:
    consulta = (args.get("consulta") or "").strip()
    if not consulta:
        return "Indica que quieres buscar en tus documentos."
    if not os.path.isdir(DOCS_DIR):
        return (f"No hay carpeta de documentos en {DOCS_DIR}. Crea la carpeta y pon ahi "
                "tus .txt, .md o .pdf para que pueda consultarlos.")
    hits = buscar(consulta)
    if not hits:
        return "No encontre nada relevante en tus documentos para esa consulta."
    out = ["Fragmentos relevantes de tus documentos:"]
    for h in hits:
        out.append(f"\n— {h['archivo']} (relevancia {h['score']}):\n{h['texto'][:800]}")
    return "\n".join(out)


DOCS_TOOLS = [
    {
        "name": "buscar_documentos",
        "description": ("Busca en los documentos personales del usuario (carpeta de docs: "
                        ".txt/.md/.pdf) los fragmentos mas relevantes para responder una "
                        "pregunta basada en SUS archivos. Usalo cuando pregunte por algo que "
                        "este en sus apuntes, manuales o notas."),
        "input_schema": {
            "type": "object",
            "properties": {"consulta": {"type": "string", "description": "Lo que se quiere encontrar."}},
            "required": ["consulta"],
        },
    },
]

DOCS_SEGURAS = {"buscar_documentos"}
DOCS_EJECUTORES = {"buscar_documentos": tool_buscar_documentos}
