# -*- coding: utf-8 -*-
"""Tests del bot de Telegram y el scheduler proactivo. Sin red: se prueban las
funciones puras y el despacho seguro de herramientas."""

import datetime

import nexus_alertas as alertas
import nexus_ninjatrader as nt
import nexus_scheduler as sched
import nexus_tareas as tareas
import nexus_telegram as tg

# --------------------------- Telegram: utilidades ---------------------------

def test_partir_mensaje_largo():
    trozos = tg.partir_mensaje("x" * 9000, limite=4000)
    assert len(trozos) == 3 and all(len(t) <= 4000 for t in trozos)


def test_partir_mensaje_vacio():
    assert tg.partir_mensaje("") == ["(sin respuesta)"]


def test_extraer_mensaje():
    upd = {"message": {"chat": {"id": 123}, "text": "hola"}}
    assert tg.extraer_mensaje(upd) == (123, "hola")
    assert tg.extraer_mensaje({"message": {"chat": {"id": 1}}}) == (None, None)  # sin texto
    assert tg.extraer_mensaje({}) == (None, None)


def test_extraer_foto():
    upd = {"message": {"chat": {"id": 7}, "photo": [{"file_id": "a"}, {"file_id": "big"}], "caption": "mira"}}
    assert tg.extraer_foto(upd) == (7, "big", "mira")
    assert tg.extraer_foto({"message": {"chat": {"id": 1}, "text": "hola"}}) == (None, None, None)


def test_permitido(monkeypatch):
    monkeypatch.setattr(tg, "CHATS_PERMITIDOS", {"123"})
    assert tg.permitido(123) is True
    assert tg.permitido(999) is False
    monkeypatch.setattr(tg, "CHATS_PERMITIDOS", set())
    assert tg.permitido(999) is True  # sin allowlist, cualquiera


def test_ejecutar_seguro_permite_y_bloquea(tmp_path, monkeypatch):
    monkeypatch.setattr(tareas, "TAREAS_PATH", str(tmp_path / "t.json"))
    # herramienta segura: funciona
    out = tg._ejecutar_seguro("agregar_tarea", {"texto": "desde telegram"})
    assert "anotada" in out.lower()
    # herramienta peligrosa: bloqueada
    bloq = tg._ejecutar_seguro("nt_orden", {"instrument": "ES", "action": "BUY", "qty": 1})
    assert "no esta disponible" in bloq.lower()


def test_comandos_basicos(tmp_path, monkeypatch):
    monkeypatch.setattr(tareas, "TAREAS_PATH", str(tmp_path / "t.json"))
    assert "NEXUS" in tg._manejar(1, "/start")
    assert "cero" in tg._manejar(1, "/nuevo").lower()
    tareas.agregar("una tarea")
    assert "una tarea" in tg._manejar(1, "/tareas")


def test_help_lista_comandos_nuevos():
    ayuda = tg._manejar(1, "/help")
    for c in ("/clima", "/noticias", "/gastos", "/agenda", "/correos"):
        assert c in ayuda


def test_comando_clima_con_argumento(monkeypatch):
    capt = {}
    monkeypatch.setattr(tg, "_ejecutar_seguro", lambda n, a: capt.setdefault(n, a) or "ok")
    tg._manejar(1, "/clima Madrid")
    assert capt["clima"]["ciudad"] == "Madrid"


# --------------------------- Scheduler: logica pura ---------------------------

def test_parse_hora():
    assert sched._parse_hora("08:30") == (8, 30)
    assert sched._parse_hora("") is None
    assert sched._parse_hora("malo") is None


def test_toca_briefing():
    hoy = datetime.datetime(2026, 6, 26, 9, 0)
    # ya pasaron las 8:00 y no se ha enviado hoy -> toca
    assert sched.toca_briefing(hoy, None, "08:00") is True
    # ya se envio hoy -> no
    assert sched.toca_briefing(hoy, datetime.date(2026, 6, 26), "08:00") is False
    # aun no son las 10:00 -> no
    assert sched.toca_briefing(hoy, None, "10:00") is False
    # hora vacia -> desactivado
    assert sched.toca_briefing(hoy, None, "") is False


def test_componer_briefing(tmp_path, monkeypatch):
    monkeypatch.setattr(tareas, "TAREAS_PATH", str(tmp_path / "t.json"))
    monkeypatch.setattr(alertas, "ALERTAS_PATH", str(tmp_path / "a.json"))
    tareas.agregar("Pagar luz", vence="hoy")
    alertas.agregar("ES 12-25", "sube", 5000)
    texto = sched.componer_briefing(instrumentos=[])
    assert "resumen de hoy" in texto.lower()
    assert "Pagar luz" in texto
    assert "ES 12-25" in texto


def test_revisar_alertas_dispara(tmp_path, monkeypatch):
    monkeypatch.setattr(alertas, "ALERTAS_PATH", str(tmp_path / "a.json"))
    alertas.agregar("ES", "sube", 5000)
    monkeypatch.setattr(nt, "leer_precio", lambda *a, **k: "5012")
    msgs = sched.revisar_alertas()
    assert len(msgs) == 1 and "ES" in msgs[0]


def test_correr_ciclo_unico_envia(tmp_path, monkeypatch):
    """Un ciclo del scheduler dispara la alerta y la 'envia' (capturada)."""
    monkeypatch.setattr(alertas, "ALERTAS_PATH", str(tmp_path / "a.json"))
    alertas.agregar("ES", "sube", 5000)
    monkeypatch.setattr(nt, "leer_precio", lambda *a, **k: "5012")
    enviados = []
    monkeypatch.setattr(sched.telegram, "enviar", lambda msg, *a, **k: enviados.append(msg))
    sched.correr(intervalo=0, _max_ciclos=1)
    assert any("ES" in m for m in enviados)
