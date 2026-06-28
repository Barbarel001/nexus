# Despliegue de NEXUS (SaaS / servidor)

Guía para poner Nexus en producción como servicio web.

## 0. Un comando con HTTPS (docker compose + Caddy) ⭐
La forma más rápida de poner Nexus online con certificado TLS automático:
```bash
cp env.example .env        # rellena tus claves
#   edita Caddyfile y pon tu dominio (con el DNS apuntando al servidor)
docker compose up -d
```
Caddy obtiene el certificado solo y hace de reverse proxy a Nexus. Datos persistentes
en el volumen `nexus_data`.

### Webhook de Stripe (activa el plan al pagar)
En el dashboard de Stripe crea un webhook hacia `https://tu-dominio.com/api/stripe/webhook`
(evento `checkout.session.completed`) y pon el secreto en `NEXUS_STRIPE_WEBHOOK_SECRET`.
Al completarse un pago, Nexus sube automáticamente el plan del usuario.

## 1. Con Docker (manual)
```bash
docker build -t nexus .
docker run -d --name nexus -p 5000:5000 \
  -e NEXUS_MULTIUSER=1 \
  -e NEXUS_SECRET="una-clave-larga-y-secreta" \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e NEXUS_BASE_URL="https://tu-dominio" \
  -v nexus_data:/app/data \
  -e NEXUS_DB_PATH=/app/data/nexus.db \
  nexus
```
- **Persistencia:** monta un volumen y apunta los datos ahí con `NEXUS_DB_PATH` (y
  si usas el modo de archivos, `NEXUS_*_PATH`). Sin volumen, los datos se pierden al
  recrear el contenedor.
- **Un solo worker:** la imagen usa `gunicorn -w 1 --threads 8` a propósito (el estado
  vive en memoria; ver `wsgi.py`). No subas el número de *workers* sin antes mover el
  estado a la BD.

## 2. Sin Docker (VPS)
```bash
pip install -r requirements-deploy.txt
NEXUS_MULTIUSER=1 NEXUS_SECRET=... gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:5000 wsgi:app
```

## 3. HTTPS (imprescindible en producción)
Pon un reverse proxy delante (TLS + dominio). Ejemplo con **Caddy** (automático):
```
tu-dominio.com {
    reverse_proxy 127.0.0.1:5000
}
```
(o Nginx con `proxy_pass` y `proxy_buffering off;` para que el streaming SSE fluya.)

## 4. Variables clave en producción
| Variable | Para qué |
|---|---|
| `NEXUS_MULTIUSER=1` | Activa cuentas de usuario (SaaS) |
| `NEXUS_SECRET` | Firma de sesiones — **fija y secreta** |
| `NEXUS_BASE_URL` | URL pública (links de retorno de Stripe) |
| `NEXUS_STRIPE_KEY` + price IDs | Cobro por suscripción |
| `ANTHROPIC_API_KEY` | Chat con Claude (o usa Ollama) |

## 5. Checklist de "listo para vender"
- [ ] HTTPS con dominio propio
- [ ] `NEXUS_MULTIUSER=1` + `NEXUS_SECRET` fijo
- [ ] Volumen persistente para la BD y backups
- [ ] Stripe con claves reales y webhooks (para activar planes al pagar)
- [ ] Copias de seguridad del volumen
- [ ] Términos/Privacidad publicados (ver `TERMS.md`, `PRIVACY.md`)

> Nota de escalado: para varios procesos/instancias hay que sacar el estado en memoria
> (conversaciones, SSE, scheduler) a la BD y a un broker de colas. Es el siguiente
> milestone si creces.
