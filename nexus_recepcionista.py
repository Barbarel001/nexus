#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RECEPCIONISTA IA para NEGOCIOS PEQUEÑOS — modulo de NEXUS.

Atiende a los clientes de un negocio (limpieza, fontaneria, peluqueria, taller...)
por chat: responde preguntas frecuentes, da presupuestos usando SOLO precios que
el dueño ha aprobado, recoge los datos del cliente (nombre, contacto, servicio) y
avisa al dueño con un lead cualificado.

Principio de diseño clave:
    La IA NUNCA inventa un precio. Los presupuestos salen de `estimar_precio`, que
    lee la tarifa aprobada por el dueño. Si no hay tarifa, dice que el dueño lo
    confirmara. Asi el dueño controla lo que se promete a sus clientes.

Reutiliza la infraestructura de NEXUS:
    - Backend de IA (Anthropic o, gratis, Ollama) via nexus.conversar.
    - Persistencia por usuario (nexus_ctx + nexus_util), como el resto de modulos.
    - Avisos al dueño por Telegram (nexus_telegram) o Web Push (nexus_push).

Los datos se guardan en  recepcionista.json  (por usuario en modo multiusuario).

Herramientas expuestas:
    - Al DUEÑO (a traves del asistente Nexus): configurar el negocio, añadir
      servicios/tarifas y FAQ, y revisar los leads capturados. Todas SEGURAS.
    - Al CLIENTE (chat de recepcion): estimar_precio, buscar_faq y capturar_lead.
      Es un set de herramientas AISLADO: el cliente jamas ve las herramientas del
      dueño (trading, sistema, etc.).

Configurable por entorno:
    NEXUS_RECEPCION_PATH   Ruta del archivo de datos (defecto: recepcionista.json).
