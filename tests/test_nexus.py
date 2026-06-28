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


# --------------------------- Endpoints web (sin red ni API) ---------------------------

def test_api_config():
    c = nexus_web.app.test_client()
    r = c.get("/api/config")
    assert r.status_code == 200
    data = r.get_json()
    assert "acciones" in data and "modelo" in data and "modelos" in data


def test_api_nueva_devuelve_id():
    c = nexus_web.app.test_client()
    r = c.post("/api/nueva")
    assert r.status_code == 200
    assert len(r.get_json()["id"]) == 12


def test_renombrar_conversacion(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_web, "CONV_PATH", str(tmp_path / "conversaciones.json"))
    nexus_web.guardar_convs({"convs": [{"id": "abc", "titulo": "Viejo", "creado": "", "turnos": []}]})
    c = nexus_web.app.test_client()
    r = c.post("/api/conversacion/abc/renombrar", json={"titulo": "Nuevo nombre"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert nexus_web.buscar_conv(nexus_web.cargar_convs(), "abc")["titulo"] == "Nuevo nombre"


def test_renombrar_inexistente(tmp_path, monkeypatch):
    monkeypatch.setattr(nexus_web, "CONV_PATH", str(tmp_path / "conversaciones.json"))
    c = nexus_web.app.test_client()
    r = c.post("/api/conversacion/nope/renombrar", json={"titulo": "X"})
    assert r.status_code == 404


def test_confirm_rid_desconocido():
    c = nexus_web.app.test_client()
    r = c.post("/api/confirm", json={"rid": "noexiste", "ok": True})
    assert r.status_code == 200 and r.get_json()["ok"] is False


def test_resumen_accion():
    assert "echo hola" in nexus_web.resumen_accion("run_command", {"command": "echo hola"})
    assert "archivo" in nexus_web.resumen_accion("write_file", {"path": "x.txt", "content": "ab"}).lower()


# --------------------------- Autenticacion (login opcional) ---------------------------

def test_sin_password_no_pide_login():
    """Por defecto (sin NEXUS_PASSWORD) no hay login: el uso local sigue igual."""
    c = nexus_web.app.test_client()
    assert c.get("/api/config").status_code == 200


def test_landing_publica():
    c = nexus_web.app.test_client()
    r = c.get("/landing")
    assert r.status_code == 200 and b"NEXUS" in r.data


def test_setup_status():
    c = nexus_web.app.test_client()
    r = c.get("/api/setup-status")
    assert r.status_code == 200
    d = r.get_json()
    for k in ("api_key", "ollama", "ninjatrader", "telegram", "google"):
        assert k in d


def test_landing_publica_con_password(monkeypatch):
    """La landing y los iconos deben ser accesibles aunque haya login activo."""
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "x")
    c = nexus_web.app.test_client()
    assert c.get("/landing").status_code == 200
    assert c.get("/app").status_code in (301, 302)  # la app sí pide login


def test_vision_sin_imagen():
    c = nexus_web.app.test_client()
    r = c.post("/api/vision", json={})
    assert r.status_code == 400


def test_vision_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(nexus_web, "CONV_PATH", str(tmp_path / "c.json"))
    # No llamamos a la API real: simulamos el analisis.
    monkeypatch.setattr(nexus_web.nexus, "analizar_imagen",
                        lambda *a, **k: ("Veo un gráfico alcista del ES.", {"in": 10, "out": 5}))
    c = nexus_web.app.test_client()
    r = c.post("/api/vision", json={"image": "data:image/png;base64,AAAA", "prompt": "analiza", "cid": "abc"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and "alcista" in d["texto"]
    # se guardo en la conversacion
    conv = nexus_web.buscar_conv(nexus_web.cargar_convs(), "abc")
    assert conv and any("vision" in (t.get("tools") or []) for t in conv["turnos"])


def test_con_password_bloquea_y_permite(monkeypatch):
    monkeypatch.setattr(nexus_web, "NEXUS_PASSWORD", "secreta123")
    c = nexus_web.app.test_client()
    # sin login: la API responde 401 y las paginas redirigen al login
    assert c.get("/api/config").status_code == 401
    assert c.get("/").status_code in (301, 302)
    # login con clave incorrecta no autentica
    c.post("/login", data={"password": "mala"})
    assert c.get("/api/config").status_code == 401
    # login correcto: ya hay acceso
    r = c.post("/login", data={"password": "secreta123"})
    assert r.status_code in (301, 302)
    assert c.get("/api/config").status_code == 200
    # logout vuelve a bloquear
    c.get("/logout")
    assert c.get("/api/config").status_code == 401
