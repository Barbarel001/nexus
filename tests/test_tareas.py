# -*- coding: utf-8 -*-
"""Tests de productividad (tareas/recordatorios). Usan un archivo temporal."""

import datetime

import pytest

import nexus
import nexus_tareas as tareas


@pytest.fixture(autouse=True)
def _archivo_temporal(tmp_path, monkeypatch):
    """Cada test usa su propio tareas.json en un directorio temporal."""
    monkeypatch.setattr(tareas, "TAREAS_PATH", str(tmp_path / "tareas.json"))


# --------------------------- Alta y persistencia ---------------------------

def test_agregar_y_listar():
    tareas.agregar("Comprar pan")
    pend = tareas.filtrar("pendientes")
    assert len(pend) == 1
    assert pend[0]["texto"] == "Comprar pan"
    assert pend[0]["hecha"] is False
    assert len(pend[0]["id"]) == 6


def test_agregar_vacio_falla():
    with pytest.raises(ValueError):
        tareas.agregar("   ")


def test_prioridad_invalida_cae_a_media():
    t = tareas.agregar("X", prioridad="urgentisima")
    assert t["prioridad"] == "media"


# --------------------------- Fechas / recordatorios ---------------------------

def test_normalizar_fecha_hoy_y_manana():
    hoy = datetime.date.today()
    assert tareas.normalizar_fecha("hoy") == hoy.isoformat()
    assert tareas.normalizar_fecha("manana") == (hoy + datetime.timedelta(days=1)).isoformat()
    assert tareas.normalizar_fecha("") == ""


def test_normalizar_fecha_invalida():
    with pytest.raises(ValueError):
        tareas.normalizar_fecha("32-13-2026")


def test_filtro_vencidas_y_hoy():
    ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    hoy = datetime.date.today().isoformat()
    manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    tareas.agregar("Atrasada", vence=ayer)
    tareas.agregar("Para hoy", vence=hoy)
    tareas.agregar("Futura", vence=manana)
    assert [t["texto"] for t in tareas.filtrar("vencidas")] == ["Atrasada"]
    assert [t["texto"] for t in tareas.filtrar("hoy")] == ["Para hoy"]
    assert len(tareas.filtrar("pendientes")) == 3


def test_orden_por_vencimiento():
    futuro = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
    proximo = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    tareas.agregar("Sin fecha")
    tareas.agregar("Lejana", vence=futuro)
    tareas.agregar("Pronto", vence=proximo)
    orden = [t["texto"] for t in tareas.filtrar("pendientes")]
    assert orden == ["Pronto", "Lejana", "Sin fecha"]  # con fecha primero, mas proxima antes


# --------------------------- Completar / eliminar ---------------------------

def test_completar_por_texto():
    tareas.agregar("Llamar al banco")
    out = tareas.completar("banco")
    assert "completada" in out.lower()
    assert tareas.filtrar("pendientes") == []
    assert len(tareas.filtrar("hechas")) == 1


def test_completar_por_id():
    t = tareas.agregar("Tarea con id")
    out = tareas.completar(t["id"])
    assert "completada" in out.lower()


def test_completar_inexistente():
    assert "No encontre" in tareas.completar("fantasma")


def test_completar_ambiguo_pide_precision():
    tareas.agregar("Revisar informe A")
    tareas.agregar("Revisar informe B")
    out = tareas.completar("revisar informe")
    assert "varias" in out.lower()
    assert tareas.filtrar("pendientes")  # no completa nada si es ambiguo


def test_eliminar():
    tareas.agregar("Borrame")
    assert "eliminada" in tareas.eliminar("borrame").lower()
    assert tareas.filtrar("todas") == []


# --------------------------- Resumen y render ---------------------------

def test_resumen_pendientes():
    assert tareas.resumen_pendientes() == ""  # sin tareas, vacio
    ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    tareas.agregar("a")
    tareas.agregar("b", vence=ayer)
    r = tareas.resumen_pendientes()
    assert "2 tareas pendientes" in r and "1 vencidas" in r


def test_render_vacio():
    assert tareas.render([], "nada") == "nada"


# --------------------------- Herramientas y registro ---------------------------

def test_tool_agregar_tarea():
    out = tareas.tool_agregar_tarea({"texto": "Pagar luz", "vence": "hoy", "prioridad": "alta"})
    assert "anotada" in out.lower() and "Pagar luz" in out


def test_tools_registradas_en_nexus():
    nombres = {t.get("name") for t in nexus.TOOLS}
    assert {"agregar_tarea", "listar_tareas", "completar_tarea", "eliminar_tarea"} <= nombres
    for n in ("agregar_tarea", "listar_tareas", "completar_tarea", "eliminar_tarea"):
        assert n in nexus.EJECUTORES


def test_tareas_no_son_peligrosas():
    assert not (tareas.TAREAS_SEGURAS & nexus.HERRAMIENTAS_PELIGROSAS)


# --------------------------- DTO para la web ---------------------------

def test_dto_severidad():
    import datetime as _dt
    ayer = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    t = tareas.agregar("Pagar", vence=ayer, prioridad="alta")
    d = tareas.dto(t)
    assert d["sev"] == "vencida" and d["prioridad"] == "alta"
    assert d["id"] == t["id"] and "vencida" in d["etiqueta"]


# --------------------------- Endpoints del panel (web) ---------------------------

def test_api_panel():
    import nexus_web
    tareas.agregar("Tarea del panel")
    c = nexus_web.app.test_client()
    r = c.get("/api/panel")
    assert r.status_code == 200
    data = r.get_json()
    assert "nt" in data and "tareas" in data
    assert any(t["texto"] == "Tarea del panel" for t in data["tareas"])
    assert "ok" in data["nt"] and "cuenta" in data["nt"]


def test_api_completar_tarea():
    import nexus_web
    t = tareas.agregar("Completar via API")
    c = nexus_web.app.test_client()
    r = c.post("/api/tarea/completar", json={"ref": t["id"]})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert tareas.filtrar("pendientes") == []


def test_api_completar_sin_ref():
    import nexus_web
    c = nexus_web.app.test_client()
    r = c.post("/api/tarea/completar", json={})
    assert r.status_code == 400
