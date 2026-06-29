#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOTP (RFC 6238) en Python puro — segundo factor (2FA) para NEXUS, sin dependencias
externas. Compatible con Google Authenticator, Authy, 1Password, etc.

Funciones:
    generar_secreto()        -> secreto base32 nuevo (para guardar por usuario)
    codigo_actual(secreto)   -> codigo de 6 digitos del periodo actual (para tests)
    verificar(secreto, code) -> True si el codigo es valido (con ventana de +-1)
    uri_otpauth(secreto, email) -> URI otpauth:// para el QR del autenticador
"""

import base64
import hashlib
import hmac
import os
import struct
import time
import urllib.parse

PERIODO = 30          # segundos por codigo
DIGITOS = 6
VENTANA = 1           # acepta el codigo anterior/siguiente (tolerancia de reloj)


def generar_secreto() -> str:
    """Secreto base32 (160 bits) sin relleno '=', como esperan los autenticadores."""
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _codigo(secreto: str, contador: int) -> str:
    relleno = "=" * (-len(secreto) % 8)
    clave = base64.b32decode(secreto.upper() + relleno, casefold=True)
    mensaje = struct.pack(">Q", contador)
    digest = hmac.new(clave, mensaje, hashlib.sha1).digest()
    desplazamiento = digest[-1] & 0x0F
    binario = struct.unpack(">I", digest[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF
    return str(binario % (10 ** DIGITOS)).zfill(DIGITOS)


def codigo_actual(secreto: str, t: float = None, periodo: int = PERIODO) -> str:
    t = time.time() if t is None else t
    return _codigo(secreto, int(t // periodo))


def verificar(secreto: str, codigo: str, t: float = None,
              periodo: int = PERIODO, ventana: int = VENTANA) -> bool:
    """True si 'codigo' coincide con el TOTP de 'secreto' dentro de la ventana."""
    if not secreto:
        return False
    codigo = (codigo or "").strip().replace(" ", "")
    if not codigo.isdigit() or len(codigo) != DIGITOS:
        return False
    t = time.time() if t is None else t
    base = int(t // periodo)
    for delta in range(-ventana, ventana + 1):
        if hmac.compare_digest(_codigo(secreto, base + delta), codigo):
            return True
    return False


def uri_otpauth(secreto: str, email: str, emisor: str = "NEXUS") -> str:
    """URI otpauth:// para generar el codigo QR (o introducir el secreto a mano)."""
    etiqueta = urllib.parse.quote(f"{emisor}:{email or 'cuenta'}")
    params = urllib.parse.urlencode({
        "secret": secreto, "issuer": emisor, "digits": DIGITOS, "period": PERIODO,
    })
    return f"otpauth://totp/{etiqueta}?{params}"
