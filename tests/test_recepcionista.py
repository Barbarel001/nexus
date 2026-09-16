# -*- coding: utf-8 -*-
"""Tests del recepcionista IA para negocios. No tocan la red: prueban la logica
determinista (tarifas, FAQ, leads, prompt) y el aislamiento de herramientas."""

import pytest

import nexus_recepcionista as recep


@pytest.fixture(autouse=True)
def _archivo_temporal(tmp_path, monkeypatch):
    """Cada test usa su propio recepcionista.json en un directorio temporal."""
    monkeypatch.setattr(recep, "RECEPCION_PATH", str(tmp_path / "recepcionista.json"))


# --------------------------- Configuracion ---------------------------

def test_configurar_negocio_pone_defectos():
    n = recep.configurar_negocio(nombre="Limpiezas Sol", sector="limpieza")
    assert n["nombre"] == "Limpiezas Sol"
    assert n["moneda"] == "€"
    assert n["idioma"] == "es"
    assert n["servicios"] == [] and n["faq"] == []


def test_configurar_solo_actualiza_campos_dados():
    recep.configurar_negocio(nombre="A", zona="Centro")
    recep.configurar_negocio(zona="Norte")  # no toca 'nombre'
    n = recep.cargar()["negocio"]
    assert n["nombre"] == "A" and n["zona"] == "Norte"


# --------------------------- Servicios y presupuestos ---------------------------

def test_agregar_servicio_y_estimar_base():
    recep.agregar_servicio("Limpieza casa", base=80, por_unidad=20,
                           unidad="habitacion", unidades_incluidas=1)
    est = recep.estimar_precio("limpieza casa")  # 1 habitacion (la incluida)
    assert est["ok"] is True
    assert est["desde"] == est["hasta"] == 80


def test_estimar_precio_por_unidades_extra():
    recep.agregar_servicio("Limpieza casa", base=80, por_unidad=20, unidades_incluidas=1)
    est = recep.estimar_precio("limpieza casa", cantidad=3)  # base + 2 extra*20
    assert est["desde"] == 120


def test_estimar_respeta_minimo_y_maximo():
    recep.agregar_servicio("Jardin", base=10, por_unidad=5, unidades_incluidas=0,
                           minimo=40, maximo=100)
    assert recep.estimar_precio("jardin", cantidad=1)["desde"] == 40   # sube al minimo
    assert recep.estimar_precio("jardin", cantidad=1000)["hasta"] == 100  # topa al maximo


def test_margen_genera_rango():
    recep.agregar_servicio("Mudanza", base=200, margen=0.15)
    est = recep.estimar_precio("mudanza")
    assert est["desde"] == 170 and est["hasta"] == 230


def test_servicio_no_tarifado_no_inventa_precio():
    recep.configurar_negocio(nombre="X")
    est = recep.estimar_precio("algo que no existe")
    assert est["ok"] is False
    assert "confirma" in recep.formato_presupuesto(est).lower()


def test_agregar_servicio_actualiza_no_duplica():
    recep.agregar_servicio("Corte", base=10)
    recep.agregar_servicio("corte", base=15)  # mismo nombre, distinto caso
    servicios = recep.cargar()["negocio"]["servicios"]
    assert len(servicios) == 1 and servicios[0]["base"] == 15


def test_servicio_sin_nombre_falla():
    with pytest.raises(ValueError):
        recep.agregar_servicio("  ", base=10)


def test_buscar_servicio_tolerante_a_acentos():
    recep.agregar_servicio("Jardinería", base=50)
    assert recep.buscar_servicio("jardineria") is not None


# --------------------------- FAQ ---------------------------

def test_faq_encuentra_por_palabras_clave():
    recep.agregar_faq("¿Cual es vuestro horario?", "Abrimos de 9 a 18h de lunes a viernes.")
    item = recep.buscar_faq("a que hora abris el horario")
    assert item and "9 a 18h" in item["respuesta"]


