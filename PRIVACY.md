# Política de privacidad (plantilla)

> Plantilla base para Nexus. Adáptala con asesoría legal (GDPR/CCPA si aplica)
> antes de comercializar. No constituye asesoramiento jurídico.

_Última actualización: 2026-06-28_

## Qué datos maneja Nexus
- **En tu equipo (local):** memoria, tareas, alertas, gastos, conversaciones y la
  bitácora de trading se guardan en archivos locales (`*.json`, `*.log`) en tu
  máquina. No se envían a nuestros servidores.
- **Servicios de terceros que tú configuras:** según lo que actives, los datos
  necesarios se envían a esos proveedores bajo SUS políticas:
  - **Anthropic (Claude)** — tus mensajes para generar respuestas.
  - **Google (Calendar/Gmail)** — solo si conectas tu cuenta (OAuth).
  - **Telegram / Discord** — mensajes y notificaciones que tú envíes/recibas.
  - **NinjaTrader** — órdenes y datos de mercado en tu propia instalación.
  - **Open-Meteo / RSS** — consultas de clima y noticias (sin datos personales).

## Modo local gratuito
Con el backend **Ollama**, el modelo corre en tu equipo y **no se envían tus
mensajes a ninguna API externa**.

## Secretos
Las claves (API keys, tokens, `credentials.json`, `token.json`) se leen de variables
de entorno o archivos locales y están en `.gitignore`. Nunca se publican.

## Tus derechos
Tus datos locales son tuyos: puedes verlos, editarlos o borrarlos (los archivos de
datos y la carpeta `backups/`). Si se ofrece una versión hospedada (SaaS), se
detallarán aquí el responsable del tratamiento, la base legal, la retención y el
procedimiento para ejercer tus derechos (acceso, rectificación, supresión).

## Contacto
Para asuntos de privacidad: <tu-email-de-soporte>.
