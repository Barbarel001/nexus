# N.E.X.U.S. — asistente personal con IA

Un asistente hecho en Python sobre la API de Claude (Anthropic), con **dos
interfaces**: una **web futurista (HUD)** en el navegador y una clásica de
**terminal**. Conversa en español, **recuerda cosas entre sesiones**, **rastrea
ofertas de trabajo freelance**, busca en la web, ejecuta comandos en tu PC (con
tu permiso) y lee/escribe archivos.

Es **lo real** detrás de los anuncios de "IA que hace todo": un agente que usa un
modelo de lenguaje + herramientas. Útil como **copiloto**, no una máquina mágica
de hacer dinero solo.

---

## 1. Requisitos

- **Python 3.9+** (ya instalado: 3.12).
- Una **API key de Anthropic** (pago por uso).

## 2. Conseguir la API key

1. Entra a **https://console.anthropic.com**
2. Crea cuenta y añade saldo (con $5 experimentas mucho).
3. **API Keys → Create Key** y copia la clave (`sk-ant-...`).

## 3. Instalación

```powershell
pip install -r requirements.txt
```

## 4. Configurar la API key

```powershell
setx ANTHROPIC_API_KEY "sk-ant-aqui-tu-clave"
```

Cierra y reabre la terminal.

## 5. Ejecutar

**Interfaz web (HUD) — recomendada:**

```powershell
cd C:\Users\17863\nexus
python nexus_web.py
```

Se abre sola en el navegador (http://127.0.0.1:5000), con estética HUD y
respuestas en streaming. En la web, por seguridad, NO se ejecutan comandos del
sistema ni se escriben archivos (usa la terminal para eso).

**Interfaz de terminal (con todas las herramientas):**

```powershell
python nexus.py
```

Para salir de la terminal: `salir`.

### Doble clic

El acceso directo **Nexus** del Escritorio abre la **interfaz web**.
(`nexus_web.bat` = web · `nexus.bat` = terminal, ambos en esta carpeta.)

---

## Qué le puedes pedir

- "Rastrea ofertas freelance de Python y bots de Telegram."
- "Recuerda que mi tarifa es 20 USD/hora."
- "¿Cuánta RAM libre tengo ahora mismo?"
- "Busca en la web las novedades de Godot 4 y resúmemelas."
- "Crea un archivo propuesta.txt para este cliente: ..."

Cuando quiera **ejecutar un comando** o **escribir un archivo**, te pedirá permiso
(`s/N`). Nada se ejecuta sin tu OK.

---

## Herramientas que tiene Nexus

| Herramienta | Qué hace |
|---|---|
| `recordar` | Memoria persistente entre sesiones (`memoria.json`) |
| `rastrear_ofertas` | Baja ofertas reales de Remotive y RemoteOK por palabras clave |
| `web_search` | Busca información actual en internet |
| `run_command` | Ejecuta comandos de PowerShell (con confirmación) |
| `read_file` / `write_file` / `list_directory` | Trabaja con archivos |

## Ajustes (edita `nexus.py`, sección CONFIGURACION)

| Variable | Para qué |
|---|---|
| `MODEL` | Modelo a usar (ver costos abajo) |
| `TU_NOMBRE` | Cómo te llama Nexus |
| `MAX_TOKENS` | Largo máximo de cada respuesta |
| `PEDIR_CONFIRMACION` | `False` = ejecuta sin pedir permiso (⚠️ con cuidado) |

## Costos (pago por uso, por millón de tokens)

| Modelo | Entrada | Salida | Cuándo |
|---|---|---|---|
| `claude-opus-4-8` | $5 | $25 | El más capaz (por defecto) |
| `claude-sonnet-4-6` | $3 | $15 | Casi tan bueno, más barato |
| `claude-haiku-4-5` | $1 | $5 | El más rápido y barato |

Una sesión normal cuesta céntimos.

---

## ⚠️ Seguridad

Nexus puede ejecutar comandos en tu PC. Por eso pide confirmación antes de
ejecutar o escribir. Lee el comando antes de aceptar.

---

## Ideas para mejorarlo

- **Voz**: texto-a-voz (que hable) y voz-a-texto (hablarle tú).
- **Más fuentes de ofertas**: Workana, Upwork, r/forhire.
- **Confirmación en la web**: permitir acciones de sistema con un modal en el HUD.
