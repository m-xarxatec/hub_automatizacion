"""Estado operativo en SQLite (fuera de la bóveda).

Solo guarda lo que no tiene sentido como nota: proyecto activo, sesión, las últimas
vueltas de la consulta en curso, preferencias (modelo de análisis), uso de los modelos
(llamadas y tokens por día, función y modelo: /tokens y /estado), pausas de proveedores
(cortacircuitos) y cola de reintentos.
Nunca contenido de notas.
Se puede borrar sin perder información real.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS chat (
    chat_id   INTEGER PRIMARY KEY,
    proyecto  TEXT,
    sesion    TEXT,
    voz       TEXT
);
-- Uso de los modelos por día, función (interprete, redactor, consulta, analisis, router, imagen) y
-- modelo. "estimadas": llamadas cuya salida se estimó por el largo del texto (Claude Code la informa mal).
CREATE TABLE IF NOT EXISTS uso (
    fecha      TEXT NOT NULL,
    funcion    TEXT NOT NULL,
    modelo     TEXT NOT NULL,
    llamadas   INTEGER NOT NULL DEFAULT 0,
    entrada    INTEGER NOT NULL DEFAULT 0,
    salida     INTEGER NOT NULL DEFAULT 0,
    estimadas  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (fecha, funcion, modelo)
);
-- Anterior a "uso" (2026-09-30): solo contaba llamadas. Se conserva para no romper bases viejas.
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
-- Fallos seguidos de cada proveedor y hasta cuándo queda en pausa (cortacircuitos).
CREATE TABLE IF NOT EXISTS proveedor_estado (
    proveedor      TEXT PRIMARY KEY,
    fallos         INTEGER NOT NULL DEFAULT 0,
    pausado_hasta  REAL NOT NULL DEFAULT 0,
    motivo         TEXT NOT NULL DEFAULT ''
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

    def proyectos_activos(self) -> dict[int, str]:
        """chat -> proyecto activo (viaja en el latido para que quien tome el bot siga en él)."""
        filas = self.cx.execute("SELECT chat_id, proyecto FROM chat WHERE proyecto IS NOT NULL").fetchall()
        return {int(chat): str(proyecto) for chat, proyecto in filas}

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

    # --- uso de los modelos -----------------------------------------------------------
    def sumar_uso(self, fecha: str, funcion: str, modelo: str, entrada: int = 0, salida: int = 0,
                  estimada: bool = False) -> None:
        self.cx.execute(
            "INSERT INTO uso (fecha, funcion, modelo, llamadas, entrada, salida, estimadas) "
            "VALUES (?, ?, ?, 1, ?, ?, ?) ON CONFLICT(fecha, funcion, modelo) DO UPDATE SET "
            "llamadas = llamadas + 1, entrada = entrada + excluded.entrada, "
            "salida = salida + excluded.salida, estimadas = estimadas + excluded.estimadas",
            (fecha, funcion, modelo, int(entrada), int(salida), int(estimada)))
        self.cx.commit()

    def uso(self, desde: str | None = None, hasta: str | None = None,
            por: tuple[str, ...] = ("funcion", "modelo")) -> list[tuple]:
        """Filas (…agrupado por `por`, llamadas, entrada, salida, estimadas) entre dos fechas
        (inclusive; None = sin límite), de más a menos tokens."""
        columnas = ", ".join(c for c in por if c in ("fecha", "funcion", "modelo"))
        return self.cx.execute(
            f"SELECT {columnas}, SUM(llamadas), SUM(entrada), SUM(salida), SUM(estimadas) FROM uso "
            "WHERE fecha >= COALESCE(?, fecha) AND fecha <= COALESCE(?, fecha) "
            f"GROUP BY {columnas} ORDER BY SUM(entrada) + SUM(salida) DESC, SUM(llamadas) DESC",
            (desde, hasta)).fetchall()

    def primer_dia_de_uso(self) -> str | None:
        return self.cx.execute("SELECT MIN(fecha) FROM uso").fetchone()[0]

    # --- pausas de proveedores ------------------------------------------------------
    def estado_proveedor(self, proveedor: str) -> tuple[int, float, str]:
        """(fallos seguidos, pausado hasta [epoch], motivo del último fallo)."""
        fila = self.cx.execute(
            "SELECT fallos, pausado_hasta, motivo FROM proveedor_estado WHERE proveedor = ?",
            (proveedor,)).fetchone()
        return (fila[0], fila[1], fila[2]) if fila else (0, 0.0, "")

    def fijar_estado_proveedor(self, proveedor: str, fallos: int, pausado_hasta: float,
                               motivo: str) -> None:
        self.cx.execute(
            "INSERT INTO proveedor_estado (proveedor, fallos, pausado_hasta, motivo) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(proveedor) DO UPDATE SET fallos = excluded.fallos, "
            "pausado_hasta = excluded.pausado_hasta, motivo = excluded.motivo",
            (proveedor, fallos, pausado_hasta, motivo))
        self.cx.commit()

    # --- cola de pendientes ------------------------------------------------------
    def encolar(self, tipo: str, datos: dict[str, Any]) -> int:
        cur = self.cx.execute("INSERT INTO cola (tipo, datos, creado) VALUES (?, ?, ?)",
                              (tipo, json.dumps(datos, ensure_ascii=False), time.time()))
        self.cx.commit()
        return int(cur.lastrowid)

    def pendientes(self) -> int:
        return self.cx.execute("SELECT COUNT(*) FROM cola").fetchone()[0]


def contador_de_uso(estado: Estado, zona: str) -> Callable[[str, Any], None]:
    """Para OpenClaw(contador=…): suma cada respuesta en la tabla `uso` con la fecha local."""
    def contar(funcion: str, r: Any) -> None:
        estado.sumar_uso(datetime.now(ZoneInfo(zona)).date().isoformat(), funcion, r.modelo,
                         r.tokens_entrada, r.tokens_salida, r.salida_estimada)
    return contar
