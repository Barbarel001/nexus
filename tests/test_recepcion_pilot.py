# -*- coding: utf-8 -*-
"""Tests del piloto de validacion. Sin red: prueban la captura de interes, el
embudo/metricas, la siembra de la demo y la landing (Flask)."""

import pytest

import nexus_db
import nexus_recepcion_pilot as pilot
import nexus_recepcion_saas as saas


@pytest.fixture(autouse=True)
def _db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "pilot.db"))
    saas._HITS.clear()
    saas._SESIONES.clear()
    pilot.init()


# --------------------------- Interes del dueño ---------------------------

def test_registrar_interes_valida_email():
    with pytest.raises(ValueError):
        pilot.registrar_interes(email="no-es-email")


def test_registrar_interes_guarda_y_cuenta():
    pilot.registrar_interes(email="ana@correo.com", nombre="Ana", negocio="Limpiezas Ana",
                            avisar=False)
    interesados = pilot.listar_interesados()
    assert len(interesados) == 1 and interesados[0]["email"] == "ana@correo.com"
    # Registrar interes cuenta como evento del embudo.
    assert pilot.metricas()["embudo"]["interes"] == 1


# --------------------------- Embudo / metricas ---------------------------

def test_embudo_cuenta_eventos_y_tasas():
    for _ in range(10):
        pilot.registrar_evento("landing")
    for _ in range(4):
        pilot.registrar_evento("demo_click")
    pilot.registrar_interes(email="a@b.com", avisar=False)
    m = pilot.metricas()
    assert m["embudo"]["landing"] == 10
    assert m["embudo"]["demo_click"] == 4
    assert m["embudo"]["tasa_demo"] == 0.4
    assert m["embudo"]["tasa_interes"] == 0.1


def test_evento_tipo_invalido_se_ignora():
    pilot.registrar_evento("basura")
    assert pilot.metricas()["embudo"] == {
        "landing": 0, "demo_click": 0, "interes": 0, "tasa_demo": 0.0, "tasa_interes": 0.0}


def test_metricas_incluye_leads_por_negocio():
    saas.crear_negocio("Negocio A", slug="a")
    saas.capturar_lead("a", contacto="600111222", servicio="x", avisar=False)
    saas.capturar_lead("a", nombre="incompleto", avisar=False)  # no cualificado
    m = pilot.metricas()
    assert m["leads"]["total"] == 2 and m["leads"]["cualificados"] == 1
    fila = [n for n in m["negocios"] if n["slug"] == "a"][0]
    assert fila["leads"] == 2 and fila["cualificados"] == 1


# --------------------------- Demo sembrada ---------------------------

def test_sembrar_demo_idempotente_y_con_tarifas():
    n1 = pilot.sembrar_demo("demo")
    n2 = pilot.sembrar_demo("demo")  # segunda vez no duplica
    assert n1["slug"] == n2["slug"] == "demo"
    assert len(n2["servicios"]) == 3          # no se duplican
    # La demo da precio real (no inventa): 3 habitaciones = 80 + 2*20.
    import nexus_recepcionista as recep
    est = recep.estimar_precio_en(n2, "limpieza de casa", 3)
    assert est["ok"] and est["desde"] == 120


# --------------------------- Landing (Flask) ---------------------------

@pytest.fixture()
def cliente_web():
    flask = pytest.importorskip("flask")
    app = flask.Flask(__name__)
    app.register_blueprint(pilot.crear_blueprint())
    return app.test_client()


def test_landing_200(cliente_web):
    r = cliente_web.get("/pilot")
    assert r.status_code == 200 and b"recepcionista" in r.data.lower()


def test_landing_css_se_renderiza(cliente_web):
    # Regresion: la landing debe formatearse (sin '{{' crudos) y traer su CSS.
    cuerpo = cliente_web.get("/pilot").get_data(as_text=True)
    # '{{' solo aparece si la plantilla se sirve SIN formatear (el bug); el CSS
    # anidado si produce '}}' legitimo, asi que solo comprobamos '{{'.
    assert "{{" not in cuerpo
    assert "system-ui" in cuerpo


def test_ir_demo_cuenta_clic_y_redirige(cliente_web):
    r = cliente_web.get("/pilot/ir-demo")
    assert r.status_code == 302 and f"/r/{pilot.DEMO_SLUG}" in r.headers["Location"]
    assert pilot.metricas()["embudo"]["demo_click"] == 1


def test_interes_endpoint_guarda(cliente_web):
    r = cliente_web.post("/pilot/interes", json={"email": "due@no.com", "negocio": "Bar Pepe"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert len(pilot.listar_interesados()) == 1


def test_interes_endpoint_email_malo_400(cliente_web):
    r = cliente_web.post("/pilot/interes", json={"email": "malo"})
    assert r.status_code == 400


def test_interes_endpoint_rate_limit_429(cliente_web):
    codigos = [cliente_web.post("/pilot/interes", json={"email": f"a{i}@b.com"}).status_code
               for i in range(12)]
    assert codigos.count(429) >= 1


def test_metricas_token_gate(cliente_web, monkeypatch):
    monkeypatch.setattr(pilot, "PILOT_TOKEN", "secreto")
    assert cliente_web.get("/pilot/metricas").status_code == 403
    assert cliente_web.get("/pilot/metricas?token=secreto").status_code == 200
