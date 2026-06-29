# -*- coding: utf-8 -*-
"""Tests del cerebro avanzado: embeddings (coseno/rank), búsqueda semántica y resumen."""


import nexus
import nexus_ctx
import nexus_docs as docs
import nexus_embeddings as E

# --------------------------- Coseno ---------------------------

def test_coseno():
    assert E.coseno([1, 0, 0], [1, 0, 0]) == 1.0
    assert E.coseno([1, 0], [0, 1]) == 0.0
    assert abs(E.coseno([1, 1], [1, 1]) - 1.0) < 1e-9
    assert E.coseno([], [1]) == 0.0          # vacío
    assert E.coseno([1, 2], [1]) == 0.0      # longitudes distintas
    assert E.coseno([0, 0], [1, 1]) == 0.0   # norma cero


# --------------------------- Rank ---------------------------

def test_rank_ordena_y_limita():
    q = [1, 0]
    items = [
        {"id": "a", "vec": [1, 0]},     # coseno 1
        {"id": "b", "vec": [0, 1]},     # coseno 0 -> se descarta
        {"id": "c", "vec": [0.8, 0.6]},  # coseno 0.8
        {"id": "d", "vec": None},       # sin vector -> se ignora
    ]
    r = E.rank(q, items, k=2)
    assert [x["id"] for x in r] == ["a", "c"]
    assert r[0]["score"] == 1.0 and "score" in r[1]


def test_rank_sin_consulta():
    assert E.rank(None, [{"vec": [1]}]) == []


# --------------------------- Búsqueda semántica ---------------------------

def _fake_embed(t):
    t = (t or "").lower()
    return [1.0 if "perro" in t else 0.0, 1.0 if "gato" in t else 0.0]


def test_buscar_semantica_por_significado(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "DOCS_DIR", str(tmp_path))
    nexus_ctx.clear_user()
    (tmp_path / "canes.md").write_text("Los perros son animales leales y juguetones.")
    (tmp_path / "felinos.md").write_text("Los gatos son independientes y curiosos.")
    hits = docs.buscar_semantica("mascota perro canino", embed=_fake_embed)
    assert hits and "perro" in hits[0]["texto"].lower()


def test_buscar_semantica_fallback_keyword(tmp_path, monkeypatch):
    # Sin embeddings (embed=None y Ollama no disponible) -> cae a palabras clave.
    monkeypatch.setattr(docs, "DOCS_DIR", str(tmp_path))
    nexus_ctx.clear_user()
    (tmp_path / "n.md").write_text("Resumen mensual de ventas y facturación.")
    hits = docs.buscar_semantica("ventas")
    assert hits and "ventas" in hits[0]["texto"].lower()


# --------------------------- Resumen ---------------------------

def test_resumir_texto_inyectado():
    llamado = {}
    def fake(prompt):
        llamado["prompt"] = prompt
        return "Título\n- punto 1\n- punto 2"
    out = nexus.resumir_texto("user: hola\nassistant: qué tal", completar=fake)
    assert out.startswith("Título")
    assert "hola" in llamado["prompt"]      # el texto entra en el prompt


def test_resumir_texto_vacio():
    assert nexus.resumir_texto("", completar=lambda p: "x") == ""


def test_resumen_web(monkeypatch, tmp_path):
    import nexus_web
    monkeypatch.setattr(nexus_web, "NEXUS_MULTIUSER", False)
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "")
    monkeypatch.setattr(nexus_web, "CONV_PATH", str(tmp_path / "conv.json"))
    monkeypatch.setattr(nexus, "resumir_texto", lambda texto: "RESUMEN: " + texto[:10])
    c = nexus_web.app.test_client()
    cid = c.post("/api/nueva").get_json()["id"]
    # crea la conversación con un turno (a través del guardado interno)
    data = {"convs": [{"id": cid, "titulo": "x", "creado": "2026-01-01 00:00",
                       "turnos": [{"role": "user", "text": "hola mundo"}]}]}
    nexus_web.guardar_convs(data)
    r = c.post(f"/api/conversacion/{cid}/resumen")
    assert r.get_json()["ok"] is True and r.get_json()["resumen"].startswith("RESUMEN:")
