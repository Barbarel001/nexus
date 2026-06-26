# -*- coding: utf-8 -*-
"""Tests del puente con NinjaTrader. No necesitan NinjaTrader instalado:
se valida el formato OIF (funciones puras) y el envio/lectura con carpetas temp."""

import os

import pytest

import nexus
import nexus_ninjatrader as nt


# --------------------------- Construccion de comandos OIF ---------------------------

def test_construir_place_market():
    linea = nt.construir_place("Sim101", "AAPL", "buy", 2, "market")
    campos = linea.split(";")
    assert campos[0] == "PLACE"
    assert campos[1] == "Sim101"
    assert campos[2] == "AAPL"          # instrumento en mayuscula
    assert campos[3] == "BUY"           # accion normalizada
    assert campos[4] == "2"             # cantidad entera
    assert campos[5] == "MARKET"
    assert len(campos) == 13            # PLACE + 12 campos


def test_construir_place_limit_incluye_precio():
    linea = nt.construir_place("Sim101", "ES 12-25", "SELL", 1, "LIMIT", limit_price="5000.25")
    campos = linea.split(";")
    assert campos[5] == "LIMIT"
    assert campos[6] == "5000.25"


def test_construir_place_accion_invalida():
    with pytest.raises(ValueError):
        nt.construir_place("Sim101", "AAPL", "comprar", 1)  # 'comprar' no es valida


def test_construir_place_cantidad_invalida():
    with pytest.raises(ValueError):
        nt.construir_place("Sim101", "AAPL", "BUY", 0)
    with pytest.raises(ValueError):
        nt.construir_place("Sim101", "AAPL", "BUY", -3)


def test_construir_place_limit_sin_precio_falla():
    with pytest.raises(ValueError):
        nt.construir_place("Sim101", "AAPL", "BUY", 1, "LIMIT")  # falta limit_price


def test_construir_place_stop_sin_precio_falla():
    with pytest.raises(ValueError):
        nt.construir_place("Sim101", "AAPL", "BUY", 1, "STOPMARKET")  # falta stop_price


def test_construir_cancel():
    assert nt.construir_cancel("abc123").split(";")[:2] == ["CANCEL", "abc123"]


def test_construir_cancel_vacio_falla():
    with pytest.raises(ValueError):
        nt.construir_cancel("")


def test_construir_close_y_flatten():
    assert nt.construir_close("Sim101", "AAPL").startswith("CLOSEPOSITION;Sim101;AAPL")
    assert nt.construir_cancel_all() == "CANCELALLORDERS"
    assert nt.construir_flatten() == "FLATTENEVERYTHING"


# --------------------------- Envio de comandos (carpeta temporal) ---------------------------

def test_enviar_comando_escribe_archivo(tmp_path):
    ruta = nt.enviar_comando("PLACE;Sim101;AAPL;BUY;1;MARKET;;;DAY;;;;", str(tmp_path))
    assert os.path.isfile(ruta)
    assert ruta.endswith(".txt") and "oif_nexus_" in os.path.basename(ruta)
    with open(ruta, encoding="utf-8") as f:
        assert f.read().strip().startswith("PLACE;Sim101;AAPL;BUY;1;MARKET")


def test_enviar_comando_carpeta_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        nt.enviar_comando("CANCELALLORDERS", str(tmp_path / "no_existe"))


# --------------------------- Lectura de precio (archivo simulado) ---------------------------

def test_leer_precio_lee_archivo(tmp_path):
    # Simulamos el archivo que NinjaTrader escribiria tras un SUBSCRIBE.
    (tmp_path / "AAPL_LAST.txt").write_text("231.05", encoding="utf-8")
    valor = nt.leer_precio("AAPL", "LAST", carpeta=str(tmp_path), espera=0.5)
    assert valor == "231.05"


def test_leer_precio_tipo_invalido(tmp_path):
    with pytest.raises(ValueError):
        nt.leer_precio("AAPL", "XYZ", carpeta=str(tmp_path), espera=0)


def test_leer_precio_sin_archivo(tmp_path):
    with pytest.raises(FileNotFoundError):
        nt.leer_precio("AAPL", "LAST", carpeta=str(tmp_path), espera=0)


# --------------------------- Funciones de alto nivel ---------------------------

def test_colocar_orden_invalida_no_revienta(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path))
    out = nt.colocar_orden({"instrument": "AAPL", "action": "nope", "qty": 1})
    assert "rechazada" in out.lower()


def test_colocar_orden_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path))
    out = nt.colocar_orden({"instrument": "AAPL", "action": "BUY", "qty": 2})
    assert "enviada" in out.lower()
    # se escribio un OIF en la carpeta
    assert any(p.startswith("oif_nexus_") for p in os.listdir(tmp_path))


def test_resumen_orden_legible():
    r = nt.resumen_orden({"instrument": "es 12-25", "action": "buy", "qty": 1, "order_type": "market"})
    assert "BUY" in r and "ES 12-25" in r and "MARKET" in r


def test_estado_carpeta_inexistente(monkeypatch, tmp_path):
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path / "nope"))
    assert "NO encuentro" in nt.estado()


# --------------------------- Integracion con el registro de Nexus ---------------------------

def test_nt_tools_registradas_en_nexus():
    nombres = {t.get("name") for t in nexus.TOOLS}
    assert {"nt_estado", "nt_precio", "nt_posicion", "nt_orden", "nt_cancelar", "nt_cerrar"} <= nombres


def test_nt_ejecutores_registrados():
    for n in ("nt_estado", "nt_precio", "nt_posicion", "nt_orden", "nt_cancelar", "nt_cerrar"):
        assert n in nexus.EJECUTORES


