# Imagen de producción de NEXUS (servidor web).
FROM python:3.12-slim

WORKDIR /app

# Dependencias primero (mejor caché de capas).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Código.
COPY . .

# Defaults de producción (sobre-escribibles en runtime con -e / env del orquestador).
ENV NEXUS_OPEN=0 \
    NEXUS_HOST=0.0.0.0 \
    NEXUS_PORT=5000 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# Comprueba que el servidor responde (sin curl: usamos Python).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4)" || exit 1

# Un solo worker con varios hilos (ver wsgi.py). timeout alto para el streaming SSE.
CMD ["gunicorn", "-w", "1", "--threads", "8", "--timeout", "300", "-b", "0.0.0.0:5000", "wsgi:app"]