def test_faq_sin_coincidencia_devuelve_none():
    recep.agregar_faq("horario", "9 a 18h")
    assert recep.buscar_faq("aceptais tarjeta de credito") is None


def test_faq_vacia_falla():
    with pytest.raises(ValueError):
        recep.agregar_faq("pregunta", "   ")


# --------------------------- Leads y cualificacion ---------------------------

def test_lead_con_contacto_y_servicio_es_cualificado():
    lead = recep.capturar_lead(nombre="Ana", contacto="600123456",
                               servicio="limpieza casa", avisar=False)
    assert lead["calificado"] is True
    assert lead["estado"] == "nuevo"
    assert len(lead["id"]) == 6


def test_lead_sin_contacto_no_es_cualificado():
    lead = recep.capturar_lead(nombre="Ana", servicio="limpieza", avisar=False)
    assert lead["calificado"] is False


def test_email_cuenta_como_contacto():
    assert recep._es_contacto("ana@correo.com") is True
    assert recep._es_contacto("600 123 456") is True
    assert recep._es_contacto("hola") is False


def test_listar_leads_filtros():
    recep.capturar_lead(contacto="600111222", servicio="a", avisar=False)   # cualificado
    recep.capturar_lead(nombre="incompleto", avisar=False)                  # no cualificado
    assert len(recep.listar_leads("todos")) == 2
    assert len(recep.listar_leads("cualificados")) == 1
    assert len(recep.listar_leads("nuevos")) == 2


def test_marcar_lead_cambia_estado():
    lead = recep.capturar_lead(contacto="600111222", servicio="a", avisar=False)
    msg = recep.marcar_lead(lead["id"], "ganado")
    assert "ganado" in msg
    assert recep.listar_leads("ganados")[0]["id"] == lead["id"]


def test_marcar_lead_estado_invalido():
    lead = recep.capturar_lead(contacto="600111222", servicio="a", avisar=False)
    assert "invalido" in recep.marcar_lead(lead["id"], "flotando").lower()


def test_marcar_lead_no_encontrado():
    assert "No encontre" in recep.marcar_lead("zzzzzz", "ganado")


# --------------------------- Prompt del cliente (pura) ---------------------------

def test_system_prompt_incluye_reglas_y_servicios():
    recep.configurar_negocio(nombre="Limpiezas Sol", sector="limpieza")
    recep.agregar_servicio("Limpieza casa", base=80)
    prompt = recep.system_prompt_cliente()
    assert "Limpiezas Sol" in prompt
    assert "estimar_precio" in prompt        # obliga a usar la herramienta de precios
    assert "NUNCA inventes" in prompt
    assert "Limpieza casa" in prompt


# --------------------------- Aislamiento de herramientas ---------------------------

def test_herramientas_cliente_no_incluyen_las_del_dueno():
    nombres_cliente = {t["name"] for t in recep.RECEPCION_CLIENTE_TOOLS}
    assert nombres_cliente == {"estimar_precio", "buscar_faq", "capturar_lead"}
    # El cliente NO puede configurar el negocio ni ver leads.
    assert "recepcion_configurar" not in nombres_cliente
    assert "recepcion_leads" not in nombres_cliente


def test_ejecutar_cliente_rechaza_herramienta_desconocida():
    salida = recep.ejecutar_cliente("recepcion_leads", {})  # herramienta del dueño
    assert "no disponible" in salida.lower()


def test_tool_capturar_lead_pide_lo_que_falta():
    salida = recep.tool_capturar_lead({"nombre": "Ana"})  # sin contacto ni servicio
    assert "contacto" in salida.lower() or "servicio" in salida.lower()


def test_tool_estimar_precio_sin_tarifa_no_inventa():
    salida = recep.tool_estimar_precio({"servicio": "algo raro"})
    assert "confirma" in salida.lower()
