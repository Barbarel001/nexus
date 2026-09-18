# -*- coding: utf-8 -*-
"""Tests de la capa multi-tenant (SaaS) del recepcionista. No tocan la red:
prueban el almacen por negocio, el AISLAMIENTO entre negocios, precios/FAQ por
tenant, el limite por IP, el gate de actividad y el endpoint publico (con el
modelo simulado)."""

import pytest

import nexus_db
import nexus_recepcion_saas as saas
import nexus_recepcionista as recep


@pytest.fixture(autouse=True)
def _db_temporal(tmp_path, monkeypatch):
    """Cada test usa su propia base SQLite y su propio estado en memoria."""
    monkeypatch.setattr(nexus_db, "DB_PATH", str(tmp_path / "saas.db"))
    saas._HITS.clear()
    saas._SESIONES.clear()
    saas.init()


# --------------------------- Slug ---------------------------

def test_slugify():
    assert saas.slugify("Limpiezas Sol S L") == "limpiezas-sol-s-l"
    assert saas.slugify("  Café  Málaga ") == "cafe-malaga"
    assert saas.slugify("") == "negocio"


def test_crear_negocio_defaults():
    n = saas.crear_negocio("Limpiezas Sol")
    assert n["slug"] == "limpiezas-sol"
    assert n["moneda"] == "€" and n["idioma"] == "es"
    assert n["activo"] is True
    assert n["servicios"] == [] and n["faq"] == []


def test_slug_duplicado_falla():
    saas.crear_negocio("Taller Uno", slug="taller")
    with pytest.raises(ValueError):
        saas.crear_negocio("Taller Dos", slug="taller")


def test_slug_invalido_falla():
    with pytest.raises(ValueError):
        saas.crear_negocio("X", slug="con espacio")  # espacio
    with pytest.raises(ValueError):
        saas.crear_negocio("X", slug="-mal")        # empieza por guion
    with pytest.raises(ValueError):
        saas.crear_negocio("X", slug="acento_é")     # caracter no permitido


def test_nombre_vacio_falla():
    with pytest.raises(ValueError):
        saas.crear_negocio("   ")


# --------------------------- CRUD y configuracion ---------------------------

def test_actualizar_negocio():
    saas.crear_negocio("Peluqueria Ana", slug="ana")
    saas.actualizar_negocio("ana", sector="peluqueria", zona="Centro")
    n = saas.obtener_negocio("ana")
    assert n["sector"] == "peluqueria" and n["zona"] == "Centro"


def test_agregar_servicio_y_faq_persisten():
    saas.crear_negocio("Limpiezas Sol", slug="sol")
    saas.agregar_servicio("sol", "limpieza casa", base=80, por_unidad=20,
                          unidad="habitacion", unidades_incluidas=1)
    saas.agregar_faq("sol", "horario", "9 a 18h")
    n = saas.obtener_negocio("sol")
    assert n["servicios"][0]["nombre"] == "limpieza casa"
    assert n["faq"][0]["respuesta"] == "9 a 18h"


def test_operar_negocio_inexistente_falla():
    with pytest.raises(ValueError):
        saas.agregar_servicio("fantasma", "x", base=10)


# --------------------------- Aislamiento multi-tenant ---------------------------

def test_servicios_y_faq_aislados_por_negocio():
    saas.crear_negocio("A", slug="a")
    saas.crear_negocio("B", slug="b")
    saas.agregar_servicio("a", "corte", base=10)
    saas.agregar_faq("a", "horario", "solo A")
    assert saas.obtener_negocio("b")["servicios"] == []
    assert saas.obtener_negocio("b")["faq"] == []


def test_leads_aislados_por_negocio():
    saas.crear_negocio("A", slug="a")
    saas.crear_negocio("B", slug="b")
    saas.capturar_lead("a", contacto="600111222", servicio="corte", avisar=False)
    assert len(saas.listar_leads("a")) == 1
    assert len(saas.listar_leads("b")) == 0


def test_marcar_lead_no_cruza_negocios():
    saas.crear_negocio("A", slug="a")
    saas.crear_negocio("B", slug="b")
    lead = saas.capturar_lead("a", contacto="600111222", servicio="x", avisar=False)
    # Intentar marcarlo desde OTRO negocio no debe encontrarlo.
    assert "No encontre" in saas.marcar_lead("b", lead["id"], "ganado")
    assert "ganado" in saas.marcar_lead("a", lead["id"], "ganado")


# --------------------------- Leads: cualificacion y filtros ---------------------------

def test_capturar_lead_cualifica():
    saas.crear_negocio("A", slug="a")
    ok = saas.capturar_lead("a", contacto="600111222", servicio="corte", avisar=False)
    assert ok["calificado"] is True
    no = saas.capturar_lead("a", nombre="incompleto", avisar=False)
    assert no["calificado"] is False
    assert len(saas.listar_leads("a", "cualificados")) == 1


