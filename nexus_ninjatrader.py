#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puente entre NEXUS y NinjaTrader 8  (trading desde tu asistente).

Usa la *AT Interface basada en archivos* de NinjaTrader 8 (la forma oficial y
SIN dependencias externas): Nexus deja "Order Instruction Files" (OIF) en la
carpeta `incoming` de NinjaTrader, y lee los archivos de precios que NinjaTrader
escribe ahi. NinjaTrader procesa cada archivo y lo borra.

Para que funcione, en NinjaTrader 8:
    Tools -> Options -> Automated trading interface -> marca "AT Interface".
La carpeta por defecto es:
    <Documentos>\\NinjaTrader 8\\incoming\\

Todo es configurable por variables de entorno (sin tocar el codigo):

    NEXUS_NT_FOLDER   Carpeta 'incoming' de NinjaTrader (autodetectada si no se indica).
    NEXUS_NT_ACCOUNT  Cuenta por defecto. Por SEGURIDAD el defecto es 'Sim101'
                      (simulacion). Para operar en real, exporta el nombre EXACTO
                      de tu cuenta real de NinjaTrader.
    NEXUS_NT_ESPERA   Segundos a esperar por el archivo de precio (defecto 2.5).

SEGURIDAD: este modulo SOLO construye y deja archivos de orden; NO confirma nada.
La confirmacion la maneja quien lo llama (la terminal con _confirmar; la web con
el modal de aprobacion), igual que run_command / write_file. Las ordenes mueven
DINERO REAL: revisa siempre el resumen antes de aprobar.
"""

import os
import glob
import time
import datetime

# --- Configuracion (por entorno; defaults seguros) ------------------------

def _env(nombre: str, defecto: str) -> str:
    valor = os.environ.get(nombre)
    return valor if valor not in (None, "") else defecto


def _carpeta_incoming_por_defecto() -> str:
    """Ubicacion tipica de la carpeta 'incoming' de NinjaTrader 8."""
    documentos = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(documentos, "NinjaTrader 8", "incoming")


NT_FOLDER = _env("NEXUS_NT_FOLDER", _carpeta_incoming_por_defecto())
NT_ACCOUNT = _env("NEXUS_NT_ACCOUNT", "Sim101")   # 'Sim101' = simulacion (seguro por defecto)
NT_ESPERA = float(_env("NEXUS_NT_ESPERA", "2.5"))  # espera maxima por el archivo de precio

# Bitacora de auditoria: TODA orden/cancelacion/cierre que Nexus envia queda
# registrada aqui con fecha y hora. Es clave operando con dinero real.
_CARPETA = os.path.dirname(os.path.abspath(__file__))
NT_LOG = _env("NEXUS_NT_LOG", os.path.join(_CARPETA, "nexus_trades.log"))

# Valores validos del protocolo OIF de NinjaTrader.
ACCIONES = {"BUY", "SELL", "BUYTOCOVER", "SELLSHORT"}
TIPOS_ORDEN = {"MARKET", "LIMIT", "STOPMARKET", "STOPLIMIT"}
TIF_VALIDOS = {"DAY", "GTC"}
TIPOS_PRECIO = {"LAST", "BID", "ASK"}


# ============================================================
#  CONSTRUCCION DE COMANDOS OIF  (funciones puras, faciles de testear)
# ============================================================

def _campo(v) -> str:
    """Normaliza un campo del OIF a texto (None/'' -> vacio)."""
    return "" if v is None else str(v).strip()


def construir_place(account: str, instrument: str, action: str, qty,
                    order_type: str = "MARKET", limit_price="", stop_price="",
                    tif: str = "DAY", oco_id: str = "", order_id: str = "",
                    strategy: str = "", strategy_id: str = "") -> str:
    """Construye la linea OIF para COLOCAR una orden. Valida los campos clave.

    Formato NinjaTrader:
      PLACE;ACCOUNT;INSTRUMENT;ACTION;QTY;ORDER TYPE;LIMIT PRICE;STOP PRICE;TIF;
            OCO ID;ORDER ID;STRATEGY;STRATEGY ID
    """
    account = _campo(account) or NT_ACCOUNT
    instrument = _campo(instrument).upper()
    action = _campo(action).upper()
    order_type = (_campo(order_type) or "MARKET").upper()
    tif = (_campo(tif) or "DAY").upper()

    if not instrument:
        raise ValueError("Falta el instrumento (ej. 'ES 12-25', 'AAPL', 'MNQ').")
    if action not in ACCIONES:
        raise ValueError(f"Accion invalida: '{action}'. Usa una de {sorted(ACCIONES)}.")
    if order_type not in TIPOS_ORDEN:
        raise ValueError(f"Tipo de orden invalido: '{order_type}'. Usa {sorted(TIPOS_ORDEN)}.")
    if tif not in TIF_VALIDOS:
        raise ValueError(f"TIF invalido: '{tif}'. Usa {sorted(TIF_VALIDOS)}.")
    try:
        if int(float(qty)) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"Cantidad invalida: '{qty}'. Debe ser un entero positivo.")
    if order_type in ("LIMIT", "STOPLIMIT") and not _campo(limit_price):
        raise ValueError(f"El tipo {order_type} requiere un precio limite (limit_price).")
    if order_type in ("STOPMARKET", "STOPLIMIT") and not _campo(stop_price):
        raise ValueError(f"El tipo {order_type} requiere un precio stop (stop_price).")

    campos = ["PLACE", account, instrument, action, str(int(float(qty))), order_type,
              _campo(limit_price), _campo(stop_price), tif, _campo(oco_id),
              _campo(order_id), _campo(strategy), _campo(strategy_id)]
    return ";".join(campos)


def construir_cancel(order_id: str) -> str:
    """CANCEL;ORDER ID;;;;;;;;;;;  -- cancela una orden por su id."""
    order_id = _campo(order_id)
    if not order_id:
        raise ValueError("Falta el order_id a cancelar.")
    return ";".join(["CANCEL", order_id] + [""] * 11)


def construir_cancel_all() -> str:
    """CANCELALLORDERS -- cancela TODAS las ordenes en curso."""
    return "CANCELALLORDERS"


def construir_close(account: str, instrument: str) -> str:
    """CLOSEPOSITION;ACCOUNT;INSTRUMENT;... -- cierra la posicion de un instrumento."""
    account = _campo(account) or NT_ACCOUNT
    instrument = _campo(instrument).upper()
    if not instrument:
        raise ValueError("Falta el instrumento para cerrar la posicion.")
    return ";".join(["CLOSEPOSITION", account, instrument] + [""] * 10)


def construir_flatten() -> str:
    """FLATTENEVERYTHING -- cierra TODAS las posiciones y cancela TODAS las ordenes."""
    return "FLATTENEVERYTHING"


# ============================================================
#  ENVIO Y LECTURA  (tocan el disco; corre en TU PC, junto a NinjaTrader)
# ============================================================

def carpeta_ok(carpeta: str = None) -> bool:
    return os.path.isdir(carpeta or NT_FOLDER)


def auditar(accion: str, detalle: str, resultado: str = "enviado") -> None:
    """Anade una linea a la bitacora de operaciones. NUNCA lanza: el registro no
    debe poder interrumpir una operacion. Formato TSV: fecha, accion, detalle, resultado."""
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        detalle = (detalle or "").replace("\t", " ").replace("\n", " ")
        with open(NT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{accion}\t{detalle}\t{resultado}\n")
    except OSError:
        pass


def leer_auditoria(n: int = 15) -> list:
    """Devuelve las ultimas n lineas de la bitacora (mas recientes al final)."""
    try:
        with open(NT_LOG, "r", encoding="utf-8", errors="replace") as f:
            lineas = [ln.rstrip("\n") for ln in f if ln.strip()]
        return lineas[-n:]
    except FileNotFoundError:
        return []


def enviar_comando(linea: str, carpeta: str = None) -> str:
    """Deja un archivo OIF en la carpeta 'incoming' de NinjaTrader con un nombre
    unico (NinjaTrader lo procesa y lo borra). Devuelve la ruta escrita.

    NO pide confirmacion: eso lo hace quien llama (terminal/web)."""
    carpeta = carpeta or NT_FOLDER
    if not os.path.isdir(carpeta):
        raise FileNotFoundError(
            f"No encuentro la carpeta de NinjaTrader: {carpeta}\n"
            "Comprueba que NinjaTrader 8 este abierto y que el 'AT Interface' este "
            "activado (Tools -> Options -> Automated trading interface), o define "
            "NEXUS_NT_FOLDER con la ruta correcta de tu carpeta 'incoming'."
        )
    nombre = f"oif_nexus_{int(time.time() * 1000)}.txt"
    ruta = os.path.join(carpeta, nombre)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(linea + "\n")
    return ruta


def _candidatos_precio(instrument: str, tipo: str, carpeta: str):
    """NinjaTrader escribe el precio en un archivo cuyo nombre exacto varia segun
    version/configuracion. Probamos los patrones conocidos para ser tolerantes."""
    inst = instrument.upper()
    tipo = tipo.upper()
    nombres = [f"{inst}_{tipo}.txt", f"{inst} {tipo}.txt",
               f"{inst}_{tipo.lower()}.txt", f"{inst.lower()}_{tipo.lower()}.txt"]
    return [os.path.join(carpeta, n) for n in nombres]


def leer_precio(instrument: str, tipo: str = "LAST", carpeta: str = None,
                espera: float = None) -> str:
    """Pide a NinjaTrader datos de mercado de un instrumento (SUBSCRIBE) y lee el
    precio del archivo que NinjaTrader escribe. Devuelve el precio como texto, o
    lanza una excepcion explicando que falto."""
    carpeta = carpeta or NT_FOLDER
    tipo = (tipo or "LAST").upper()
    instrument = (instrument or "").upper()
    espera = NT_ESPERA if espera is None else espera
    if not instrument:
        raise ValueError("Falta el instrumento.")
    if tipo not in TIPOS_PRECIO:
        raise ValueError(f"Tipo de precio invalido: '{tipo}'. Usa {sorted(TIPOS_PRECIO)}.")

    # Pedimos la suscripcion a datos de mercado (NinjaTrader empieza a escribir el archivo).
    enviar_comando(f"SUBSCRIBE;{instrument}", carpeta)

    # Sondear hasta `espera` segundos por alguno de los nombres de archivo posibles.
    limite = time.time() + max(0.0, espera)
    candidatos = _candidatos_precio(instrument, tipo, carpeta)
    while True:
        for ruta in candidatos:
            try:
                with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                    valor = f.read().strip()
                if valor:
                    return valor
            except FileNotFoundError:
                continue
        if time.time() >= limite:
            break
        time.sleep(0.15)
    raise FileNotFoundError(
        f"No recibi el precio {tipo} de {instrument}. Comprueba que NinjaTrader este "
        "conectado a un proveedor de datos y que el instrumento sea valido."
    )


def leer_posicion(instrument: str, account: str = None, carpeta: str = None) -> str:
    """Lectura *best-effort* de la posicion: busca en la carpeta 'incoming' un
    archivo que mencione el instrumento y 'position'. El nombre exacto depende de
    la version de NinjaTrader, por eso buscamos por patron. Devuelve el contenido
    o un aviso si no se encuentra."""
    carpeta = carpeta or NT_FOLDER
    account = account or NT_ACCOUNT
    inst = (instrument or "").upper()
    if not os.path.isdir(carpeta):
        raise FileNotFoundError(f"No encuentro la carpeta de NinjaTrader: {carpeta}")

    patrones = [os.path.join(carpeta, f"*{inst}*position*.txt"),
                os.path.join(carpeta, f"*{inst}*Position*.txt"),
                os.path.join(carpeta, f"*{account}*{inst}*.txt")]
    for patron in patrones:
        for ruta in sorted(glob.glob(patron)):
            try:
                with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                    cont = f.read().strip()
                if cont:
                    return f"{os.path.basename(ruta)}: {cont}"
            except OSError:
                continue
    return (f"No encontre un archivo de posicion para {inst} en {carpeta}. "
            "NinjaTrader escribe la posicion solo cuando el AT Interface lo expone; "
            "puede variar por version.")


# ============================================================
#  FUNCIONES DE ALTO NIVEL  (las que llaman las herramientas)
# ============================================================

def resumen_orden(args: dict) -> str:
    """Texto legible de una orden, para mostrar en la confirmacion."""
    cuenta = _campo(args.get("account")) or NT_ACCOUNT
    inst = _campo(args.get("instrument")).upper()
    accion = _campo(args.get("action")).upper()
    qty = _campo(args.get("qty"))
    tipo = (_campo(args.get("order_type")) or "MARKET").upper()
    extra = []
    if _campo(args.get("limit_price")):
        extra.append(f"limite {args.get('limit_price')}")
    if _campo(args.get("stop_price")):
        extra.append(f"stop {args.get('stop_price')}")
    cola = f" ({', '.join(extra)})" if extra else ""
    return f"{accion} {qty} {inst} {tipo}{cola}  [cuenta {cuenta}]"


def estado() -> str:
    carpeta = NT_FOLDER
    if carpeta_ok(carpeta):
        return (f"NinjaTrader: carpeta detectada en {carpeta}.\n"
                f"Cuenta por defecto: {NT_ACCOUNT}. Listo para operar.")
    return (f"NinjaTrader: NO encuentro la carpeta {carpeta}.\n"
            "Abre NinjaTrader 8, activa el AT Interface (Tools -> Options -> Automated "
            "trading interface) o define NEXUS_NT_FOLDER con la ruta de tu 'incoming'.")


def precio(args: dict) -> str:
    inst = _campo(args.get("instrument"))
    tipo = (_campo(args.get("tipo")) or "LAST").upper()
    try:
        valor = leer_precio(inst, tipo)
        return f"{inst.upper()} {tipo}: {valor}"
    except Exception as e:
        return f"No pude leer el precio: {e}"


def posicion(args: dict) -> str:
    try:
        return leer_posicion(_campo(args.get("instrument")), _campo(args.get("account")) or None)
    except Exception as e:
        return f"No pude leer la posicion: {e}"


def historial(args: dict = None) -> str:
    """Muestra las ultimas operaciones registradas en la bitacora de auditoria."""
    args = args or {}
    try:
        n = int(args.get("n", 15))
    except (TypeError, ValueError):
        n = 15
    n = max(1, min(n, 100))
    lineas = leer_auditoria(n)
    if not lineas:
        return "Aun no hay operaciones registradas en la bitacora."
    return "Ultimas operaciones (fecha | accion | detalle | resultado):\n" + "\n".join(lineas)


def colocar_orden(args: dict) -> str:
    """Construye y envia una orden PLACE. NO confirma (lo hace quien llama)."""
    try:
        linea = construir_place(
            account=args.get("account"), instrument=args.get("instrument"),
            action=args.get("action"), qty=args.get("qty"),
            order_type=args.get("order_type", "MARKET"),
            limit_price=args.get("limit_price", ""), stop_price=args.get("stop_price", ""),
            tif=args.get("tif", "DAY"), oco_id=args.get("oco_id", ""),
            order_id=args.get("order_id", ""),
        )
    except ValueError as e:
        return f"Orden rechazada: {e}"
    try:
        enviar_comando(linea)
    except Exception as e:
        auditar("ORDEN", resumen_orden(args), f"ERROR: {e}")
        return f"No pude enviar la orden a NinjaTrader: {e}"
    auditar("ORDEN", resumen_orden(args), "enviada")
    return f"Orden enviada a NinjaTrader: {resumen_orden(args)}"


def cancelar(args: dict) -> str:
    """Cancela una orden por id, o TODAS si se pide 'todas'."""
    try:
        if str(args.get("todas", "")).lower() in ("1", "true", "si", "yes") or args.get("order_id") in (None, "", "todas"):
            enviar_comando(construir_cancel_all())
            auditar("CANCELAR", "todas", "enviada")
            return "Solicitud enviada: cancelar TODAS las ordenes."
        enviar_comando(construir_cancel(args.get("order_id")))
        auditar("CANCELAR", str(args.get("order_id")), "enviada")
        return f"Solicitud enviada: cancelar la orden {args.get('order_id')}."
    except Exception as e:
        auditar("CANCELAR", str(args.get("order_id") or "todas"), f"ERROR: {e}")
        return f"No pude cancelar: {e}"


def cerrar(args: dict) -> str:
    """Cierra una posicion concreta, o aplana TODO si se pide 'todo'."""
    try:
        if str(args.get("todo", "")).lower() in ("1", "true", "si", "yes") or not _campo(args.get("instrument")):
            enviar_comando(construir_flatten())
            auditar("CERRAR", "aplanar todo", "enviada")
            return "Solicitud enviada: APLANAR todo (cerrar posiciones y cancelar ordenes)."
        inst = _campo(args.get("instrument")).upper()
        enviar_comando(construir_close(args.get("account"), args.get("instrument")))
        auditar("CERRAR", inst, "enviada")
        return f"Solicitud enviada: cerrar la posicion de {inst}."
    except Exception as e:
        auditar("CERRAR", _campo(args.get("instrument")).upper() or "todo", f"ERROR: {e}")
        return f"No pude cerrar la posicion: {e}"


# ============================================================
#  DEFINICION DE HERRAMIENTAS  (lo que Claude "ve")
# ============================================================
# Las de SOLO lectura no mueven dinero. Las de orden SI: van en el set peligroso
# (confirmacion en terminal; modal en web; desactivadas por defecto en la web).

NT_TOOLS = [
    {
        "name": "nt_estado",
        "description": ("Comprueba la conexion con NinjaTrader 8 (si la carpeta del AT "
                        "Interface esta accesible) y muestra la cuenta por defecto."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "nt_precio",
        "description": ("Consulta el precio de un instrumento en NinjaTrader (ultimo, bid o "
                        "ask). Ej. instrumento 'ES 12-25', 'MNQ', 'AAPL'."),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "Instrumento de NinjaTrader."},
                "tipo": {"type": "string", "description": "LAST (defecto), BID o ASK."},
            },
            "required": ["instrument"],
        },
    },
    {
        "name": "nt_posicion",
        "description": "Lee la posicion abierta de un instrumento en NinjaTrader (best-effort).",
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "Instrumento a consultar."},
                "account": {"type": "string", "description": "Cuenta (opcional; usa la de por defecto)."},
            },
            "required": ["instrument"],
        },
    },
    {
        "name": "nt_historial",
        "description": ("Muestra las ultimas operaciones que Nexus ha enviado a NinjaTrader "
                        "(bitacora de auditoria). Opcional 'n' = cuantas mostrar."),
        "input_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "Cuantas operaciones mostrar (defecto 15)."}},
            "required": [],
        },
    },
    {
        "name": "nt_orden",
        "description": ("ENVIA una orden REAL a NinjaTrader (mueve dinero). Requiere "
                        "confirmacion del usuario. action: BUY/SELL/BUYTOCOVER/SELLSHORT; "
                        "order_type: MARKET/LIMIT/STOPMARKET/STOPLIMIT."),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "Instrumento, ej. 'ES 12-25' o 'AAPL'."},
                "action": {"type": "string", "description": "BUY, SELL, BUYTOCOVER o SELLSHORT."},
                "qty": {"type": "integer", "description": "Cantidad (entero positivo)."},
                "order_type": {"type": "string", "description": "MARKET (defecto), LIMIT, STOPMARKET o STOPLIMIT."},
                "limit_price": {"type": "string", "description": "Precio limite (para LIMIT/STOPLIMIT)."},
                "stop_price": {"type": "string", "description": "Precio stop (para STOPMARKET/STOPLIMIT)."},
                "tif": {"type": "string", "description": "DAY (defecto) o GTC."},
                "account": {"type": "string", "description": "Cuenta (opcional; usa la de por defecto)."},
            },
            "required": ["instrument", "action", "qty"],
        },
    },
    {
        "name": "nt_cancelar",
        "description": "Cancela una orden de NinjaTrader por su order_id, o TODAS si todas=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Id de la orden a cancelar."},
                "todas": {"type": "boolean", "description": "true para cancelar TODAS las ordenes."},
            },
            "required": [],
        },
    },
    {
        "name": "nt_cerrar",
        "description": ("Cierra la posicion de un instrumento en NinjaTrader, o APLANA todo "
                        "(cierra posiciones y cancela ordenes) si todo=true."),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "Instrumento a cerrar."},
                "account": {"type": "string", "description": "Cuenta (opcional)."},
                "todo": {"type": "boolean", "description": "true para aplanar TODO."},
            },
            "required": [],
        },
    },
]

# Herramientas de orden (mueven dinero): necesitan confirmacion / off por defecto en web.
NT_PELIGROSAS = {"nt_orden", "nt_cancelar", "nt_cerrar"}
# Herramientas de solo lectura (seguras).
NT_SEGURAS = {"nt_estado", "nt_precio", "nt_posicion", "nt_historial"}

# Mapa nombre -> funcion de trabajo (sin confirmacion).
NT_EJECUTORES = {
    "nt_estado": lambda a: estado(),
    "nt_precio": precio,
    "nt_posicion": posicion,
    "nt_historial": historial,
    "nt_orden": colocar_orden,
    "nt_cancelar": cancelar,
    "nt_cerrar": cerrar,
}
