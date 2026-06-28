# Seguridad de NEXUS

Resumen honesto del modelo de seguridad y de lo que falta endurecer según el uso.

## Modelo por escenario

### Uso local / personal (por defecto) — sólido
- El servidor escucha solo en `127.0.0.1` (no accesible desde fuera).
- Secretos (API keys, tokens, `credentials.json`) en variables de entorno / archivos
  `git-ignored`; **nunca** en el código ni en el repo.
- Acciones peligrosas (`run_command`, `write_file`, órdenes de trading, enviar correo,
  crear evento) requieren **confirmación** y están **desactivadas por defecto** en web/Telegram.
- `read_file` / `list_directory` **solo** existen en la terminal local (no en web/Telegram).

### Expuesto a internet / SaaS — requiere endurecer
Antes de abrirlo a terceros:

- **Contraseñas** con PBKDF2-HMAC-SHA256 (200k iter + salt), comparación de tiempo constante. ✅
- **Sesiones** firmadas, `HttpOnly`, `SameSite=Lax`; `Secure` con `NEXUS_HTTPS=1`. ✅
- **Login con límite de intentos** por IP (anti fuerza bruta). ✅
- **HTTPS** mediante reverse proxy (Caddy/Nginx) — imprescindible. ✅ (ver `DEPLOY.md`)
- **Webhook de Stripe** con verificación de firma. ✅

## ⚠️ Limitaciones conocidas (TODO antes de SaaS público)
1. **Aislamiento de datos por usuario:** las cuentas (login) funcionan, pero los datos
   de funciones (tareas, memoria, gastos, conversaciones) aún se guardan en archivos
   **globales**, no por usuario. **No abras el modo multiusuario a terceros** hasta
   enrutar cada almacenamiento por `user_id` (la BD ya tiene `user_data` por usuario
   como base). Es el trabajo #1 pendiente para SaaS real.
2. **CSRF tokens:** se confía en `SameSite=Lax` (mitiga la mayoría de casos). Para SaaS,
   añadir tokens CSRF a las acciones POST.
3. **2FA:** no implementado.
4. **Escaneo de dependencias:** recomendable añadir Dependabot / `pip-audit` en CI.
5. **Inyección de prompt:** el agente lee web/documentos/correos; las acciones que
   importan están detrás de confirmación, lo que lo mitiga, pero revisa antes de aprobar.

## Variables de seguridad
| Variable | Para qué |
|---|---|
| `NEXUS_PASSWORD` / `NEXUS_MULTIUSER` | Exigir login (una clave / cuentas) |
| `NEXUS_SECRET` | Firma de sesiones (fija y secreta en prod) |
| `NEXUS_HTTPS=1` | Cookie de sesión `Secure` (tras TLS) |
| `NEXUS_LOGIN_LIMITE` / `NEXUS_LOGIN_VENTANA` | Límite de intentos de login por IP |
| `NEXUS_ADMIN_EMAIL` | Quién accede al panel de administración |

## Reportar una vulnerabilidad
Escribe a <tu-email-de-seguridad>. No abras un issue público para fallos sensibles.
