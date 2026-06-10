# -*- coding: utf-8 -*-
"""Tests de Nexus. No tocan la red ni la API de Claude:
las funciones puras se prueban directo y la red se simula con monkeypatch."""

import json
import urllib.request

import nexus
import nexus_web


# --------------------------- Memoria persistente ---------------------------

def test_guardar_y_cargar_memoria(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    assert nexus.cargar_memoria() == []
    nexus.guardar_nota("Mi tarifa es 20 USD/hora")
    nexus.guardar_nota("Me llamo Barbarel")
    assert nexus.cargar_memoria() == ["Mi tarifa es 20 USD/hora", "Me llamo Barbarel"]


def test_cargar_memoria_archivo_corrupto(tmp_path, monkeypatch):
    mem = tmp_path / "memoria.json"
    mem.write_text("{esto no es json valido", encoding="utf-8")
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(mem))
    assert nexus.cargar_memoria() == []  # degrada con gracia, no revienta


# --------------------------- System prompt ---------------------------

def test_system_prompt_sin_notas(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    assert nexus.construir_system_prompt() == nexus.BASE_PROMPT


def test_system_prompt_incluye_notas(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    nexus.guardar_nota("Dato importante X")
    prompt = nexus.construir_system_prompt()
    assert "Dato importante X" in prompt
    assert "NEXUS" in prompt


# --------------------------- Herramientas ---------------------------

def test_tool_recordar_vacio():
    assert "No se indico" in nexus.tool_recordar({"nota": "   "})


def test_tool_recordar_guarda(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    out = nexus.tool_recordar({"nota": "Recuerda esto"})
    assert "Recuerda esto" in out
    assert "Recuerda esto" in nexus.cargar_memoria()


def test_ejecutar_herramienta_desconocida():
    assert "desconocida" in nexus.ejecutar_herramienta("no_existe", {})


def test_list_directory(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("y")
    out = nexus.tool_list_directory({"path": str(tmp_path)})
    assert "a.txt" in out and "b.txt" in out


def test_read_y_write_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "PEDIR_CONFIRMACION", False)  # evita el prompt interactivo
    f = tmp_path / "nota.txt"
    res = nexus.tool_write_file({"path": str(f), "content": "hola"})
    assert "guardado" in res.lower()
    assert nexus.tool_read_file({"path": str(f)}) == "hola"


# --------------------------- Rastreador de ofertas (red simulada) ---------------------------

class _FakeResp:
    def __init__(self, data):
        self._d = json.dumps(data).encode("utf-8")

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_rastrear_ofertas_filtra_por_palabra_clave(monkeypatch):
    remotive = {"jobs": [
        {"title": "Python Developer", "category": "Software", "tags": ["python"],
         "company_name": "Acme", "candidate_required_location": "Worldwide", "url": "http://x/1"},
        {"title": "Graphic Designer", "category": "Design", "tags": ["figma"],
         "company_name": "Beta", "url": "http://x/2"},
    ]}
    remoteok = [
        {"position": "Python Bot Engineer", "tags": ["python", "bot"], "company": "Gamma", "url": "http://x/3"},
        {"position": "Sales Rep", "tags": ["sales"], "company": "Delta", "url": "http://x/4"},
    ]

    def fake_urlopen(req, timeout=0):
        return _FakeResp(remotive if "remotive" in req.full_url else remoteok)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = nexus.tool_rastrear_ofertas({"palabras_clave": "python"})
    assert "Python Developer" in out
    assert "Python Bot Engineer" in out
    assert "Graphic Designer" not in out
    assert "Sales Rep" not in out


# --------------------------- Recorte de contexto ---------------------------

def test_recortar_contexto_no_toca_historial_corto():
    msgs = [{"role": "user", "content": "hola"}]
    assert nexus.recortar_contexto(msgs, 40) == msgs


def test_recortar_contexto_corta_en_frontera_limpia():
    msgs = []
    for i in range(60):
        msgs.append({"role": "user", "content": f"pregunta {i}"})
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": f"respuesta {i}"}]})
    recortado = nexus.recortar_contexto(msgs, 10)
    assert len(recortado) < len(msgs)
    assert recortado[0]["role"] == "user"
    assert isinstance(recortado[0]["content"], str)  # empieza en un mensaje de texto, no en un tool_result


def test_recortar_contexto_no_deja_tool_result_huerfano():
    msgs = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok2"}]},
    ]
    recortado = nexus.recortar_contexto(msgs, 3)
    primero = recortado[0]
    es_tool_result = primero["role"] == "user" and isinstance(primero["content"], list)
    assert not es_tool_result


# --------------------------- Persistencia de conversaciones (web) ---------------------------

def test_conversaciones_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_web, "CONV_PATH", str(tmp_path / "conversaciones.json"))
    assert nexus_web.cargar_convs() == {"convs": []}
    data = {"convs": [{"id": "abc", "titulo": "Demo", "creado": "2026-06-10", "turnos": []}]}
    nexus_web.guardar_convs(data)
    assert nexus_web.cargar_convs() == data
    assert nexus_web.buscar_conv(data, "abc")["titulo"] == "Demo"
    assert nexus_web.buscar_conv(data, "no_existe") is None
