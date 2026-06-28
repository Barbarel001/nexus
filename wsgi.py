#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Punto de entrada WSGI para producción (gunicorn / uvicorn-worker / etc.).

    gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:5000 wsgi:app

IMPORTANTE: usa UN SOLO worker (-w 1). El estado de Nexus (streaming SSE, caché de
conversaciones, hilos del bot de Telegram y del scheduler) vive en memoria y debe
compartirse en un único proceso. Para escalar horizontalmente habría que mover ese
estado a la BD/colas (siguiente milestone del SaaS).
"""

import nexus_web

# Arranca el bot de Telegram + scheduler si están configurados (no se llama a main()
# bajo gunicorn, así que lo hacemos aquí).
try:
    nexus_web._arrancar_proactivo()
except Exception:
    pass

app = nexus_web.app
