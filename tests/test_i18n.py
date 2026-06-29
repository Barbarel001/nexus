# -*- coding: utf-8 -*-
"""Tests de i18n server-side: páginas de login/registro/2FA en ES/EN según
la cabecera Accept-Language."""

import nexus_web


def test_login_clave_unica_en(monkeypatch):
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "secreta")
    c = nexus_web.app.test_client()
    r = c.get("/login", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert b"Sign in" in r.data and b"Password" in r.data
    assert b'lang="en"' in r.data


def test_login_clave_unica_es_por_defecto(monkeypatch):
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "secreta")
    c = nexus_web.app.test_client()
    r = c.get("/login")               # sin Accept-Language -> español
    assert "Contraseña".encode() in r.data and b"Entrar" in r.data
    assert b'lang="es"' in r.data


def test_login_multiusuario_en(monkeypatch):
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", True)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    c = nexus_web.app.test_client()
    r = c.get("/login", headers={"Accept-Language": "en"})
    assert b"Create account" in r.data and b"No account?" in r.data
