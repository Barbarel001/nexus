# -*- coding: utf-8 -*-
"""Tests del scaffold de Google (Calendar/Gmail). No tocan la API real: se prueba
el registro de herramientas, la degradacion sin configurar, y la confirmacion."""

import nexus
import nexus_google as google


def test_degrada_sin_configurar(monkeypatch):
    """Sin librerias/token, las herramientas avisan en vez de romper."""
    monkeypatch.setattr(google, "librerias_ok", lambda: False)
    assert "no esta configurado" in google.tool_agenda({}).lower()
    assert "no esta configurado" in google.tool_correos({}).lower()


def test_crear_evento_valida_args():
    # sin librerias da ayuda; validamos primero la falta de argumentos
    assert "Indica" in google.tool_crear_evento({"titulo": ""})
    assert "Indica" in google.tool_enviar_correo({"para": ""})


def test_resumen_accion():
    r = google.resumen_accion("google_enviar_correo", {"para": "a@b.com", "asunto": "Hola"})
    assert "a@b.com" in r
    r2 = google.resumen_accion("google_crear_evento", {"titulo": "Reunión", "inicio": "2026-07-01T10:00:00"})
    assert "Reunión" in r2


def test_tools_registradas():
    nombres = {t.get("name") for t in nexus.TOOLS}
    assert {"google_agenda", "google_correos", "google_crear_evento", "google_enviar_correo"} <= nombres
    for n in ("google_agenda", "google_correos", "google_crear_evento", "google_enviar_correo"):
        assert n in nexus.EJECUTORES


def test_acciones_son_peligrosas():
    assert google.GOOGLE_PELIGROSAS <= nexus.HERRAMIENTAS_PELIGROSAS
    assert not (google.GOOGLE_SEGURAS & nexus.HERRAMIENTAS_PELIGROSAS)


def test_accion_requiere_confirmacion(monkeypatch):
    """Crear evento denegado en la confirmacion no llama a la API."""
    monkeypatch.setattr(nexus, "_confirmar", lambda *_: False)
    out = nexus.EJECUTORES["google_crear_evento"]({"titulo": "X", "inicio": "2026-07-01T10:00:00"})
    assert "denego" in out.lower()
