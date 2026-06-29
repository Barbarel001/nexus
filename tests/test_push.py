# -*- coding: utf-8 -*-
"""Tests de Web Push: almacenamiento de suscripciones, gating y endpoints.
No requiere pywebpush ni claves VAPID (se prueban las rutas inertes/seguras)."""

import pytest

import nexus_push as P
import nexus_web


@pytest.fixture(autouse=True)
def _subs_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "SUBS_PATH", str(tmp_path / "subs.json"))
    yield


def test_agregar_y_dedup():
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}
    assert P.agregar_sub(sub) is True
    assert P.agregar_sub(sub) is True            # idempotente
    assert len(P.cargar_subs()) == 1             # no duplica


def test_agregar_invalida():
    assert P.agregar_sub({}) is False
    assert P.agregar_sub({"keys": {}}) is False  # sin endpoint
    assert P.cargar_subs() == []


def test_quitar_sub():
    P.agregar_sub({"endpoint": "e1"})
    P.agregar_sub({"endpoint": "e2"})
    P.quitar_sub("e1")
    assert [s["endpoint"] for s in P.cargar_subs()] == ["e2"]


def test_enviar_inerte_sin_config(monkeypatch):
    # Sin claves VAPID / sin librería -> no-op (0), nunca lanza.
    monkeypatch.setattr(P, "VAPID_PUBLIC", "")
    monkeypatch.setattr(P, "VAPID_PRIVATE", "")
    P.agregar_sub({"endpoint": "e1"})
    assert P.configurado() is False
    assert P.enviar("hola", "mundo") == 0


def test_endpoint_clave_y_suscribir():
    c = nexus_web.app.test_client()
    d = c.get("/api/push/clave").get_json()
    assert "configurado" in d and "clave" in d
    sub = {"endpoint": "https://push.example/z", "keys": {"p256dh": "a", "auth": "b"}}
    assert c.post("/api/push/suscribir", json=sub).get_json()["ok"] is True
    assert any(s["endpoint"] == sub["endpoint"] for s in P.cargar_subs())


def test_generar_claves_si_hay_cryptography():
    try:
        claves = P.generar_claves()
    except BaseException:
        pytest.skip("cryptography no disponible en este entorno")
    assert claves["public"] and "BEGIN PRIVATE KEY" in claves["private_pem"]
