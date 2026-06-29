# Despliegue de NEXUS

Guía para usar Nexus desde el móvil / internet. Elige tu caso y sigue **una** ruta.

## ¿Qué opción elijo?

| Quiero… | Ruta | Coste | Dificultad |
|---|---|---|---|
| Usarlo **solo yo**, desde el móvil, sin servidor | **A) Mi PC + túnel** | gratis | fácil |
| Tenerlo **encendido 24/7** para mí | **B) Docker + Caddy** | un VPS (~5 $/mes) | media |
| **Venderlo** (varios usuarios, pagos) | **C) SaaS multiusuario** | VPS + dominio | media-alta |

> Antes de nada: `cp .env.example .env` y rellena lo que necesites. Todas las
> variables están explicadas en [`.env.example`](.env.example).

---

## A) Mi PC + túnel (gratis, sin servidor) ⭐ para uso personal

Nexus corre en tu computadora y un **túnel** te da una URL pública temporal para
entrar desde el móvil. Protégelo **siempre** con contraseña.

```bash
# 1) Protege el acceso (¡imprescindible si lo expones!)
export NEXUS_PASSWORD="una-clave-fuerte"
export NEXUS_HTTPS=1               # el túnel da HTTPS

# 2) Arranca Nexus
python nexus_web.py               # escucha en 127.0.0.1:5000

# 3) En otra terminal, abre el túnel (elige uno):
cloudflared tunnel --url http://localhost:5000      # Cloudflare (gratis)
#  o
ngrok http 5000                                     # ngrok (gratis)
```

Copia la URL `https://…` que imprime el túnel y ábrela en el móvil. Entra con tu
contraseña. Cuando apagas el PC o el túnel, la URL deja de funcionar (normal).

---

## B) Docker + Caddy (encendido 24/7, HTTPS automático) ⭐ para ti en un VPS

La forma más rápida de ponerlo online con certificado TLS automático en tu propio
dominio (con el DNS del dominio apuntando a la IP del servidor):

```bash
cp .env.example .env        # rellena ANTHROPIC_API_KEY, NEXUS_SECRET, etc.
#   edita Caddyfile y pon tu dominio
docker compose up -d
```

Caddy obtiene el certificado solo y hace de reverse proxy a Nexus. Los datos
persisten en el volumen `nexus_data`.

### Docker manual (sin compose)
```bash
docker build -t nexus .
docker run -d --name nexus -p 5000:5000 \
  -e NEXUS_PASSWORD="una-clave-fuerte" \
  -e NEXUS_SECRET="una-clave-larga-y-secreta" \
  -e NEXUS_HTTPS=1 \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v nexus_data:/app/data \
  -e NEXUS_DB_PATH=/app/data/nexus.db \
  nexus
```
- **Persistencia:** monta un volumen y apunta los datos ahí (`NEXUS_DB_PATH`, y si usas
  modo archivos, `NEXUS_*_PATH` / `NEXUS_USERS_DIR`). Sin volumen, los datos se pierden
  al recrear el contenedor.
- **Un solo worker:** la imagen usa `gunicorn -w 1 --threads 8` a propósito (el estado
  vive en memoria; ver `wsgi.py`). No subas los *workers* sin mover antes el estado a la BD.

### Sin Docker (VPS a pelo)
```bash
pip install -r requirements-deploy.txt
NEXUS_PASSWORD=... NEXUS_SECRET=... NEXUS_HTTPS=1 \
  gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:5000 wsgi:app
```
Pon un reverse proxy delante para TLS (Caddy recomendado):
```
tu-dominio.com {
    reverse_proxy 127.0.0.1:5000
}
```
(o Nginx con `proxy_pass` y `proxy_buffering off;` para que el streaming SSE fluya.)

---

## C) SaaS multiusuario (para vender)

Sobre la ruta B, añade cuentas y cobros:

```bash
NEXUS_MULTIUSER=1          # registro/login con email+contraseña (SQLite)
NEXUS_SECRET=...           # fija y secreta
NEXUS_BASE_URL=https://tu-dominio.com
NEXUS_ADMIN_EMAIL=tu@correo.com   # acceso al panel /admin
```

### Pagos (Stripe)
1. En Stripe crea los **precios** y ponlos en `NEXUS_STRIPE_PRICE_PRO` / `NEXUS_STRIPE_PRICE_TEAM`.
2. Pon tu `NEXUS_STRIPE_KEY` (`sk_live_…`).
3. Crea un **webhook** hacia `https://tu-dominio.com/api/stripe/webhook` (evento
   `checkout.session.completed`) y guarda el secreto en `NEXUS_STRIPE_WEBHOOK_SECRET`.
   Al completarse un pago, Nexus sube el plan del usuario automáticamente.

### Notificaciones Web Push (opcional)
```bash
pip install pywebpush
python nexus_push.py genkeys      # imprime las claves VAPID
# exporta NEXUS_VAPID_PUBLIC / NEXUS_VAPID_PRIVATE / NEXUS_VAPID_SUBJECT
```

---

## Variables clave en producción
| Variable | Para qué |
|---|---|
| `NEXUS_SECRET` | Firma de sesiones — **fija y secreta** |
| `NEXUS_HTTPS=1` | Cookie de sesión `Secure` (tras TLS) |
| `NEXUS_PASSWORD` *o* `NEXUS_MULTIUSER=1` | Proteger el acceso (clave única / cuentas) |
| `NEXUS_BASE_URL` | URL pública (links de retorno de Stripe) |
| `NEXUS_ADMIN_EMAIL` | Acceso al panel `/admin` |
| `ANTHROPIC_API_KEY` | Chat con Claude (o usa Ollama, $0) |

> La lista completa y comentada está en [`.env.example`](.env.example).

## Checklist de "listo para producción"
- [ ] HTTPS con dominio propio (o túnel para uso personal)
- [ ] `NEXUS_SECRET` fijo + acceso protegido (`NEXUS_PASSWORD` o `NEXUS_MULTIUSER`)
- [ ] `NEXUS_HTTPS=1` detrás de TLS
- [ ] Volumen persistente para la BD y los datos por usuario
- [ ] Copias de seguridad del volumen
- [ ] (Si vendes) Stripe con claves reales + webhook; Términos/Privacidad publicados
- [ ] (Opcional) 2FA activado por los usuarios desde `/seguridad`

> Nota de escalado: para varios procesos/instancias hay que sacar el estado en memoria
> (conversaciones, SSE, scheduler) a la BD y a un broker de colas. Es el siguiente
> milestone si creces.
