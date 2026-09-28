"""Limpieza de archivos temporales.

Regla: la bóveda es la única base de datos. Todo lo que vive en datos/
es temporal y se borra por antigüedad según config.yaml (limpieza:).
En la bóveda solo se tocan restos .*.tmp de escrituras interrumpidas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


def _viejos(carpeta: Path, max_edad_s: float, ahora: float, patron: str = "*") -> list[Path]:
    if not carpeta.exists():
        return []
    return [p for p in carpeta.rglob(patron)
            if p.is_file() and ahora - p.stat().st_mtime > max_edad_s]


def candidatos(datos: Path, boveda: Path, cfg: dict, ahora: float | None = None) -> list[Path]:
    ahora = time.time() if ahora is None else ahora
    hora, dia = 3600, 86400
    rutas: list[Path] = []
    rutas += _viejos(datos / "tmp", cfg.get("temp_dir_horas", 24) * hora, ahora)
    rutas += _viejos(datos / "descartadas", cfg.get("imagenes_descartadas_dias", 7) * dia, ahora)
    rutas += [p for p in _viejos(datos / "logs", cfg.get("logs_dias", 14) * dia, ahora)
              if p.name != "hub.log"]
    rutas += _viejos(boveda, cfg.get("temporales_boveda_horas", 1) * hora, ahora, ".*.tmp")
    return sorted(set(rutas))


def limpiar(datos: Path, boveda: Path, cfg: dict, simular: bool = False,
            ahora: float | None = None) -> list[Path]:
    rutas = candidatos(datos, boveda, cfg, ahora)
    if simular:
        return rutas
    borrados = []
    for p in rutas:
        try:
            p.unlink()
            borrados.append(p)
        except OSError as e:
            log.warning("No se pudo borrar %s: %s", p, e)
    if borrados:
        log.info("Limpieza: %d archivos borrados", len(borrados))
    return borrados


def segundos_hasta(hora: str, zona: str) -> float:
    tz = ZoneInfo(zona)
    ahora = datetime.now(tz)
    h, m = (int(x) for x in hora.split(":"))
    objetivo = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    if objetivo <= ahora:
        objetivo += timedelta(days=1)
    return (objetivo - ahora).total_seconds()


async def bucle(datos: Path, boveda: Path, cfg: dict, zona: str) -> None:
    while True:
        await asyncio.sleep(segundos_hasta(cfg.get("hora", "04:00"), zona))
        await asyncio.to_thread(limpiar, datos, boveda, cfg)