"""

import datetime
import os
import re
import uuid

import nexus_ctx
import nexus_util

CARPETA = os.path.dirname(os.path.abspath(__file__))
RECEPCION_PATH = os.environ.get("NEXUS_RECEPCION_PATH") or os.path.join(CARPETA, "recepcionista.json")

ESTADOS_LEAD = ("nuevo", "contactado", "ganado", "perdido")
_MARGEN_DEFECTO = 0.0  # 0 = precio exacto; el dueño puede pedir un rango (p.ej. 0.15)

# Tope de leads por CONVERSACION (anti-spam): un chat publico es una puerta
# abierta; sin limite, alguien podria inundar recepcionista.json y los avisos del
# dueño. Configurable por entorno; 0 o negativo = sin tope.
try:
    MAX_LEADS_POR_CONV = int(os.environ.get("NEXUS_RECEPCION_MAX_LEADS") or 3)
except ValueError:
    MAX_LEADS_POR_CONV = 3


# --------------------------- Persistencia ---------------------------

def _vacio() -> dict:
    return {"negocio": {}, "leads": []}


def cargar() -> dict:
    datos = nexus_util.cargar_json(nexus_ctx.user_path(RECEPCION_PATH), None)
    if not isinstance(datos, dict):
        return _vacio()
    datos.setdefault("negocio", {})
    datos.setdefault("leads", [])
    return datos


def guardar(datos: dict) -> None:
    nexus_util.guardar_json(nexus_ctx.user_path(RECEPCION_PATH), datos)


def _hoy() -> str:
    return datetime.date.today().isoformat()


def _ahora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------- Utilidades de texto ---------------------------

def _normalizar(texto: str) -> str:
    """Minusculas, sin acentos y sin signos, para comparar de forma tolerante."""
    t = (texto or "").strip().lower()
    reemplazos = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                  ("ü", "u"), ("ñ", "n"))
    for a, b in reemplazos:
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9\s]", " ", t)


def _palabras(texto: str) -> set:
    return {p for p in _normalizar(texto).split() if len(p) > 2}


def _puntuar(consulta: str, texto: str) -> int:
    """Cuantas palabras significativas de `consulta` aparecen en `texto`."""
    return len(_palabras(consulta) & _palabras(texto))


# --------------------------- Configuracion del negocio ---------------------------

def configurar_negocio(**campos) -> dict:
    """Fija/actualiza los datos generales del negocio (solo los campos indicados).

    Campos habituales: nombre, sector, zona, horario, moneda, idioma,
    telefono_aviso (chat_id de Telegram del dueño), politica (texto libre).
    """
    datos = cargar()
    negocio = datos["negocio"]
    for k, v in campos.items():
        if v is not None:
            negocio[k] = v
    negocio.setdefault("servicios", [])
    negocio.setdefault("faq", [])
    negocio.setdefault("moneda", "€")
    negocio.setdefault("idioma", "es")
    guardar(datos)
    return negocio


def agregar_servicio(nombre: str, base: float, por_unidad: float = 0.0,
                     unidad: str = "", unidades_incluidas: int = 1,
                     minimo: float = None, maximo: float = None,
                     margen: float = None, notas: str = "") -> dict:
    """Registra (o actualiza) una tarifa APROBADA para un servicio.

    precio = base + max(0, cantidad - unidades_incluidas) * por_unidad, acotado a
    [minimo, maximo] si se indican. `margen` (0..1) convierte el precio en un rango
    +/- ese porcentaje (util para presupuestos orientativos).
    """
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El servicio necesita un nombre.")
    if base is None or float(base) < 0:
        raise ValueError("El precio base debe ser un numero >= 0.")
    servicio = {
        "nombre": nombre,
        "base": round(float(base), 2),
        "por_unidad": round(float(por_unidad or 0.0), 2),
        "unidad": (unidad or "").strip(),
        "unidades_incluidas": int(unidades_incluidas or 1),
        "minimo": None if minimo is None else round(float(minimo), 2),
        "maximo": None if maximo is None else round(float(maximo), 2),
        "margen": _MARGEN_DEFECTO if margen is None else max(0.0, float(margen)),
        "notas": (notas or "").strip(),
    }
    datos = cargar()
    servicios = datos["negocio"].setdefault("servicios", [])
    for i, s in enumerate(servicios):
        if _normalizar(s.get("nombre", "")) == _normalizar(nombre):
            servicios[i] = servicio
            break
    else:
        servicios.append(servicio)
    guardar(datos)
    return servicio


def buscar_servicio(nombre: str):
    """Devuelve el servicio que mejor casa con `nombre`, o None."""
    servicios = cargar()["negocio"].get("servicios", [])
    if not servicios:
        return None
    exacto = [s for s in servicios if _normalizar(s["nombre"]) == _normalizar(nombre)]
    if exacto:
        return exacto[0]
    puntuados = sorted(servicios, key=lambda s: _puntuar(nombre, s["nombre"]), reverse=True)
    mejor = puntuados[0]
    return mejor if _puntuar(nombre, mejor["nombre"]) > 0 else None


def agregar_faq(pregunta: str, respuesta: str) -> dict:
    """Añade una pregunta frecuente con su respuesta APROBADA por el dueño."""
    pregunta = (pregunta or "").strip()
    respuesta = (respuesta or "").strip()
    if not pregunta or not respuesta:
        raise ValueError("La FAQ necesita pregunta y respuesta.")
    datos = cargar()
    faq = datos["negocio"].setdefault("faq", [])
    for item in faq:
        if _normalizar(item.get("pregunta", "")) == _normalizar(pregunta):
            item["respuesta"] = respuesta
            break
    else:
        faq.append({"pregunta": pregunta, "respuesta": respuesta})
    guardar(datos)
    return {"pregunta": pregunta, "respuesta": respuesta}


def buscar_faq(pregunta: str):
    """Devuelve la respuesta a la FAQ que mejor casa, o None si nada casa."""
    faq = cargar()["negocio"].get("faq", [])
    if not faq:
        return None
    puntuadas = sorted(faq, key=lambda f: _puntuar(pregunta, f["pregunta"] + " " + f["respuesta"]),
                       reverse=True)
    mejor = puntuadas[0]
    return mejor if _puntuar(pregunta, mejor["pregunta"] + " " + mejor["respuesta"]) > 0 else None


# --------------------------- Presupuestos (precio aprobado) ---------------------------

def estimar_precio(servicio_nombre: str, cantidad: float = None) -> dict:
    """Calcula el presupuesto de un servicio a partir de la tarifa APROBADA.

    Devuelve un dict con estado:
      {"ok": True,  "servicio", "desde", "hasta", "moneda", "notas"}
      {"ok": False, "motivo"}  -> no hay tarifa; el dueño debe confirmar.
    Nunca inventa un precio: si el servicio no esta tarifado, devuelve ok=False.
    """
    negocio = cargar()["negocio"]
    moneda = negocio.get("moneda", "€")
    servicio = buscar_servicio(servicio_nombre)
    if not servicio:
        return {"ok": False, "motivo": "servicio_no_tarifado", "consulta": servicio_nombre}

    incluidas = servicio.get("unidades_incluidas", 1)
    try:
        cant = float(cantidad) if cantidad is not None else float(incluidas)
    except (TypeError, ValueError):
        cant = float(incluidas)
    extra = max(0.0, cant - incluidas)
    precio = servicio["base"] + extra * servicio.get("por_unidad", 0.0)

    minimo, maximo = servicio.get("minimo"), servicio.get("maximo")
    if minimo is not None:
        precio = max(precio, minimo)
    if maximo is not None:
        precio = min(precio, maximo)

    margen = servicio.get("margen", 0.0) or 0.0
    desde = round(precio * (1 - margen), 2)
    hasta = round(precio * (1 + margen), 2)
    return {
        "ok": True, "servicio": servicio["nombre"], "cantidad": cant,
        "unidad": servicio.get("unidad", ""), "desde": desde, "hasta": hasta,
        "moneda": moneda, "notas": servicio.get("notas", ""),
    }


def formato_presupuesto(est: dict) -> str:
    """Texto legible de un presupuesto (para mostrar al cliente o al dueño)."""
    if not est.get("ok"):
        return ("No tengo una tarifa cerrada para eso; anoto tu solicitud y el "
                "responsable te confirma el precio.")
    m = est["moneda"]
    if est["desde"] == est["hasta"]:
        cuerpo = f"{est['desde']:g} {m}"
    else:
        cuerpo = f"entre {est['desde']:g} y {est['hasta']:g} {m}"
    extra = f" ({est['notas']})" if est.get("notas") else ""
    return f"Presupuesto orientativo para {est['servicio']}: {cuerpo}{extra}."


# --------------------------- Leads (clientes potenciales) ---------------------------

def _es_contacto(texto: str) -> bool:
    """True si `texto` parece un telefono o un email utilizable."""
    t = (texto or "").strip()
    if "@" in t and "." in t.split("@")[-1]:
        return True
    digitos = re.sub(r"\D", "", t)
    return len(digitos) >= 7


def calificar_lead(lead: dict) -> bool:
    """Un lead esta CUALIFICADO si tiene contacto valido y un servicio identificado."""
    return _es_contacto(lead.get("contacto", "")) and bool((lead.get("servicio") or "").strip())


def capturar_lead(nombre: str = "", contacto: str = "", servicio: str = "",
                  detalles: str = "", presupuesto: str = "", origen: str = "chat",
                  avisar: bool = True) -> dict:
    """Guarda un lead, lo califica y (opcional) avisa al dueño. Devuelve el lead."""
    lead = {
        "id": uuid.uuid4().hex[:6],
        "creado": _ahora(),
        "nombre": (nombre or "").strip(),
        "contacto": (contacto or "").strip(),
        "servicio": (servicio or "").strip(),
        "detalles": (detalles or "").strip(),
        "presupuesto": (presupuesto or "").strip(),
        "estado": "nuevo",
        "origen": (origen or "chat").strip(),
        "notas": "",
    }
    lead["calificado"] = calificar_lead(lead)
    datos = cargar()
    datos["leads"].append(lead)
    guardar(datos)
    if avisar and lead["calificado"]:
        avisar_dueno(lead)
    return lead


def listar_leads(filtro: str = "todos") -> list:
    """Filtra leads: 'todos', 'nuevos', 'cualificados', 'ganados', 'perdidos'."""
    leads = cargar()["leads"]
    f = (filtro or "todos").lower()
    if f in ("nuevos", "nuevo"):
        return [l for l in leads if l.get("estado") == "nuevo"]
    if f in ("cualificados", "calificados"):
        return [l for l in leads if l.get("calificado")]
    if f in ("ganados", "ganado"):
        return [l for l in leads if l.get("estado") == "ganado"]
    if f in ("perdidos", "perdido"):
        return [l for l in leads if l.get("estado") == "perdido"]
    return list(leads)


def marcar_lead(ref: str, estado: str) -> str:
    """Cambia el estado de un lead (por id o parte de su nombre/contacto)."""
    estado = (estado or "").strip().lower()
    if estado not in ESTADOS_LEAD:
        return f"Estado invalido. Usa uno de: {', '.join(ESTADOS_LEAD)}."
    leads = cargar()
    ref_n = _normalizar(ref)
    coincidencias = [l for l in leads["leads"]
                     if l["id"] == ref or ref_n and ref_n in _normalizar(
                         f"{l.get('nombre','')} {l.get('contacto','')}")]
    if not coincidencias:
        return f"No encontre ningun lead que coincida con '{ref}'."
    if len(coincidencias) > 1:
        ids = ", ".join(f"{l['id']} ({l.get('nombre') or l.get('contacto')})" for l in coincidencias[:5])
        return f"Hay varios leads que coinciden. Precisa el id: {ids}"
    coincidencias[0]["estado"] = estado
    guardar(leads)
    obj = coincidencias[0]
    return f"Lead {obj['id']} ({obj.get('nombre') or obj.get('contacto')}) -> {estado}."


def resumen_lead(lead: dict) -> str:
    """Texto compacto de un lead para el dueño."""
    marca = "★" if lead.get("calificado") else " "
    partes = [f"[{marca}] {lead['id']}", lead.get("nombre") or "(sin nombre)"]
    if lead.get("servicio"):
        partes.append(f"· {lead['servicio']}")
    if lead.get("contacto"):
        partes.append(f"· {lead['contacto']}")
    if lead.get("presupuesto"):
        partes.append(f"· {lead['presupuesto']}")
    partes.append(f"· {lead.get('estado', 'nuevo')}")
    linea = " ".join(partes)
    if lead.get("detalles"):
        linea += f"\n    {lead['detalles']}"
    return linea


def render_leads(leads: list, vacio: str = "No hay leads todavia.") -> str:
    return "\n".join(resumen_lead(l) for l in leads) if leads else vacio


def dto_lead(lead: dict) -> dict:
    """Representacion de un lead para la web."""
    return {
        "id": lead["id"], "creado": lead.get("creado", ""),
        "nombre": lead.get("nombre", ""), "contacto": lead.get("contacto", ""),
        "servicio": lead.get("servicio", ""), "detalles": lead.get("detalles", ""),
        "presupuesto": lead.get("presupuesto", ""), "estado": lead.get("estado", "nuevo"),
        "calificado": bool(lead.get("calificado")), "origen": lead.get("origen", "chat"),
    }


# --------------------------- Aviso al dueño ---------------------------

def avisar_dueno(lead: dict) -> bool:
    """Avisa al dueño de un nuevo lead por Telegram y/o Web Push. Best-effort:
    nunca lanza y devuelve True si consiguio enviarlo por algun canal."""
    negocio = cargar()["negocio"]
    nombre_negocio = negocio.get("nombre", "tu negocio")
    titulo = f"Nuevo lead — {nombre_negocio}"
    cuerpo = resumen_lead(lead)
    enviado = False
    try:
        import nexus_telegram
        if nexus_telegram.configurado():
            chat = negocio.get("telefono_aviso") or None
            enviado = nexus_telegram.enviar(f"{titulo}\n{cuerpo}", chat_id=chat) or enviado
    except Exception as e:
        nexus_util.log(f"recepcionista: aviso telegram fallo: {e}", "WARN")
    try:
        import nexus_push
        if nexus_push.configurado():
            enviado = bool(nexus_push.enviar(titulo, cuerpo, url="/")) or enviado
    except Exception as e:
        nexus_util.log(f"recepcionista: aviso push fallo: {e}", "WARN")
    return enviado


# --------------------------- Chat con el CLIENTE ---------------------------

def system_prompt_cliente(negocio: dict = None) -> str:
    """Construye las instrucciones del recepcionista para atender a un cliente.

    Es una funcion pura (no toca la red): facil de probar y de auditar lo que la
    IA tiene permitido decir.
    """
    negocio = negocio if negocio is not None else cargar()["negocio"]
    nombre = negocio.get("nombre", "el negocio")
    sector = negocio.get("sector", "")
    zona = negocio.get("zona", "")
    horario = negocio.get("horario", "")
    idioma = negocio.get("idioma", "es")
    politica = negocio.get("politica", "")
    servicios = negocio.get("servicios", [])
    lista_serv = ", ".join(s["nombre"] for s in servicios) or "(sin servicios cargados)"

    partes = [
        f"Eres el recepcionista virtual de {nombre}"
        + (f", un negocio de {sector}" if sector else "") + ".",
        "Tu trabajo: atender a clientes con amabilidad y brevedad, resolver dudas y "
        "recoger sus datos para que el responsable les de seguimiento.",
        f"Servicios que ofrece el negocio: {lista_serv}.",
        "REGLAS ESTRICTAS:",
        "1. Para CUALQUIER precio o presupuesto usa la herramienta estimar_precio. "
        "NUNCA inventes ni estimes precios de tu cabeza. Si no hay tarifa, di que el "
        "responsable confirmara el precio y sigue recogiendo datos.",
        "2. Para preguntas sobre horarios, politicas o dudas frecuentes usa buscar_faq. "
        "Si no hay respuesta, no te inventes datos: ofrece que el responsable lo aclare.",
        "3. Consigue de forma natural: nombre, un contacto (telefono o email), el "
        "servicio que necesita y los detalles (p. ej. tamaño, fecha). Cuando tengas "
        "al menos contacto y servicio, llama a capturar_lead.",
        "4. No prometas fechas ni descuentos que no esten en la informacion aprobada.",
        "5. Se breve: respuestas de 1-3 frases. Una pregunta a la vez.",
    ]
    if zona:
        partes.append(f"Zona de servicio: {zona}.")
    if horario:
        partes.append(f"Horario: {horario}.")
    if politica:
        partes.append(f"Politica del negocio: {politica}")
    partes.append(f"Responde SIEMPRE en el idioma del cliente (por defecto: {idioma}).")
    return "\n".join(partes)


def nuevo_estado() -> dict:
    """Estado que persiste a lo largo de UNA conversacion con un cliente. El
    llamador (web/telegram) lo reutiliza entre turnos del mismo chat; sirve para
    el tope de leads por conversacion (anti-spam)."""
    return {"leads_capturados": 0}


def _hacer_ejecutar_cliente(estado: dict, max_leads: int):
    """Devuelve un dispatcher de herramientas del cliente que respeta el tope de
    leads de ESTA conversacion. Al superarlo, no guarda ni avisa: responde amable.
    `max_leads` <= 0 significa sin tope."""
    def _ejecutar(name: str, args: dict) -> str:
        if name == "capturar_lead" and max_leads > 0:
            if estado.get("leads_capturados", 0) >= max_leads:
                return ("Ya he registrado tu solicitud; el responsable te contactara. "
                        "Si necesitas algo mas, te atendera directamente.")
            resultado = ejecutar_cliente(name, args)
            estado["leads_capturados"] = estado.get("leads_capturados", 0) + 1
            return resultado
        return ejecutar_cliente(name, args)
    return _ejecutar


def responder_cliente(mensaje: str, historial: list = None, model: str = None,
                      estado: dict = None, max_leads: int = None) -> dict:
    """Atiende un turno del CLIENTE usando el backend de IA de NEXUS.

    `historial` es una lista de mensajes {role, content} (formato Anthropic) que se
    ACTUALIZA in-place para poder continuar la conversacion. `estado` (ver
    nuevo_estado) persiste el tope de leads por conversacion; pasa el MISMO dict en
    cada turno del mismo chat. Devuelve {"texto", "historial", "estado"}. El cliente
    solo tiene acceso a las herramientas del recepcionista (aislamiento total
    respecto a las del dueño), acotadas por el tope anti-spam.
    """
    import nexus  # import diferido: evita coste si el modulo se usa solo para datos
    historial = historial if historial is not None else []
    estado = estado if estado is not None else nuevo_estado()
    tope = MAX_LEADS_POR_CONV if max_leads is None else max_leads
    historial.append({"role": "user", "content": mensaje})
    system = system_prompt_cliente()
    ejecutar = _hacer_ejecutar_cliente(estado, tope)
    texto, _usage = nexus.conversar(
        historial, system_prompt=system, tools=RECEPCION_CLIENTE_TOOLS,
        ejecutar=ejecutar, model=model, max_iter=6)
    return {"texto": texto, "historial": historial, "estado": estado}


# ============================================================
#  HERRAMIENTAS DEL CLIENTE  (chat de recepcion) -- set AISLADO
# ============================================================

def tool_estimar_precio(args: dict) -> str:
    return formato_presupuesto(estimar_precio(args.get("servicio", ""), args.get("cantidad")))


def tool_buscar_faq(args: dict) -> str:
    item = buscar_faq(args.get("pregunta", ""))
    if not item:
        return ("No tengo esa informacion a mano; puedo pedir que el responsable te "
                "lo confirme si me dejas tu contacto.")
    return item["respuesta"]


def tool_capturar_lead(args: dict) -> str:
    lead = capturar_lead(
        nombre=args.get("nombre", ""), contacto=args.get("contacto", ""),
        servicio=args.get("servicio", ""), detalles=args.get("detalles", ""),
        presupuesto=args.get("presupuesto", ""), origen=args.get("origen", "chat"))
    if lead["calificado"]:
        return ("¡Gracias! He tomado tus datos y el responsable te contactara pronto. "
                f"(referencia {lead['id']})")
    faltan = []
    if not _es_contacto(lead.get("contacto", "")):
        faltan.append("un telefono o email de contacto")
    if not lead.get("servicio"):
        faltan.append("que servicio necesitas")
    return "Casi lo tengo; ¿me confirmas " + " y ".join(faltan) + "?"


RECEPCION_CLIENTE_TOOLS = [
    {
        "name": "estimar_precio",
        "description": ("Da el presupuesto APROBADO de un servicio. Usala SIEMPRE para "
                        "cualquier precio; nunca inventes cifras. 'cantidad' es opcional "
                        "(p. ej. numero de habitaciones)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "servicio": {"type": "string", "description": "Servicio que pide el cliente."},
                "cantidad": {"type": "number", "description": "Cantidad/tamaño (opcional)."},
            },
            "required": ["servicio"],
        },
    },
    {
        "name": "buscar_faq",
        "description": "Busca la respuesta aprobada a una pregunta frecuente (horarios, politicas, dudas).",
        "input_schema": {
            "type": "object",
            "properties": {"pregunta": {"type": "string", "description": "Pregunta del cliente."}},
            "required": ["pregunta"],
        },
    },
    {
        "name": "capturar_lead",
        "description": ("Guarda los datos del cliente y avisa al responsable. Llamala cuando "
                        "tengas al menos contacto y servicio."),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre del cliente."},
                "contacto": {"type": "string", "description": "Telefono o email."},
                "servicio": {"type": "string", "description": "Servicio solicitado."},
                "detalles": {"type": "string", "description": "Detalles (tamaño, fecha, direccion...)."},
                "presupuesto": {"type": "string", "description": "Presupuesto ofrecido, si lo hubo."},
            },
            "required": ["contacto", "servicio"],
        },
    },
]

RECEPCION_CLIENTE_EJECUTORES = {
    "estimar_precio": tool_estimar_precio,
    "buscar_faq": tool_buscar_faq,
    "capturar_lead": tool_capturar_lead,
}


def ejecutar_cliente(name: str, args: dict) -> str:
    """Dispatcher de herramientas del cliente. Aislado: solo conoce las del recepcionista."""
    funcion = RECEPCION_CLIENTE_EJECUTORES.get(name)
    if funcion is None:
        return f"Herramienta no disponible en recepcion: {name}"
    try:
        return funcion(args)
    except Exception as e:
        nexus_util.log(f"recepcionista: error en {name}: {e}", "ERROR")
        return "Ha ocurrido un problema al procesar tu solicitud; lo intento de nuevo."


# ============================================================
#  HERRAMIENTAS DEL DUEÑO  (asistente Nexus) -- todas SEGURAS
# ============================================================

def tool_recepcion_configurar(args: dict) -> str:
    campos = {k: args.get(k) for k in
              ("nombre", "sector", "zona", "horario", "moneda", "idioma",
               "telefono_aviso", "politica") if args.get(k) is not None}
    if not campos:
        return "Indica al menos un dato del negocio (nombre, sector, zona, horario...)."
    negocio = configurar_negocio(**campos)
    return f"Negocio actualizado: {negocio.get('nombre', '(sin nombre)')}."


def tool_recepcion_servicio(args: dict) -> str:
    try:
        s = agregar_servicio(
            nombre=args.get("nombre", ""), base=args.get("base"),
            por_unidad=args.get("por_unidad", 0.0), unidad=args.get("unidad", ""),
            unidades_incluidas=args.get("unidades_incluidas", 1),
            minimo=args.get("minimo"), maximo=args.get("maximo"),
            margen=args.get("margen"), notas=args.get("notas", ""))
    except ValueError as e:
        return f"No pude guardar el servicio: {e}"
    est = estimar_precio(s["nombre"])
    return f"Tarifa guardada para '{s['nombre']}'. {formato_presupuesto(est)}"


def tool_recepcion_faq(args: dict) -> str:
    try:
        agregar_faq(args.get("pregunta", ""), args.get("respuesta", ""))
    except ValueError as e:
        return f"No pude guardar la FAQ: {e}"
    return "FAQ guardada."


def tool_recepcion_leads(args: dict) -> str:
    return render_leads(listar_leads(args.get("filtro", "todos")))


def tool_recepcion_marcar_lead(args: dict) -> str:
    return marcar_lead(args.get("ref", ""), args.get("estado", ""))


def tool_recepcion_probar(args: dict) -> str:
    """Prueba rapida: simula la pregunta de un cliente sin abrir el chat completo."""
    return responder_cliente(args.get("mensaje", "")).get("texto", "")


RECEPCION_TOOLS = [
    {
        "name": "recepcion_configurar",
        "description": ("Configura tu recepcionista IA: nombre del negocio, sector, zona, "
                        "horario, moneda, idioma, telefono_aviso (chat de Telegram del dueño) "
                        "y politica (texto libre)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string"}, "sector": {"type": "string"},
                "zona": {"type": "string"}, "horario": {"type": "string"},
                "moneda": {"type": "string"}, "idioma": {"type": "string"},
                "telefono_aviso": {"type": "string"}, "politica": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "recepcion_servicio",
        "description": ("Registra una tarifa APROBADA. precio = base + max(0, cantidad - "
                        "unidades_incluidas) * por_unidad, acotado a [minimo, maximo]. 'margen' "
                        "(0..1) lo convierte en rango orientativo."),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre del servicio."},
                "base": {"type": "number", "description": "Precio base."},
                "por_unidad": {"type": "number", "description": "Incremento por unidad extra."},
                "unidad": {"type": "string", "description": "Nombre de la unidad (habitacion, m2...)."},
                "unidades_incluidas": {"type": "integer", "description": "Unidades incluidas en el base."},
                "minimo": {"type": "number"}, "maximo": {"type": "number"},
                "margen": {"type": "number", "description": "Rango +/- (0..1). Opcional."},
                "notas": {"type": "string", "description": "Nota (que incluye, condiciones...)."},
            },
            "required": ["nombre", "base"],
        },
    },
    {
        "name": "recepcion_faq",
        "description": "Añade una pregunta frecuente con su respuesta aprobada.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pregunta": {"type": "string"}, "respuesta": {"type": "string"},
            },
            "required": ["pregunta", "respuesta"],
        },
    },
    {
        "name": "recepcion_leads",
        "description": "Muestra los leads capturados. filtro: todos/nuevos/cualificados/ganados/perdidos.",
        "input_schema": {
            "type": "object",
            "properties": {"filtro": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "recepcion_marcar_lead",
        "description": "Cambia el estado de un lead (nuevo/contactado/ganado/perdido). 'ref' = id o nombre.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"}, "estado": {"type": "string"},
            },
            "required": ["ref", "estado"],
        },
    },
    {
        "name": "recepcion_probar",
        "description": "Prueba tu recepcionista: escribe lo que preguntaria un cliente y ve la respuesta.",
        "input_schema": {
            "type": "object",
            "properties": {"mensaje": {"type": "string"}},
            "required": ["mensaje"],
        },
    },
]

# Todas operan sobre el archivo propio del negocio (o simulan un chat): SEGURAS.
RECEPCION_SEGURAS = {"recepcion_configurar", "recepcion_servicio", "recepcion_faq",
                     "recepcion_leads", "recepcion_marcar_lead", "recepcion_probar"}

RECEPCION_EJECUTORES = {
    "recepcion_configurar": tool_recepcion_configurar,
    "recepcion_servicio": tool_recepcion_servicio,
    "recepcion_faq": tool_recepcion_faq,
    "recepcion_leads": tool_recepcion_leads,
    "recepcion_marcar_lead": tool_recepcion_marcar_lead,
    "recepcion_probar": tool_recepcion_probar,
}


# --------------------------- Demo por terminal ---------------------------

def _demo() -> None:
    """Chat de recepcion por consola (usa el backend de IA configurado)."""
    negocio = cargar()["negocio"]
    if not negocio.get("servicios"):
        print("Aviso: no hay servicios cargados. Configura el negocio primero "
              "(recepcion_servicio) o los presupuestos diran 'lo confirmara el responsable'.")
    print(f"— Recepcion de {negocio.get('nombre', 'tu negocio')} — (Ctrl+C para salir)")
    historial, estado = [], nuevo_estado()
    try:
        while True:
            msg = input("Cliente: ").strip()
            if not msg:
                continue
            r = responder_cliente(msg, historial, estado=estado)
            print("Recepcion:", r["texto"])
    except (KeyboardInterrupt, EOFError):
        print("\nHasta luego.")


if __name__ == "__main__":
    _demo()
