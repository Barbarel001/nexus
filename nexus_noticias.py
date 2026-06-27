#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Noticias de mercado para NEXUS (titulares por RSS, sin APIs de pago).

Descarga titulares de fuentes financieras publicas (RSS) y los resume. Se usa:
  - como herramienta del agente ('noticias_mercado'),
  - en el resumen matutino del scheduler.

Configuracion:
    NEXUS_NEWS_FEEDS   URLs RSS separadas por coma (si quieres tus propias fuentes).
"""

import os
import urllib.request
import xml.etree.ElementTree as ET

# Fuentes por defecto (RSS publicos de mercados). Configurables por entorno.
_DEFAULT_FEEDS = [
    "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
    "https://www.investing.com/rss/news_25.rss",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
]
_feeds_env = os.environ.get("NEXUS_NEWS_FEEDS") or ",".join(_DEFAULT_FEEDS)
FEEDS = [u.strip() for u in _feeds_env.split(",") if u.strip()]

_HEADERS = {"User-Agent": "Mozilla/5.0 (NEXUS-news)"}


def _parse_feed(xml_bytes: bytes) -> list:
    """Extrae (titulo, url) de un RSS. Tolerante a fallos de formato."""
    out = []
    try:
        raiz = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for item in raiz.iter("item"):
        titulo = item.findtext("title") or ""
        link = item.findtext("link") or ""
        titulo = titulo.strip()
        if titulo:
            out.append({"titulo": titulo, "url": link.strip()})
    return out


def obtener(n: int = 8, feeds: list = None) -> list:
    """Descarga y combina titulares de las fuentes. Deduplica por titulo."""
    feeds = feeds if feeds is not None else FEEDS
    vistos, noticias = set(), []
    for url in feeds:
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                datos = r.read()
        except Exception:
            continue
        for it in _parse_feed(datos):
            clave = it["titulo"].lower()
            if clave in vistos:
                continue
            vistos.add(clave)
            noticias.append(it)
            if len(noticias) >= n:
                break
        if len(noticias) >= n:
            break
    return noticias[:n]


def texto_titulares(n: int = 8) -> str:
    """Titulares en texto plano (para el resumen matutino)."""
    noticias = obtener(n)
    if not noticias:
        return ""
    return "\n".join(f"  • {x['titulo']}" for x in noticias)


# ============================================================
#  HERRAMIENTA  (SEGURA)
# ============================================================

def tool_noticias(args: dict) -> str:
    try:
        n = int(args.get("n", 8))
    except (TypeError, ValueError):
        n = 8
    n = max(1, min(n, 20))
    noticias = obtener(n)
    if not noticias:
        return "No pude obtener titulares de mercado ahora mismo (fuentes no disponibles)."
    out = ["📰 Titulares de mercado:"]
    for x in noticias:
        linea = f"  • {x['titulo']}"
        if x["url"]:
            linea += f"\n    {x['url']}"
        out.append(linea)
    return "\n".join(out)


NEWS_TOOLS = [
    {
        "name": "noticias_mercado",
        "description": ("Trae los ultimos titulares de noticias de mercados financieros "
                        "(via RSS publicos). Opcional 'n' = cuantos titulares."),
        "input_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "Cuantos titulares (defecto 8)."}},
            "required": [],
        },
    },
]

NEWS_SEGURAS = {"noticias_mercado"}
NEWS_EJECUTORES = {"noticias_mercado": tool_noticias}
