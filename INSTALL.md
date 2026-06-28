# Instalación de NEXUS

Tres formas, de la más simple a la de "producto".

## A) Desde el código (recomendada para empezar)
```powershell
pip install -r requirements.txt
python nexus_web.py        # se abre en http://127.0.0.1:5000
```

## B) Ejecutable de un clic (Windows .exe)
Genera un ejecutable con PyInstaller (no necesita que el usuario final tenga Python):
```powershell
build_installer.bat
```
Esto crea **`dist\NEXUS\NEXUS.exe`**. Copia esa carpeta a donde quieras y haz doble
clic. Los datos personales (memoria, tareas, etc.) se guardan donde apunten las
variables `NEXUS_*_PATH`; lo más cómodo es lanzarlo con `nexus_servicio.bat`, que
fija la configuración y reinicia solo si se cae.

> Para un **instalador con asistente** (setup.exe) puedes envolver `dist\NEXUS`
> con [Inno Setup](https://jrsoftware.org/isinfo.php) (gratis): crea un script
> `.iss` que copie la carpeta a Archivos de Programa y añada un acceso directo.
> (Paso opcional, fuera del alcance de este repo.)

## C) Hospedado (SaaS)
Para ofrecerlo como servicio web multiusuario, despliega `nexus_web.py` detrás de un
servidor WSGI (gunicorn/uvicorn) con `NEXUS_MULTIUSER=1`, base de datos y HTTPS.
Ver la sección de multiusuario en el README.

---

### Notas
- **Antivirus/SmartScreen:** los .exe de PyInstaller sin firmar pueden dar aviso de
  SmartScreen. Para distribución seria, firma el ejecutable con un certificado de
  *code signing*.
- **Tamaño:** el .exe incluye Python y dependencias (~60–120 MB). Es normal.
