#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RECEPCIONISTA IA — COBRO por suscripcion (Stripe), multi-tenant.

Conecta el cobro al gate que ya existe: cuando un negocio tiene una suscripcion
activa, `activo=1` y su recepcionista atiende (/r/<slug>); cuando la suscripcion
se cancela o deja de pagarse, `activo=0` y el chat responde que el servicio no
esta disponible — sin tocar nada mas del sistema.

Diseño para poder probarlo SIN claves ni red:
  - `procesar_evento(evento)` es un manejador PURO: recibe un evento de Stripe ya
    parseado (dict) y actualiza el negocio (activar/desactivar, guardar ids/plan/
    fin de periodo). Los tests lo llaman directo con payloads de ejemplo.
  - `verificar_firma(payload, cabecera)` valida la firma del webhook con hmac de la
    stdlib (sin la libreria 'stripe'): los tests firman un payload y comprueban que
    verifica, y que una firma mala o caducada se rechaza.
  - `crear_checkout(...)` es lo unico que habla con Stripe (por HTTPS, urllib). Sin
    `NEXUS_STRIPE_KEY` queda desactivado y el endpoint devuelve 503 con el motivo.

Planes (ajusta precios/price IDs a tu cuenta de Stripe):
    NEXUS_STRIPE_PRICE_BASICO / _PRO / _PREMIUM   price IDs (uno por plan)
    NEXUS_STRIPE_KEY, NEXUS_STRIPE_WEBHOOK_SECRET, NEXUS_BASE_URL   (compartidos)
"""

import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request

import nexus_db
import nexus_recepcion_saas as saas
import nexus_util

BASE_URL = (os.environ.get("NEXUS_BASE_URL") or "http://localhost:5000").rstrip("/")
STRIPE_KEY = os.environ.get("NEXUS_STRIPE_KEY", "")
WEBHOOK_SECRET = os.environ.get("NEXUS_STRIPE_WEBHOOK_SECRET", "")
_TOLERANCIA = 300  # segundos de margen para la marca de tiempo de la firma

PLANES = {
    "basico":  {"nombre": "Básico",  "precio": "99€/mes",  "price_env": "NEXUS_STRIPE_PRICE_BASICO"},
    "pro":     {"nombre": "Pro",     "precio": "199€/mes", "price_env": "NEXUS_STRIPE_PRICE_PRO"},
    "premium": {"nombre": "Premium", "precio": "299€/mes", "price_env": "NEXUS_STRIPE_PRICE_PREMIUM"},
}

# Estados de suscripcion de Stripe que consideramos "pagando".
_ACTIVOS = {"active", "trialing"}


# --------------------------- Base de datos / migracion ---------------------------

def _conn():
    conn = sqlite3.connect(nexus_db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Asegura la capa SaaS y añade columnas de cobro a negocios. Idempotente."""
    saas.init()
    with _conn() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(negocios)").fetchall()}
        for col in ("stripe_customer_id", "stripe_subscription_id", "current_period_end"):
            if col not in cols:
                tipo = "INTEGER" if col == "current_period_end" else "TEXT"
                c.execute(f"ALTER TABLE negocios ADD COLUMN {col} {tipo}")


def configurado() -> bool:
    return bool(STRIPE_KEY)


# --------------------------- Estado de cobro por negocio ---------------------------

def _set(slug: str, **cols) -> None:
    if not cols:
        return
    sets = ", ".join(f"{k}=?" for k in cols)
    with _conn() as c:
        c.execute(f"UPDATE negocios SET {sets} WHERE slug=?", (*cols.values(), slug))


def estado_cobro(slug: str):
    """Devuelve {plan, activo, current_period_end, stripe_customer_id} o None."""
    n = saas.obtener_negocio(slug)
    if n is None:
        return None
    init()
    with _conn() as c:
        row = c.execute("""SELECT plan, activo, current_period_end, stripe_customer_id,
                           stripe_subscription_id FROM negocios WHERE slug=?""", (slug,)).fetchone()
    d = dict(row) if row else {}
    d["activo"] = bool(d.get("activo"))
    return d


def _negocio_por(campo: str, valor: str):
    if not valor:
        return None
    init()
    with _conn() as c:
        row = c.execute(f"SELECT slug FROM negocios WHERE {campo}=?", (valor,)).fetchone()
    return row["slug"] if row else None


# --------------------------- Webhook: verificacion de firma ---------------------------

