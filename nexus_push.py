#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notificaciones Web Push para NEXUS — avisos del navegador AUNQUE la pestaña esté
cerrada (alertas de precio, resumen matutino). Es OPCIONAL: solo se activa si
configuras claves VAPID y tienes instalada la librería 'pywebpush'. Si falta algo,
todo queda inerte (no rompe nada) y se sigue usando el aviso in-tab de siempre.

Puesta en marcha (una vez):
    pip install pywebpush
    python nexus_push.py genkeys      # genera el par de claves VAPID
    # exporta lo que imprime:
    setx NEXUS_VAPID_PUBLIC  "<clave publica base64url>"
    setx NEXUS_VAPID_PRIVATE "<PEM de la clave privada o ruta a un .pem>"
    setx NEXUS_VAPID_SUBJECT "mailto:tu-correo@ejemplo.com"

Las suscripciones del navegador se guardan en push_subs.json (git-ignored).
Nota: las suscripciones son GLOBALES (pensado para el modo personal, como el
scheduler proactivo), no por usuario.
"""

import json
import os

import nexus_util

_CARPETA = os.path.dirname(os.path.abspath(__file__))
SUBS_PATH = os.environ.get("NEXUS_PUSH_SUBS") or os.path.join(_CARPETA, "push_subs.json")

VAPID_PUBLIC = os.environ.get("NEXUS_VAPID_PUBLIC", "")
VAPID_PRIVATE = os.environ.get("NEXUS_VAPID_PRIVATE", "")
VAPID_SUBJECT = os.environ.get("NEXUS_VAPID_SUBJECT", "mailto:admin@nexus.local")


def _lib_disponible() -> bool:
    try:
        import pywebpush  # noqa: F401
        return True
    except ImportError:
        return False


def configurado() -> bool:
    """True si hay claves VAPID y la librería disponible (push real activable)."""
    return bool(VAPID_PUBLIC and VAPID_PRIVATE and _lib_disponible())


def clave_publica() -> str:
    return VAPID_PUBLIC


def cargar_subs() -> list:
    return (nexus_util.cargar_json(SUBS_PATH, {"subs": []}) or {}).get("subs", [])


def guardar_subs(subs: list) -> None:
    nexus_util.guardar_json(SUBS_PATH, {"subs": subs})


def agregar_sub(sub: dict) -> bool:
    """Guarda una suscripción de PushManager ({endpoint, keys:{p256dh,auth}})."""
    if not isinstance(sub, dict) or not sub.get("endpoint"):
        return False
    subs = cargar_subs()
    if not any(s.get("endpoint") == sub["endpoint"] for s in subs):
        subs.append(sub)
        guardar_subs(subs)
    return True


def quitar_sub(endpoint: str) -> None:
    subs = [s for s in cargar_subs() if s.get("endpoint") != endpoint]
    guardar_subs(subs)


def enviar(titulo: str, cuerpo: str, url: str = "/") -> int:
    """Envía un push a todas las suscripciones. Devuelve cuántas se entregaron.
    No-op (0) si no está configurado. Poda las suscripciones muertas (404/410)."""
    if not configurado():
        return 0
    from pywebpush import WebPushException, webpush
    payload = json.dumps({"title": titulo, "body": cuerpo, "url": url})
    subs = cargar_subs()
    vivos, enviados = [], 0
    for s in subs:
        try:
            webpush(subscription_info=s, data=payload,
                    vapid_private_key=VAPID_PRIVATE,
                    vapid_claims={"sub": VAPID_SUBJECT})
            vivos.append(s)
            enviados += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                continue  # suscripción muerta: descartar
            vivos.append(s)  # error temporal: conservar
        except Exception:
            vivos.append(s)
    if len(vivos) != len(subs):
        guardar_subs(vivos)
    return enviados


def generar_claves() -> dict:
    """Genera un par de claves VAPID (requiere 'cryptography'). Devuelve dict con
    'public' (base64url, para el navegador) y 'private_pem' (para el servidor)."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pk = ec.generate_private_key(ec.SECP256R1())
    priv_pem = pk.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode("ascii")
    punto = pk.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(punto).rstrip(b"=").decode("ascii")
    return {"public": pub_b64, "private_pem": priv_pem}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "genkeys":
        try:
            claves = generar_claves()
        except ImportError:
            sys.exit("Falta 'cryptography'. Ejecuta: pip install cryptography")
        print("== Claves VAPID generadas ==\n")
        print("NEXUS_VAPID_PUBLIC =", claves["public"], "\n")
        print("NEXUS_VAPID_PRIVATE (PEM, guárdalo en un .pem o como variable):\n")
        print(claves["private_pem"])
    else:
        print("Uso: python nexus_push.py genkeys")
