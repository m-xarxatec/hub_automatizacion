"""Latido del servidor activo en _hub/.

Evita levantar el stack en dos equipos a la vez: si otro equipo escribió
un latido reciente, el arranque se detiene con un mensaje claro.

Desde el 2026-09-30 cada equipo escribe su propio archivo (`servidor-<nombre>.json`): con uno solo
compartido, si un equipo escribía sin conexión aparecían copias de conflicto de Syncthing. Se sigue
leyendo el `servidor.json` anterior, por si el otro equipo aún tiene el código viejo; además, el
error 409 de Telegram impide que dos servidores lean el bot a la vez.

Desde el 2026-09-30 (relevo, ver `relevo.py`) el latido dice además en qué estado está el equipo
(`activo`, `espera` o `apagado`), desde cuándo, si es de guardia (`cede`) y el proyecto activo de cada
chat, para que quien tome el bot siga en el mismo proyecto. Un latido sin `estado` (formato anterior)
cuenta como `activo`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from ..boveda import escritor

log = logging.getLogger(__name__)
ANTERIOR = "servidor.json"
ACTIVO, ESPERA, APAGADO = "activo", "espera", "apagado"


def ruta(interna: Path, nombre: str) -> Path:
    return interna / f"servidor-{escritor.slug(nombre)}.json"


def leer_todos(interna: Path) -> list[dict]:
    """Latidos válidos de todos los equipos (incluido el archivo anterior), sin copias de conflicto."""
    latidos = []
    for archivo in sorted(interna.glob("servidor*.json")):
        if ".sync-conflict-" in archivo.name:
            continue
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(datos, dict) and datos.get("servidor"):
            latidos.append(datos)
    return latidos


def por_servidor(interna: Path) -> dict[str, dict]:
    """El latido más reciente de cada equipo (el archivo anterior y el nuevo pueden ser del mismo)."""
    ultimos: dict[str, dict] = {}
    for d in leer_todos(interna):
        nombre = str(d["servidor"])
        if nombre not in ultimos or float(d.get("epoch", 0)) > float(ultimos[nombre].get("epoch", 0)):
            ultimos[nombre] = d
    return ultimos


def estado_de(d: dict) -> str:
    return str(d.get("estado") or ACTIVO)


def leer(interna: Path) -> dict | None:
    """El latido más reciente, sea del equipo que sea (lo muestra el chequeo)."""
    return max(leer_todos(interna), key=lambda d: float(d.get("epoch", 0)), default=None)


def escribir(interna: Path, nombre: str, ahora: float | None = None, estado: str = ACTIVO,
             desde: float | None = None, cede: bool = False, proyectos: dict[int, str] | None = None) -> None:
    ahora = time.time() if ahora is None else ahora
    datos = {"servidor": nombre, "epoch": ahora,
             "hora": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ahora)),
             "estado": estado, "desde": ahora if desde is None else desde, "cede": cede}
    if proyectos:
        datos["proyectos"] = {str(chat): p for chat, p in sorted(proyectos.items())}
    escritor.escribir_atomico(ruta(interna, nombre), json.dumps(datos, ensure_ascii=False, indent=2) + "\n")


def conflicto(interna: Path, nombre: str, vigencia_s: int, ahora: float | None = None,
              ceden: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Devuelve un mensaje si otro equipo está activo, o None si se puede arrancar.

    No cuentan los equipos en espera o apagados ni los de guardia (`ceden`): esos le dejan el bot a
    quien arranca (relevo).
    """
    ahora = time.time() if ahora is None else ahora
    otros = [d for d in leer_todos(interna) if d.get("servidor") != nombre and estado_de(d) == ACTIVO
             and not d.get("cede") and d.get("servidor") not in ceden]
    reciente = max(otros, key=lambda d: float(d.get("epoch", 0)), default=None)
    if reciente is None:
        return None
    edad = ahora - float(reciente.get("epoch", 0))
    if edad < vigencia_s:
        return (f"El equipo '{reciente.get('servidor')}' escribió un latido hace {int(edad)} s. "
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
