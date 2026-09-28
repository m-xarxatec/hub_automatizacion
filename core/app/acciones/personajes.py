"""Fichas de personaje desde texto o voz.

"Crea un personaje llamado Bruno que sea carnicero" -> Historia/Personajes/Bruno.md con la descripción.
"Zamael odia la lluvia" (Zamael ya tiene ficha) -> se agrega a "## Notas" de su ficha.
Las fotos de referencia de personaje siguen en acciones/referencias.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..boveda import escritor
from ..boveda.proyectos import Boveda
from . import referencias

SECCION_NOTAS = "## Notas"


def _aparece(texto: str, nombre: str) -> bool:
    """El nombre aparece como palabra completa y con mayúscula ("Luz", no "la luz del templo")."""
    for m in re.finditer(rf"(?<!\w){re.escape(nombre)}(?!\w)", texto, re.IGNORECASE):
        if texto[m.start()].isupper():
            return True
    return False


def mencionado(boveda: Boveda, proyecto: str, texto: str) -> Path | None:
    """Ficha del único personaje del proyecto que se nombra en el texto (por nombre o alias).
    Si se nombran varios, no se elige ninguno: la nota va al archivo de su tipo."""
    carpeta = referencias.carpeta_personajes(boveda, proyecto)
    if not carpeta.exists():
        return None
    plano = escritor.sin_acentos(texto)
    hallados = []
    for nota in sorted(carpeta.glob("*.md")):
        meta = escritor.leer_frontmatter(nota)
        alias = meta.get("aliases") or []
        if isinstance(alias, str):
            alias = [alias]
        nombres = [nota.stem, str(meta.get("nombre") or "")] + [str(a) for a in alias]
        if any(_aparece(plano, escritor.sin_acentos(n)) for n in nombres if n.strip()):
            hallados.append(nota)
    return hallados[0] if len(hallados) == 1 else None


def anotar(boveda: Boveda, ficha: Path, texto: str, origen: str) -> Path:
    ahora = boveda.ahora()
    via = "voz" if origen == "voz" else "texto"
    linea = f"- {ahora.strftime('%Y-%m-%d %H:%M')} ({via}): {' '.join(texto.split())}"
    referencias.insertar_en_seccion(ficha, SECCION_NOTAS, linea)
    boveda.registrar_diario(f"Nota en [[{boveda.enlace(ficha)}|{ficha.stem}]]")
    return ficha


def crear_o_anotar(boveda: Boveda, proyecto: str, nombre: str, descripcion: str,
                   origen: str) -> tuple[Path, bool]:
    """Crea la ficha con la descripción, o si ya existe agrega la descripción a sus notas.
    Devuelve (ficha, True si se creó)."""
    hallado = referencias.buscar_personaje(boveda, nombre, proyecto)
    if hallado:
        if descripcion:
            anotar(boveda, hallado[1], descripcion, origen)
        return hallado[1], False
    ficha = referencias.crear_personaje(boveda, proyecto, nombre, descripcion)
    boveda.registrar_diario(f"Personaje nuevo [[{boveda.enlace(ficha)}|{ficha.stem}]] en {proyecto}")
    return ficha, True
