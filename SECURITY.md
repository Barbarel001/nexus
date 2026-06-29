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
- **CSRF tokens** en todas las acciones POST cuando hay login activo. ✅
- **2FA (TOTP)** opcional por usuario (Google Authenticator/Authy/1Password). ✅
- **Escaneo de dependencias** (`pip-audit` en CI + Dependabot). ✅

## ✅ Resuelto
1. **Aislamiento de datos por usuario:** en modo multiusuario, cada usuario guarda sus
   datos (memoria, tareas, alertas, gastos, conversaciones, documentos) en su propia
   carpeta `data/users/<id>/` (`nexus_ctx`). Un usuario no puede ver los datos de otro.
2. **CSRF tokens:** patrón *double-submit*. El servidor publica un token en la cookie
   `nexus_csrf` y lo exige en la cabecera `X-CSRF-Token` (o el campo `csrf_token`) en
   todo POST/PUT/PATCH/DELETE cuando el login está activo. El webhook de Stripe (firma
   propia) y el login/registro (cubiertos por `SameSite=Lax`) quedan exentos.
3. **2FA (TOTP):** cada usuario puede activar verificación en 2 pasos desde
   `/seguridad`. Implementado en Python puro (`nexus_totp`, RFC 6238), sin dependencias.
   Tras la contraseña, el login pide un código de 6 dígitos.
4. **Escaneo de dependencias:** `pip-audit` corre en CI (`.github/workflows/ci.yml`) y
   Dependabot (`.github/dependabot.yml`) abre PRs semanales de actualización (pip +
   GitHub Actions).

## ⚠️ Pendiente / a revisar
- **Inyección de prompt:** el agente lee web/documentos/correos; las acciones que
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