def firmar(payload: bytes, secret: str, ts: int = None) -> str:
    """Construye una cabecera Stripe-Signature valida (util para tests y para firmar)."""
    ts = int(time.time()) if ts is None else ts
    firmado = f"{ts}.".encode() + payload
    v1 = hmac.new(secret.encode(), firmado, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def verificar_firma(payload: bytes, cabecera: str, secret: str = None,
                    tolerancia: int = _TOLERANCIA) -> bool:
    """Verifica la cabecera Stripe-Signature con hmac (sin la libreria stripe).
    Rechaza firmas invalidas o fuera de la ventana de tiempo."""
    secret = WEBHOOK_SECRET if secret is None else secret
    if not secret or not cabecera:
        return False
    partes = {}
    for trozo in cabecera.split(","):
        k, _, v = trozo.partition("=")
        partes.setdefault(k.strip(), v.strip())
    ts, firma = partes.get("t"), partes.get("v1")
    if not ts or not firma:
        return False
    try:
        if tolerancia and abs(time.time() - int(ts)) > tolerancia:
            return False
    except ValueError:
        return False
    firmado = f"{ts}.".encode() + payload
    esperado = hmac.new(secret.encode(), firmado, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, firma)


# --------------------------- Webhook: procesar evento (PURO) ---------------------------

def procesar_evento(evento: dict) -> str:
    """Actualiza el negocio segun un evento de Stripe ya parseado. Devuelve un texto
    de resultado. No lanza ante eventos que no manejamos (los ignora)."""
    tipo = (evento or {}).get("type", "")
    obj = ((evento or {}).get("data") or {}).get("object") or {}

    if tipo == "checkout.session.completed":
        slug = ((obj.get("metadata") or {}).get("negocio") or "").strip()
        plan = ((obj.get("metadata") or {}).get("plan") or "").strip().lower()
        if not slug or saas.obtener_negocio(slug) is None:
            return "checkout sin negocio valido; ignorado."
        init()
        _set(slug, stripe_customer_id=obj.get("customer") or "",
             stripe_subscription_id=obj.get("subscription") or "",
             plan=plan or "pro", activo=1)
        return f"{slug}: suscripcion iniciada (activo)."

    if tipo in ("customer.subscription.updated", "customer.subscription.created",
                "customer.subscription.deleted"):
        slug = (_negocio_por("stripe_subscription_id", obj.get("id"))
                or _negocio_por("stripe_customer_id", obj.get("customer")))
        if not slug:
            return "suscripcion sin negocio asociado; ignorado."
        estado = (obj.get("status") or "").lower()
        activo = 0 if tipo.endswith("deleted") else (1 if estado in _ACTIVOS else 0)
        cols = {"activo": activo}
        if obj.get("current_period_end"):
            cols["current_period_end"] = int(obj["current_period_end"])
        if obj.get("id"):
            cols["stripe_subscription_id"] = obj["id"]
        init()
        _set(slug, **cols)
        return f"{slug}: suscripcion {estado or 'eliminada'} -> {'activo' if activo else 'inactivo'}."

    return f"evento '{tipo}' ignorado."


# --------------------------- Checkout (unico que habla con Stripe) ---------------------------

def crear_checkout(slug: str, plan: str, email: str = "") -> str:
    """Crea una sesion de Stripe Checkout para un negocio y devuelve su URL.
    Lanza ValueError (plan/negocio) o RuntimeError (config) con motivo claro."""
    if saas.obtener_negocio(slug) is None:
        raise ValueError(f"No existe el negocio '{slug}'.")
    p = PLANES.get((plan or "").lower())
    if not p:
        raise ValueError(f"Plan invalido: '{plan}'. Usa: {', '.join(PLANES)}.")
    if not STRIPE_KEY:
        raise RuntimeError("Stripe no configurado. Define NEXUS_STRIPE_KEY.")
    price_id = os.environ.get(p["price_env"], "")
    if not price_id:
        raise RuntimeError(f"Falta {p['price_env']} para el plan {p['nombre']}.")
    datos = [
        ("mode", "subscription"),
        ("line_items[0][price]", price_id),
        ("line_items[0][quantity]", "1"),
        ("success_url", f"{BASE_URL}/panel/{slug}?pago=ok"),
        ("cancel_url", f"{BASE_URL}/panel/{slug}"),
        ("metadata[negocio]", slug),
        ("metadata[plan]", (plan or "").lower()),
        ("subscription_data[metadata][negocio]", slug),
    ]
    if email:
        datos.append(("customer_email", email))
    req = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=urllib.parse.urlencode(datos).encode(),
        headers={"Authorization": f"Bearer {STRIPE_KEY}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        sesion = json.loads(r.read().decode("utf-8", "replace"))
    url = sesion.get("url")
    if not url:
        raise RuntimeError("Stripe no devolvio URL de checkout.")
    return url


# --------------------------- Endpoint (Flask blueprint) ---------------------------

def crear_blueprint():
    """Blueprint de cobro:
        POST /billing/<slug>/checkout   {plan,email} -> {url}   (503 si sin Stripe)
        GET  /billing/<slug>/estado     -> {plan, activo}
        POST /billing/webhook           webhook de Stripe (verifica firma)
    """
    from flask import Blueprint, abort, jsonify, request

    bp = Blueprint("recepcion_cobro", __name__)

    @bp.post("/billing/<slug>/checkout")
    def checkout(slug):
        if saas.obtener_negocio(slug) is None:
            abort(404)
        d = request.get_json(silent=True) or request.form.to_dict() or {}
        try:
            url = crear_checkout(slug, d.get("plan", ""), d.get("email", ""))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
        except Exception as e:
            nexus_util.log(f"cobro: checkout {slug} fallo: {e}", "ERROR")
            return jsonify({"error": "No se pudo iniciar el pago."}), 502
        return jsonify({"url": url})

    @bp.get("/billing/<slug>/estado")
    def estado(slug):
        e = estado_cobro(slug)
        if e is None:
            abort(404)
        return jsonify({"plan": e.get("plan"), "activo": e.get("activo")})

    @bp.post("/billing/webhook")
    def webhook():
        payload = request.get_data()
        firma = request.headers.get("Stripe-Signature", "")
        if not verificar_firma(payload, firma):
            abort(400)
        try:
            evento = json.loads(payload.decode("utf-8", "replace"))
        except ValueError:
            abort(400)
        msg = procesar_evento(evento)
        nexus_util.log(f"cobro webhook: {msg}", "INFO")
        return jsonify({"ok": True})

    return bp
