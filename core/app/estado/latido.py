"""Latido del servidor activo en _hub/servidor.json.

Evita levantar el stack en dos equipos a la vez: si otro equipo escribió
un latido reciente, el arranque se detiene con un mensaje claro.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from ..boveda import escritor

log = logging.getLogger(__name__)


def ruta(interna: Path) -> Path:
    return interna / "servidor.json"


def leer(interna: Path) -> dict | None:
    try:
        return json.loads(ruta(interna).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def escribir(interna: Path, nombre: str, ahora: float | None = None) -> None:
    ahora = time.time() if ahora is None else ahora
    datos = {"servidor": nombre, "epoch": ahora,
             "hora": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ahora))}
    escritor.escribir_atomico(ruta(interna), json.dumps(datos, ensure_ascii=False, indent=2) + "\n")


def conflicto(interna: Path, nombre: str, vigencia_s: int, ahora: float | None = None) -> str | None:
    """Devuelve un mensaje si otro equipo está activo, o None si se puede arrancar."""
    ahora = time.time() if ahora is None else ahora
    datos = leer(interna)
    if not datos or datos.get("servidor") == nombre:
        return None
    edad = ahora - float(datos.get("epoch", 0))
    if edad < vigencia_s:
        return (f"El equipo '{datos.get('servidor')}' escribió un latido hace {int(edad)} s. "
                "Detén el stack allí (docker compose down) y espera a que Syncthing sincronice. "
                "Si ese equipo está apagado de verdad, usa FORZAR_ARRANQUE=1.")
    return None


async def bucle(interna: Path, nombre: str, intervalo_s: int) -> None:
    while True:
        try:
            escribir(interna, nombre)
        except OSError as e:
            log.warning("No se pudo escribir el latido: %s", e)
        await asyncio.sleep(intervalo_s)
