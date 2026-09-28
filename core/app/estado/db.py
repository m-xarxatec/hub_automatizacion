"""Estado operativo en SQLite (fuera de la bóveda).

Solo guarda lo que no tiene sentido como nota: proyecto activo, sesión, las últimas
vueltas de la consulta en curso, preferencias (modelo de análisis), gasto por proveedor
y cola de reintentos.
Nunca contenido de notas.
Se puede borrar sin perder información real.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

ESQUEMA = """
CREATE TABLE IF NOT EXISTS chat (
    chat_id   INTEGER PRIMARY KEY,
    proyecto  TEXT,
    sesion    TEXT,
    voz       TEXT
);
CREATE TABLE IF NOT EXISTS gasto (
    fecha      TEXT NOT NULL,
    proveedor  TEXT NOT NULL,
    llamadas   INTEGER NOT NULL DEFAULT 0,
    usd        REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (fecha, proveedor)
);
-- Últimas vueltas de la consulta de cada sesión (se mandan al modelo como historial).
CREATE TABLE IF NOT EXISTS conversacion (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion  TEXT NOT NULL,
    rol     TEXT NOT NULL,
    texto   TEXT NOT NULL,
    creado  REAL NOT NULL
);
-- Preferencias por chat (p. ej. el modelo de análisis elegido con /modelo).
CREATE TABLE IF NOT EXISTS preferencia (
    chat_id  INTEGER NOT NULL,
    clave    TEXT NOT NULL,
    valor    TEXT NOT NULL,
    PRIMARY KEY (chat_id, clave)
);
CREATE TABLE IF NOT EXISTS cola (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo      TEXT NOT NULL,
    datos     TEXT NOT NULL,
    creado    REAL NOT NULL,
    intentos  INTEGER NOT NULL DEFAULT 0
);
"""


class Estado:
    def __init__(self, ruta: Path):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(ruta, check_same_thread=False)
        self.cx.executescript(ESQUEMA)
        self.cx.commit()

    def _chat(self, chat_id: int) -> None:
        self.cx.execute("INSERT OR IGNORE INTO chat (chat_id, sesion) VALUES (?, ?)",
                        (chat_id, secrets.token_hex(8)))

    # --- proyecto activo ---------------------------------------------------------
    def proyecto_activo(self, chat_id: int) -> str | None:
        fila = self.cx.execute("SELECT proyecto FROM chat WHERE chat_id = ?", (chat_id,)).fetchone()
        return fila[0] if fila else None

    def fijar_proyecto(self, chat_id: int, proyecto: str | None) -> None:
        self._chat(chat_id)
        self.cx.execute("UPDATE chat SET proyecto = ? WHERE chat_id = ?", (proyecto, chat_id))
        self.cx.commit()

    # --- sesión de conversación (clave para OpenClaw) ----------------------------
    def sesion(self, chat_id: int) -> str:
        self._chat(chat_id)
        self.cx.commit()
        return self.cx.execute("SELECT sesion FROM chat WHERE chat_id = ?", (chat_id,)).fetchone()[0]

    def nueva_sesion(self, chat_id: int) -> str:
        """/nuevo: otra clave de sesión y se borra el historial de la anterior."""
        anterior = self.sesion(chat_id)
        clave = secrets.token_hex(8)
        self.cx.execute("DELETE FROM conversacion WHERE sesion = ?", (anterior,))
        self.cx.execute("UPDATE chat SET sesion = ? WHERE chat_id = ?", (clave, chat_id))
        self.cx.commit()
        return clave

    # --- historial de la consulta -----------------------------------------------
    def agregar_vuelta(self, sesion: str, pregunta: str, respuesta: str, guardar: int = 6) -> None:
        """Guarda pregunta y respuesta y deja solo los últimos `guardar` mensajes de la sesión."""
        ahora = time.time()
        self.cx.executemany(
            "INSERT INTO conversacion (sesion, rol, texto, creado) VALUES (?, ?, ?, ?)",
            [(sesion, "user", pregunta, ahora), (sesion, "assistant", respuesta, ahora)])
        self.cx.execute(
            "DELETE FROM conversacion WHERE sesion = ? AND id NOT IN "
            "(SELECT id FROM conversacion WHERE sesion = ? ORDER BY id DESC LIMIT ?)",
            (sesion, sesion, guardar))
        self.cx.commit()

    def historial(self, sesion: str, max_horas: float = 12) -> list[tuple[str, str]]:
        """[(rol, texto)] del más antiguo al más nuevo; lo de más de `max_horas` no cuenta."""
        filas = self.cx.execute(
            "SELECT rol, texto FROM conversacion WHERE sesion = ? AND creado >= ? ORDER BY id",
            (sesion, time.time() - max_horas * 3600)).fetchall()
        return [(rol, texto) for rol, texto in filas]

    # --- preferencias -----------------------------------------------------------
    def preferencia(self, chat_id: int, clave: str) -> str | None:
        fila = self.cx.execute("SELECT valor FROM preferencia WHERE chat_id = ? AND clave = ?",
                               (chat_id, clave)).fetchone()
        return fila[0] if fila else None

    def fijar_preferencia(self, chat_id: int, clave: str, valor: str) -> None:
        self.cx.execute("INSERT INTO preferencia (chat_id, clave, valor) VALUES (?, ?, ?) "
                        "ON CONFLICT(chat_id, clave) DO UPDATE SET valor = excluded.valor",
                        (chat_id, clave, valor))
        self.cx.commit()

    # --- gasto ---------------------------------------------------------------
    def sumar_gasto(self, fecha: str, proveedor: str, usd: float = 0.0) -> None:
        self.cx.execute(
            "INSERT INTO gasto (fecha, proveedor, llamadas, usd) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(fecha, proveedor) DO UPDATE SET llamadas = llamadas + 1, usd = usd + ?",
            (fecha, proveedor, usd, usd),
        )
        self.cx.commit()

    def gasto_del_dia(self, fecha: str) -> list[tuple[str, int, float]]:
        return self.cx.execute(
            "SELECT proveedor, llamadas, usd FROM gasto WHERE fecha = ? ORDER BY proveedor", (fecha,)
        ).fetchall()

    # --- cola de pendientes ------------------------------------------------------
    def encolar(self, tipo: str, datos: dict[str, Any]) -> int:
        cur = self.cx.execute("INSERT INTO cola (tipo, datos, creado) VALUES (?, ?, ?)",
                              (tipo, json.dumps(datos, ensure_ascii=False), time.time()))
        self.cx.commit()
        return int(cur.lastrowid)

    def pendientes(self) -> int:
        return self.cx.execute("SELECT COUNT(*) FROM cola").fetchone()[0]
