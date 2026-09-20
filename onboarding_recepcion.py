#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Onboarding de un negocio para el RECEPCIONISTA IA (SaaS), en un comando.

Da de alta (o actualiza) un negocio con sus datos, sus tarifas aprobadas, sus FAQ
y la contraseña de su panel — todo desde un archivo JSON — y te imprime los
enlaces listos para pasar al dueño:

    python onboarding_recepcion.py --archivo docs/negocio_ejemplo.json
    python onboarding_recepcion.py --archivo negocio.json --password "una-clave"

Es idempotente: si el negocio ya existe, actualiza sus datos y hace upsert de
servicios/FAQ (no duplica). Reutiliza nexus_recepcion_saas (aislamiento y logica
de precios: la IA nunca inventa) y nexus_recepcion_panel (contraseña del dueño).

Formato del JSON (todos los campos salvo slug/nombre son opcionales):
{
  "slug": "limpiezas-aurora",
  "nombre": "Limpiezas Aurora",
  "sector": "limpieza",
  "zona": "Madrid",
  "horario": "L-V 9:00-18:00",
  "idioma": "es",
  "moneda": "€",
  "telefono_aviso": "123456789",         // chat_id de Telegram del dueño (avisos)
  "dueno_email": "ana@aurora.es",
  "password": "clave-del-panel",         // o pásala con --password
  "servicios": [
    {"nombre": "limpieza de casa", "base": 80, "por_unidad": 20,
     "unidad": "habitacion", "unidades_incluidas": 1, "notas": "productos incluidos"},
    {"nombre": "limpieza de oficina", "base": 120, "por_unidad": 0.5,
     "unidad": "m2", "unidades_incluidas": 100, "margen": 0.15}
  ],
  "faq": [
    {"pregunta": "¿Que zona cubris?", "respuesta": "Madrid y alrededores."}
  ]
}

Recuerda usar la MISMA base de datos que el servidor (NEXUS_DB_PATH) para que el
alta se vea en la web. Arranca la web con NEXUS_RECEPCION_SAAS=1.
"""

import argparse
import json
import sys

import nexus_recepcion_panel as panel
import nexus_recepcion_saas as saas

# Campos de texto del negocio que aceptamos (ademas de servicios/faq/password).
_CAMPOS = ("sector", "zona", "horario", "idioma", "moneda", "telefono_aviso", "dueno_email")


def onboard(config: dict) -> dict:
    """Da de alta/actualiza un negocio a partir de un dict de configuracion.
    Devuelve un resumen {slug, nombre, servicios, faq, panel, urls}. Lanza
    ValueError si faltan slug/nombre o algun dato es invalido."""
    slug = (config.get("slug") or "").strip().lower()
    nombre = (config.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("Falta 'nombre' del negocio.")
    if not slug:
        slug = saas.slugify(nombre)

    campos = {k: config[k] for k in _CAMPOS if config.get(k) is not None}

    if saas.obtener_negocio(slug) is None:
        saas.crear_negocio(nombre, slug=slug, **campos)
    else:
        saas.actualizar_negocio(slug, nombre=nombre, **campos)

    for s in (config.get("servicios") or []):
        if not s.get("nombre") or s.get("base") is None:
            raise ValueError(f"Servicio invalido (necesita nombre y base): {s!r}")
        saas.agregar_servicio(
            slug, nombre=s["nombre"], base=s["base"],
            por_unidad=s.get("por_unidad", 0.0), unidad=s.get("unidad", ""),
            unidades_incluidas=s.get("unidades_incluidas", 1),
            minimo=s.get("minimo"), maximo=s.get("maximo"),
            margen=s.get("margen"), notas=s.get("notas", ""))

    for f in (config.get("faq") or []):
        if not f.get("pregunta") or not f.get("respuesta"):
            raise ValueError(f"FAQ invalida (necesita pregunta y respuesta): {f!r}")
        saas.agregar_faq(slug, f["pregunta"], f["respuesta"])

    con_password = False
    if config.get("password"):
        panel.fijar_password(slug, config["password"])
        con_password = True

    negocio = saas.obtener_negocio(slug)
    return {
        "slug": slug,
        "nombre": negocio["nombre"],
        "servicios": len(negocio.get("servicios", [])),
        "faq": len(negocio.get("faq", [])),
        "panel": con_password,
        "urls": {
            "chat_cliente": f"/r/{slug}",
            "panel_dueno": f"/panel/{slug}",
            "landing": "/pilot",
        },
    }


def _cargar_archivo(ruta: str) -> dict:
    with open(ruta, "r", encoding="utf-8") as fh:
        datos = json.load(fh)
    if not isinstance(datos, dict):
        raise ValueError("El archivo JSON debe ser un objeto con los datos del negocio.")
    return datos


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Da de alta un negocio del recepcionista IA.")
    ap.add_argument("--archivo", help="Ruta a un JSON con los datos del negocio.")
    ap.add_argument("--slug", help="Slug (URL) del negocio; por defecto se deriva del nombre.")
    ap.add_argument("--nombre", help="Nombre del negocio.")
    ap.add_argument("--sector")
    ap.add_argument("--zona")
    ap.add_argument("--horario")
    ap.add_argument("--idioma")
    ap.add_argument("--moneda")
    ap.add_argument("--telefono-aviso", dest="telefono_aviso")
    ap.add_argument("--dueno-email", dest="dueno_email")
    ap.add_argument("--password", help="Contraseña del panel del dueño (sobreescribe la del archivo).")
    args = ap.parse_args(argv)

    config = _cargar_archivo(args.archivo) if args.archivo else {}
    # Las opciones de la linea de comandos tienen prioridad sobre el archivo.
    for k in ("slug", "nombre", *_CAMPOS, "password"):
        v = getattr(args, k, None)
        if v is not None:
            config[k] = v

    if not (config.get("nombre") or config.get("slug")):
        ap.error("Indica al menos --nombre (o un --archivo con 'nombre').")

    try:
        r = onboard(config)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    base = "http://localhost:5000"
    print(f"✓ Negocio listo: {r['nombre']}  (slug: {r['slug']})")
    print(f"  Servicios: {r['servicios']} · FAQ: {r['faq']} · Panel con contraseña: {'si' if r['panel'] else 'NO (define password)'}")
    print("  Enlaces (sobre tu dominio):")
    print(f"    Chat del cliente : {base}{r['urls']['chat_cliente']}")
    print(f"    Panel del dueño  : {base}{r['urls']['panel_dueno']}")
    print(f"    Landing piloto   : {base}{r['urls']['landing']}")
    if not r["panel"]:
        print("  Nota: sin contraseña el dueño no puede entrar al panel. Usa --password.")
    print("  Arranca la web con: NEXUS_RECEPCION_SAAS=1 python nexus_web.py "
          "(misma NEXUS_DB_PATH que este alta).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
