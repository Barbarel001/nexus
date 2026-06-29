# -*- coding: utf-8 -*-
"""Guard: cada variable de entorno usada en el código debe estar documentada en
.env.example. Evita que se añada configuración sin documentarla."""

import glob
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Variables que se leen por nombre dinámico (no como literal en _env/os.environ.get)
# y que documentamos a mano en .env.example.
EXTRA = {"NEXUS_STRIPE_PRICE_PRO", "NEXUS_STRIPE_PRICE_TEAM"}


def _vars_en_codigo():
    patron = re.compile(r'(?:_env\(|os\.environ\.get\(|os\.getenv\()"([A-Z][A-Z0-9_]+)"')
    encontradas = set()
    for ruta in glob.glob(os.path.join(RAIZ, "nexus_*.py")) + [os.path.join(RAIZ, "nexus.py")]:
        with open(ruta, encoding="utf-8") as f:
            encontradas |= set(patron.findall(f.read()))
    return encontradas


def test_env_example_documenta_todas_las_variables():
    documentadas = set(re.findall(
        r"^([A-Z][A-Z0-9_]+)=", open(os.path.join(RAIZ, ".env.example"), encoding="utf-8").read(),
        re.M))
    usadas = _vars_en_codigo() | EXTRA
    faltan = sorted(v for v in usadas if v not in documentadas)
    assert not faltan, f"Variables sin documentar en .env.example: {faltan}"
