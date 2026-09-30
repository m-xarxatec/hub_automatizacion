"""Escritura segura en la bóveda.

Reglas (ver documento del proyecto):
- Archivos nuevos con nombre único en vez de editar existentes.
- Solo se agrega al final de tareas.md y de la nota del día.
- Se escribe a un temporal oculto y se renombra: Syncthing nunca copia un archivo a medias.
- Nombres válidos en Windows y en minúsculas.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_PROHIBIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVADOS = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {
    f"lpt{i}" for i in range(1, 10)
}


def sin_acentos(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normal if not unicodedata.combining(c))


def slug(texto: str, largo_max: int = 50) -> str:
    """Nombre de archivo portable: minúsculas, sin acentos ni caracteres prohibidos."""
    base = sin_acentos(texto).lower()
    base = _PROHIBIDOS.sub(" ", base)
    base = re.sub(r"[^a-z0-9ñ\s_-]", " ", base)
    base = re.sub(r"[\s_-]+", "-", base).strip("-. ")
    base = base[:largo_max].rstrip("-. ")
    if not base or base in _RESERVADOS:
        base = f"nota-{base}" if base else "nota"
    return base


def nombre_carpeta(texto: str) -> str:
    """Nombre visible de carpeta (conserva mayúsculas y acentos), válido en Windows."""
    limpio = _PROHIBIDOS.sub(" ", texto)
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")
    if not limpio or limpio.lower() in _RESERVADOS:
        raise ValueError(f"Nombre no válido: {texto!r}")
    return limpio[:60].rstrip(" .")


def ruta_unica(carpeta: Path, titulo: str, extension: str, ahora: datetime) -> Path:
    prefijo = ahora.strftime("%Y-%m-%d-%H%M")
    base = f"{prefijo}-{slug(titulo)}"
    ruta = carpeta / f"{base}{extension}"
    n = 2
    while ruta.exists():
        ruta = carpeta / f"{base}-{n}{extension}"
        n += 1
    return ruta


def escribir_atomico(ruta: Path, contenido: str | bytes) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f".{ruta.name}.tmp")
    modo = "wb" if isinstance(contenido, bytes) else "w"
    kwargs: dict[str, Any] = {} if isinstance(contenido, bytes) else {"encoding": "utf-8", "newline": "\n"}
    with open(temporal, modo, **kwargs) as f:
        f.write(contenido)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporal, ruta)
    return ruta


def agregar_al_final(ruta: Path, texto: str, encabezado: str = "") -> Path:
    """Agrega texto al final reescribiendo de forma atómica."""
    actual = ruta.read_text(encoding="utf-8") if ruta.exists() else encabezado
    if actual and not actual.endswith("\n"):
        actual += "\n"
    return escribir_atomico(ruta, actual + texto.rstrip("\n") + "\n")


def con_frontmatter(meta: dict[str, Any], cuerpo: str) -> str:
    cabecera = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{cabecera}\n---\n{cuerpo.rstrip()}\n"


def sin_frontmatter(texto: str) -> str:
    """El cuerpo de la nota, sin el bloque --- … --- del principio."""
    if texto.startswith("---\n"):
        fin = texto.find("\n---", 4)
        if fin != -1:
            return texto[fin + 4:].lstrip("\n")
    return texto


def leer_frontmatter(ruta: Path) -> dict[str, Any]:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not texto.startswith("---\n"):
        return {}
    fin = texto.find("\n---", 4)
    if fin == -1:
        return {}
    try:
        datos = yaml.safe_load(texto[4:fin]) or {}
    except yaml.YAMLError:
        return {}
    return datos if isinstance(datos, dict) else {}
