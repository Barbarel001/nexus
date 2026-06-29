#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilidades base de NEXUS (sin dependencias de otros modulos del proyecto, para
evitar imports circulares).

- guardar_json: escritura ATOMICA (escribe a un temporal y reemplaza). Asi, si el
  programa se corta a mitad de un guardado, el archivo original NO se corrompe.
- cargar_json: lectura tolerante (devuelve un valor por defecto si falta o esta roto).
- log: registro simple de eventos/errores a un archivo (y a consola).
"""

import datetime
import json
import os
import shutil
import tempfile

LOG_PATH = os.environ.get("NEXUS_LOG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "nexus.log")


def guardar_json(path: str, data) -> None:
    """Guarda `data` como JSON de forma ATOMICA (temp + os.replace)."""
    carpeta = os.path.dirname(os.path.abspath(path))
    os.makedirs(carpeta, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # operacion atomica en el mismo sistema de archivos
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def cargar_json(path: str, defecto=None):
    """Lee un JSON; devuelve `defecto` si no existe o esta corrupto."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def respaldar(rutas, carpeta_dest: str, keep: int = 7) -> int:
    """Copia los archivos indicados a carpeta_dest/<AAAA-MM-DD>/ y conserva solo las
    ultimas `keep` carpetas de fecha. Devuelve cuantos archivos copio. No lanza."""
    try:
        fecha = datetime.date.today().isoformat()
        destino = os.path.join(carpeta_dest, fecha)
        os.makedirs(destino, exist_ok=True)
    except OSError:
        return 0
    copiados = 0
    for r in rutas:
        try:
            if os.path.isfile(r):
                shutil.copy2(r, os.path.join(destino, os.path.basename(r)))
                copiados += 1
        except OSError:
            pass
    # Limpieza de respaldos antiguos.
    try:
        carpetas = sorted(d for d in os.listdir(carpeta_dest)
                          if os.path.isdir(os.path.join(carpeta_dest, d)))
        if keep > 0:
            for d in carpetas[:-keep]:
                shutil.rmtree(os.path.join(carpeta_dest, d), ignore_errors=True)
    except OSError:
        pass
    return copiados


def log(mensaje: str, nivel: str = "INFO") -> None:
    """Registra un evento con fecha. Nunca lanza (el log no debe romper nada)."""
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linea = f"{ts} [{nivel}] {mensaje}"
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass
