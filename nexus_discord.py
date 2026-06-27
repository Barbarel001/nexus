#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notificaciones a Discord para NEXUS (via Webhook entrante de un canal).

Es un canal de SALIDA: Nexus puede enviarte alertas y el resumen matutino a un
canal de Discord. Mas simple que un bot completo y muy util.

Como obtener el webhook: en tu servidor de Discord -> Editar canal -> Integraciones
-> Webhooks -> Nuevo webhook -> Copiar URL.

Configuracion:
    NEXUS_DISCORD_WEBHOOK   URL del webhook del canal.
"""

import os
import json
import urllib.request

WEBHOOK = os.environ.get("NEXUS_DISCORD_WEBHOOK") or ""


def configurado() -> bool:
    return bool(WEBHOOK)


def _trozos(texto: str, limite: int = 1900):
    texto = texto or ""
    return [texto[i:i + limite] for i in range(0, len(texto), limite)] or [""]


def enviar(texto: str) -> bool:
    """Envia un mensaje al canal de Discord. Nunca lanza; devuelve True/False."""
    if not WEBHOOK or not texto:
        return False
    ok = True
    for trozo in _trozos(texto):
        datos = json.dumps({"content": trozo}).encode("utf-8")
        req = urllib.request.Request(WEBHOOK, data=datos,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read()
        except Exception:
            ok = False
    return ok
