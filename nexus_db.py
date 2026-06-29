#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base de datos (SQLite) y cuentas de usuario para NEXUS — base del modo multiusuario
(SaaS). Sin dependencias externas (sqlite3 + hashlib de la stdlib).

Tablas:
  users(id, email, password_hash, plan, creado)
  user_data(user_id, clave, datos)   -- almacen JSON por usuario y clave

Las contraseñas se guardan con PBKDF2-HMAC-SHA256 (salt por usuario). Nunca en claro.

Configuracion:
    NEXUS_DB_PATH   Ruta del archivo SQLite (defecto: nexus.db junto a este script).
"""

import os
import json
import sqlite3
import hashlib
import secrets
import datetime

_CARPETA = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("NEXUS_DB_PATH") or os.path.join(_CARPETA, "nexus.db")

_ITERACIONES = 200_000


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Crea las tablas si no existen. Idempotente."""
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            plan TEXT DEFAULT 'free',
            creado TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_data(
            user_id INTEGER NOT NULL,
            clave TEXT NOT NULL,
            datos TEXT NOT NULL,
            PRIMARY KEY(user_id, clave),
            FOREIGN KEY(user_id) REFERENCES users(id))""")
        # Migracion suave: columnas de 2FA (TOTP) si la tabla es de una version previa.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if "totp_secret" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
        if "totp_enabled" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN totp_enabled INTEGER DEFAULT 0")


# --------------------------- Contraseñas ---------------------------

def _hash_password(password: str, salt: str = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERACIONES)
    return f"{salt}${dk.hex()}"


def _verificar_password(password: str, almacenado: str) -> bool:
    try:
        salt, _ = almacenado.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return secrets.compare_digest(_hash_password(password, salt), almacenado)


# --------------------------- Usuarios ---------------------------

def _normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def crear_usuario(email: str, password: str, plan: str = "free") -> dict:
    """Crea un usuario. Lanza ValueError si el email es invalido, la contraseña es
    corta o el email ya existe. Devuelve el usuario creado (sin el hash)."""
    email = _normalizar_email(email)
    if "@" not in email or "." not in email:
        raise ValueError("Email invalido.")
    if len((password or "")) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    init()
    try:
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO users(email, password_hash, plan, creado) VALUES(?,?,?,?)",
                (email, _hash_password(password), plan, datetime.date.today().isoformat()))
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Ese email ya está registrado.")
    return {"id": uid, "email": email, "plan": plan}


def autenticar(email: str, password: str):
    """Devuelve el dict del usuario si las credenciales son correctas, o None."""
    email = _normalizar_email(email)
    init()
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if row and _verificar_password(password, row["password_hash"]):
        return {"id": row["id"], "email": row["email"], "plan": row["plan"]}
    return None


def obtener_usuario(user_id: int):
    init()
    with _conn() as c:
        row = c.execute("SELECT id, email, plan, creado FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def usuario_por_email(email: str):
    init()
    with _conn() as c:
        row = c.execute("SELECT id, email, plan, creado FROM users WHERE email=?",
                        (_normalizar_email(email),)).fetchone()
    return dict(row) if row else None


def cambiar_password(user_id: int, password_actual: str, password_nuevo: str) -> None:
    """Cambia la contraseña validando la actual. Lanza ValueError si algo falla."""
    init()
    with _conn() as c:
        row = c.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not _verificar_password(password_actual, row["password_hash"]):
        raise ValueError("La contraseña actual no es correcta.")
    if len((password_nuevo or "")) < 6:
        raise ValueError("La nueva contraseña debe tener al menos 6 caracteres.")
    with _conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?",
                  (_hash_password(password_nuevo), user_id))


def borrar_usuario(user_id: int) -> None:
    """Elimina el usuario y todos sus datos en la BD (no toca archivos en disco)."""
    init()
    with _conn() as c:
        c.execute("DELETE FROM user_data WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))


def cambiar_plan(user_id: int, plan: str) -> None:
    init()
    with _conn() as c:
        c.execute("UPDATE users SET plan=? WHERE id=?", (plan, user_id))


def contar_usuarios() -> int:
    init()
    with _conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def listar_usuarios(limite: int = 500) -> list:
    """Lista usuarios (más recientes primero) para el panel de administración."""
    init()
    with _conn() as c:
        rows = c.execute("SELECT id, email, plan, creado FROM users ORDER BY id DESC LIMIT ?",
                         (limite,)).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    """Métricas agregadas: total de usuarios y desglose por plan."""
    init()
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        por_plan = {r["plan"]: r["n"]
                    for r in c.execute("SELECT plan, COUNT(*) AS n FROM users GROUP BY plan").fetchall()}
    return {"usuarios": total, "por_plan": por_plan}


# --------------------------- 2FA (TOTP) ---------------------------

def get_totp(user_id: int):
    """Devuelve (secreto, activado) del usuario; (None, False) si no existe."""
    init()
    with _conn() as c:
        row = c.execute("SELECT totp_secret, totp_enabled FROM users WHERE id=?",
                        (user_id,)).fetchone()
    if not row:
        return (None, False)
    return (row["totp_secret"], bool(row["totp_enabled"]))


def set_totp_secret(user_id: int, secret: str) -> None:
    """Guarda un secreto TOTP pendiente (aun no activado hasta confirmar un codigo)."""
    init()
    with _conn() as c:
        c.execute("UPDATE users SET totp_secret=?, totp_enabled=0 WHERE id=?", (secret, user_id))


def enable_totp(user_id: int) -> None:
    init()
    with _conn() as c:
        c.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user_id,))


def disable_totp(user_id: int) -> None:
    """Desactiva el 2FA y borra el secreto."""
    init()
    with _conn() as c:
        c.execute("UPDATE users SET totp_secret=NULL, totp_enabled=0 WHERE id=?", (user_id,))


# --------------------------- Datos por usuario ---------------------------

def guardar_dato(user_id: int, clave: str, valor) -> None:
    """Guarda un valor JSON-serializable bajo (user_id, clave)."""
    init()
    with _conn() as c:
        c.execute("""INSERT INTO user_data(user_id, clave, datos) VALUES(?,?,?)
                     ON CONFLICT(user_id, clave) DO UPDATE SET datos=excluded.datos""",
                  (user_id, clave, json.dumps(valor, ensure_ascii=False)))


def cargar_dato(user_id: int, clave: str, defecto=None):
    init()
    with _conn() as c:
        row = c.execute("SELECT datos FROM user_data WHERE user_id=? AND clave=?",
                        (user_id, clave)).fetchone()
    if not row:
        return defecto
    try:
        return json.loads(row["datos"])
    except (ValueError, TypeError):
        return defecto
