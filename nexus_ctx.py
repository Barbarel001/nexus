#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contexto de usuario para NEXUS — aislamiento de datos en modo multiusuario.

Mantiene, por hilo, el "usuario actual" de la petición web. Las funciones de
almacenamiento (memoria, tareas, alertas, gastos, conversaciones, documentos)
consultan aquí qué ruta usar:

  - Sin usuario en contexto (uso local / terminal / single-user) -> ruta GLOBAL de
    siempre (no cambia nada).
  - Con usuario en contexto (web multiusuario, sesión iniciada) -> una carpeta
    PROPIA del usuario:  <NEXUS_USERS_DIR>/<user_id>/<archivo>.

Así, en SaaS multiusuario, los datos de un usuario nunca se mezclan con los de otro.
"""

import os
import threading

_CARPETA = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.environ.get("NEXUS_USERS_DIR") or os.path.join(_CARPETA, "data", "users")

_local = threading.local()


def set_user(uid) -> None:
    _local.uid = uid


def clear_user() -> None:
    _local.uid = None


def current_user():
    return getattr(_local, "uid", None)


def _carpeta_usuario() -> str:
    carpeta = os.path.join(USERS_DIR, str(current_user()))
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


def user_path(ruta_global: str) -> str:
    """Devuelve la ruta de archivo a usar: la propia del usuario si hay uno en
    contexto, o la global si no."""
    if current_user() is None:
        return ruta_global
    return os.path.join(_carpeta_usuario(), os.path.basename(ruta_global))


def user_dir(dir_global: str) -> str:
    """Como user_path pero para una CARPETA (p. ej. documentos)."""
    if current_user() is None:
        return dir_global
    return os.path.join(_carpeta_usuario(), os.path.basename(dir_global.rstrip("/\\")))