def test_ordenes_son_peligrosas():
    assert nt.NT_PELIGROSAS <= nexus.HERRAMIENTAS_PELIGROSAS
    # las de lectura NO son peligrosas
    assert not (nt.NT_SEGURAS & nexus.HERRAMIENTAS_PELIGROSAS)


def test_orden_requiere_confirmacion(monkeypatch, tmp_path):
    """En la terminal, una orden denegada en la confirmacion no se envia."""
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path))
    monkeypatch.setattr(nexus, "_confirmar", lambda *_: False)
    out = nexus.EJECUTORES["nt_orden"]({"instrument": "AAPL", "action": "BUY", "qty": 1})
    assert "denego" in out.lower()
    assert os.listdir(tmp_path) == []  # no se escribio ninguna orden


# --------------------------- Bitacora de auditoria ---------------------------

def test_orden_se_registra_en_bitacora(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path))
    monkeypatch.setattr(nt, "NT_LOG", str(tmp_path / "trades.log"))
    nt.colocar_orden({"instrument": "MNQ", "action": "BUY", "qty": 1})
    lineas = nt.leer_auditoria()
    assert len(lineas) == 1
    assert "ORDEN" in lineas[0] and "MNQ" in lineas[0] and "enviada" in lineas[0]


def test_auditar_nunca_lanza(monkeypatch):
    # Aunque la ruta sea invalida, auditar() no debe lanzar.
    monkeypatch.setattr(nt, "NT_LOG", "/ruta/que/no/existe/y/no/se/puede/crear.log")
    nt.auditar("ORDEN", "x")  # no debe lanzar


def test_historial_vacio_y_lleno(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NT_LOG", str(tmp_path / "trades.log"))
    assert "Aun no hay" in nt.historial({})
    nt.auditar("CANCELAR", "todas", "enviada")
    out = nt.historial({"n": 5})
    assert "CANCELAR" in out


def test_historial_registrado_en_nexus():
    assert "nt_historial" in nexus.EJECUTORES
    assert "nt_historial" in nt.NT_SEGURAS
    assert "nt_historial" not in nexus.HERRAMIENTAS_PELIGROSAS


# --------------------------- Robustez del despacho de herramientas ---------------------------

def test_ejecutar_herramienta_captura_excepciones(monkeypatch):
    def explota(_):
        raise RuntimeError("boom")
    monkeypatch.setitem(nexus.EJECUTORES, "nt_estado", explota)
    out = nexus.ejecutar_herramienta("nt_estado", {})
    assert "Error ejecutando" in out and "boom" in out  # no se propaga la excepcion


# --------------------------- OCO: stop-loss / take-profit ---------------------------

def test_accion_opuesta():
    assert nt.accion_opuesta("BUY") == "SELL"
    assert nt.accion_opuesta("SELL") == "BUY"
    assert nt.accion_opuesta("SELLSHORT") == "BUYTOCOVER"


def test_orden_con_oco_envia_tres_ordenes(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path))
    monkeypatch.setattr(nt, "NT_LOG", str(tmp_path / "t.log"))
    out = nt.colocar_orden({"instrument": "ES 12-25", "action": "BUY", "qty": 1,
                            "stop_loss": "4990", "take_profit": "5030"})
    assert "OCO" in out
    archivos = [p for p in os.listdir(tmp_path) if p.startswith("oif_nexus_")]
    assert len(archivos) == 3  # entrada + stop + objetivo
    # Las protecciones usan la accion opuesta (SELL) y comparten un OCO id
    contenidos = []
    for p in sorted(archivos):
        with open(os.path.join(tmp_path, p), encoding="utf-8") as f:
            contenidos.append(f.read())
    todo = "".join(contenidos)
    assert "nexus_oco_" in todo
    assert todo.count("SELL") >= 2  # stop y objetivo cierran un BUY


def test_resumen_orden_incluye_oco():
    r = nt.resumen_orden({"instrument": "ES", "action": "BUY", "qty": 1,
                          "stop_loss": "4990", "take_profit": "5030"})
    assert "stop-loss 4990" in r and "take-profit 5030" in r


# --------------------------- Modo simulacion ---------------------------

def test_modo_simulacion_precio_y_estado(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NT_SIMULAR", True)
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path / "sim"))
    # carpeta_ok crea la carpeta y devuelve True aunque no exista al inicio
    assert nt.carpeta_ok() is True
    # precio simulado: numero parseable, cercano a la base de ES
    val = float(nt.leer_precio("ES 12-25", "LAST", espera=0))
    assert 4900 < val < 5100
    assert "SIMULACION" in nt.estado()


def test_simulacion_orden_se_guarda_local(tmp_path, monkeypatch):
    sim = tmp_path / "sim"
    monkeypatch.setattr(nt, "NT_SIMULAR", True)
    monkeypatch.setattr(nt, "NT_FOLDER", str(sim))
    monkeypatch.setattr(nt, "NT_LOG", str(tmp_path / "t.log"))
    out = nt.colocar_orden({"instrument": "MNQ", "action": "BUY", "qty": 1})
    assert "enviada" in out.lower()
    assert any(p.startswith("oif_nexus_") for p in os.listdir(sim))  # quedó local


def test_diagnostico_no_revienta(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NT_SIMULAR", True)
    monkeypatch.setattr(nt, "NT_FOLDER", str(tmp_path / "sim"))
    monkeypatch.setattr(nt, "NT_LOG", str(tmp_path / "t.log"))
    rep = nt.diagnostico()
    assert "Diagnostico" in rep and "Modo simulacion" in rep