def test_marcar_lead_estado_invalido():
    saas.crear_negocio("A", slug="a")
    lead = saas.capturar_lead("a", contacto="600111222", servicio="x", avisar=False)
    assert "invalido" in saas.marcar_lead("a", lead["id"], "flotando").lower()


# --------------------------- Precios por tenant (misma logica, sin inventar) ---------------------------

def test_ejecutor_precio_por_negocio_y_captura_en_el_tenant_correcto():
    saas.crear_negocio("A", slug="a")
    saas.crear_negocio("B", slug="b")
    saas.agregar_servicio("a", "limpieza casa", base=80, por_unidad=20, unidades_incluidas=1)
    ejec = saas._ejecutor_de("a", saas.obtener_negocio("a"), recep.nuevo_estado(), max_leads=3)
    # Precio calculado desde la tarifa aprobada de A (3 habitaciones = 80 + 2*20).
    assert "120" in ejec("estimar_precio", {"servicio": "limpieza casa", "cantidad": 3})
    # B no tiene esa tarifa: no se inventa un precio.
    ejec_b = saas._ejecutor_de("b", saas.obtener_negocio("b"), recep.nuevo_estado(), max_leads=3)
    assert "confirma" in ejec_b("estimar_precio", {"servicio": "limpieza casa"}).lower()
    # La captura de A no aparece en B.
    ejec("capturar_lead", {"contacto": "600111222", "servicio": "limpieza casa"})
    assert len(saas.listar_leads("a")) == 1 and len(saas.listar_leads("b")) == 0


def test_ejecutor_rechaza_herramienta_desconocida():
    saas.crear_negocio("A", slug="a")
    ejec = saas._ejecutor_de("a", saas.obtener_negocio("a"), recep.nuevo_estado(), 3)
    assert "no disponible" in ejec("recepcion_leads", {}).lower()


def test_tope_leads_por_conversacion_en_saas():
    saas.crear_negocio("A", slug="a")
    estado = recep.nuevo_estado()
    ejec = saas._ejecutor_de("a", saas.obtener_negocio("a"), estado, max_leads=1)
    assert "referencia" in ejec("capturar_lead", {"contacto": "600111222", "servicio": "x"}).lower()
    assert "ya he registrado" in ejec("capturar_lead", {"contacto": "600333444", "servicio": "y"}).lower()
    assert len(saas.listar_leads("a")) == 1


# --------------------------- Limite por IP ---------------------------

def test_rate_limit_por_clave():
    assert all(saas.permitido("ip1", limite=3, ventana=60) for _ in range(3))
    assert saas.permitido("ip1", limite=3, ventana=60) is False
    # Otra clave (otra IP) no se ve afectada.
    assert saas.permitido("ip2", limite=3, ventana=60) is True


def test_rate_limit_desactivado_con_cero():
    assert all(saas.permitido("ipx", limite=0) for _ in range(50))


# --------------------------- Gate de actividad ---------------------------

def test_responder_negocio_inactivo_no_llama_al_modelo():
    saas.crear_negocio("A", slug="a")
    saas.fijar_estado_cuenta("a", activo=False)
    r = saas.responder_cliente("a", "hola")  # no debe tocar la red
    assert r["ok"] is False


def test_responder_negocio_inexistente_no_llama_al_modelo():
    r = saas.responder_cliente("fantasma", "hola")
    assert r["ok"] is False


# --------------------------- Endpoint publico (Flask) ---------------------------

@pytest.fixture()
def cliente_web():
    flask = pytest.importorskip("flask")
    app = flask.Flask(__name__)
    app.register_blueprint(saas.crear_blueprint())
    return app.test_client()


def test_pagina_publica_200_y_404(cliente_web):
    saas.crear_negocio("Limpiezas Sol", slug="sol")
    assert cliente_web.get("/r/sol").status_code == 200
    assert cliente_web.get("/r/desconocido").status_code == 404


def test_pagina_inactiva_404(cliente_web):
    saas.crear_negocio("A", slug="a")
    saas.fijar_estado_cuenta("a", activo=False)
    assert cliente_web.get("/r/a").status_code == 404


def test_chat_endpoint_usa_responder(cliente_web, monkeypatch):
    saas.crear_negocio("A", slug="a")
    monkeypatch.setattr(saas, "responder_cliente",
                        lambda slug, msg, **kw: {"ok": True, "texto": f"eco:{msg}"})
    r = cliente_web.post("/r/a/chat", json={"mensaje": "hola", "sid": "s1"})
    assert r.status_code == 200 and r.get_json()["texto"] == "eco:hola"


def test_chat_endpoint_rate_limit_429(cliente_web, monkeypatch):
    saas.crear_negocio("A", slug="a")
    monkeypatch.setattr(saas, "responder_cliente",
                        lambda slug, msg, **kw: {"ok": True, "texto": "ok"})
    monkeypatch.setattr(saas, "RATE_MAX", 2)
    codigos = [cliente_web.post("/r/a/chat", json={"mensaje": "x", "sid": "s"}).status_code
               for _ in range(3)]
    assert codigos.count(429) >= 1
