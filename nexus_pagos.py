#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pagos / suscripciones para NEXUS (scaffold de Stripe).

Deja listo el cobro por suscripción: en cuanto pongas tus claves de Stripe y los
IDs de precio, el botón "Probar Pro" genera una sesión de Checkout. La librería
'stripe' se importa de forma PEREZOSA: sin configurar, Nexus funciona igual y el
endpoint avisa de lo que falta.

Puesta en marcha:
  1) pip install stripe
  2) En https://dashboard.stripe.com crea Productos/Precios (Pro, Team) y copia
     sus price IDs y tu clave secreta.
  3) Exporta:
       NEXUS_STRIPE_KEY=sk_live_...     (o sk_test_...)
       NEXUS_STRIPE_PRICE_PRO=price_...
       NEXUS_STRIPE_PRICE_TEAM=price_...
       NEXUS_BASE_URL=https://tu-dominio   (para las URLs de retorno)
"""

import os

STRIPE_KEY = os.environ.get("NEXUS_STRIPE_KEY", "")
BASE_URL = (os.environ.get("NEXUS_BASE_URL") or "http://localhost:5000").rstrip("/")

PLANES = {
    "pro":  {"nombre": "Pro",  "precio": "$9/mes",  "price_env": "NEXUS_STRIPE_PRICE_PRO"},
    "team": {"nombre": "Team", "precio": "$29/mes", "price_env": "NEXUS_STRIPE_PRICE_TEAM"},
}


def configurado() -> bool:
    return bool(STRIPE_KEY)


def crear_checkout(plan: str, email: str = "") -> str:
    """Crea una sesión de Stripe Checkout y devuelve su URL. Lanza si falta config."""
    p = PLANES.get((plan or "").lower())
    if not p:
        raise ValueError(f"Plan invalido: '{plan}'. Usa: {', '.join(PLANES)}.")
    if not STRIPE_KEY:
        raise RuntimeError("Stripe no configurado. Define NEXUS_STRIPE_KEY (ver nexus_pagos.py).")
    price_id = os.environ.get(p["price_env"], "")
    if not price_id:
        raise RuntimeError(f"Falta el ID de precio {p['price_env']} para el plan {p['nombre']}.")
    try:
        import stripe
    except ImportError:
        raise RuntimeError("Falta la libreria 'stripe'. Ejecuta: pip install stripe")
    stripe.api_key = STRIPE_KEY
    sesion = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=BASE_URL + "/app?pago=ok",
        cancel_url=BASE_URL + "/landing",
        customer_email=email or None,
    )
    return sesion.url
