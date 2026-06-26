# -*- coding: utf-8 -*-
"""Tests del 'cerebro': memoria avanzada (categorias/busqueda/olvido, con
compatibilidad hacia atras) y RAG-lite sobre documentos."""

import json

import pytest

import nexus
import nexus_docs as docs


# --------------------------- Memoria: compatibilidad ---------------------------

def test_memoria_compat_formato_viejo(tmp_path, monkeypatch):
    """El formato antiguo (lista de strings) se sigue leyendo."""
    mem = tmp_path / "memoria.json"
    mem.write_text(json.dumps({"notas": ["soy viejo dato", "otro"]}), encoding="utf-8")
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(mem))
    assert nexus.cargar_memoria() == ["soy viejo dato", "otro"]
    notas = nexus.cargar_notas()
    assert notas[0]["categoria"] == "general" and notas[0]["texto"] == "soy viejo dato"


def test_memoria_con_categoria(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    assert nexus.guardar_nota("Mi tarifa es 25/h", "trabajo") is True
    assert nexus.guardar_nota("Mi tarifa es 25/h", "trabajo") is False  # dedup
    notas = nexus.cargar_notas()
    assert notas[0]["categoria"] == "trabajo"
    # el system prompt agrupa por categoria
    assert "[trabajo]" in nexus.construir_system_prompt()


def test_buscar_y_olvidar(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    nexus.guardar_nota("Me gusta el cafe", "personal")
    nexus.guardar_nota("Opero futuros del ES", "trading")
    assert len(nexus.buscar_notas("trading")) == 1
    assert len(nexus.buscar_notas("ES")) == 1
    nota_id = nexus.cargar_notas()[0]["id"]
    assert "Olvidado" in nexus.olvidar_nota(nota_id)
    assert len(nexus.cargar_notas()) == 1


def test_olvidar_inexistente(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    assert "No encontre" in nexus.olvidar_nota("fantasma")


def test_tools_memoria_registradas():
    nombres = {t.get("name") for t in nexus.TOOLS}
    assert {"recordar", "buscar_memoria", "olvidar_memoria"} <= nombres
    for n in ("buscar_memoria", "olvidar_memoria"):
        assert n in nexus.EJECUTORES


# --------------------------- Documentos / RAG-lite ---------------------------

def test_docs_busca_relevante(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "DOCS_DIR", str(tmp_path))
    (tmp_path / "notas.md").write_text(
        "El plan de trading usa medias moviles.\n\nLa receta de la abuela lleva canela.",
        encoding="utf-8")
    (tmp_path / "otro.txt").write_text("Documento sin relacion sobre jardineria.", encoding="utf-8")
    hits = docs.buscar("medias moviles trading", k=3)
    assert hits and "medias moviles" in hits[0]["texto"]


def test_docs_sin_coincidencia(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "DOCS_DIR", str(tmp_path))
    (tmp_path / "a.txt").write_text("hola mundo", encoding="utf-8")
    assert docs.buscar("xyzzy supercalifragilistico", k=3) == []


def test_docs_tool_sin_carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "DOCS_DIR", str(tmp_path / "no_existe"))
    out = docs.tool_buscar_documentos({"consulta": "algo"})
    assert "No hay carpeta" in out


def test_docs_tool_registrada():
    assert "buscar_documentos" in nexus.EJECUTORES
    assert "buscar_documentos" in {t.get("name") for t in nexus.TOOLS}


# --------------------------- Endpoints de memoria (web) ---------------------------

def test_api_memoria(tmp_path, monkeypatch):
    import nexus_web
    monkeypatch.setattr(nexus, "MEMORIA_PATH", str(tmp_path / "memoria.json"))
    nexus.guardar_nota("dato web", "personal")
    c = nexus_web.app.test_client()
    r = c.get("/api/memoria")
    assert r.status_code == 200
    assert any(n["texto"] == "dato web" for n in r.get_json()["notas"])
    # olvidar via API
    nid = nexus.cargar_notas()[0]["id"]
    r2 = c.post("/api/memoria/olvidar", json={"ref": nid})
    assert r2.get_json()["ok"] is True
