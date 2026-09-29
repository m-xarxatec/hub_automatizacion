"""Fichas de personaje desde texto o voz.

"Crea un personaje llamado Bruno que sea carnicero" -> Personajes/Bruno.md con la descripción
(Historia/Personajes/ en los proyectos que ya la tienen). Es el respaldo sin GPT: con él, lo hace el redactor.
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
SECCION_DESCRIPCION = "## Descripción"


def _aparece(texto: str, nombre: str) -> bool:
    """El nombre aparece como palabra completa y con mayúscula ("Luz", no "la luz del templo")."""
    for m in re.finditer(rf"(?<!\w){re.escape(nombre)}(?!\w)", texto, re.IGNORECASE):
        if texto[m.start()].isupper():
            return True
    return False


def fichas(boveda: Boveda, proyecto: str | None) -> dict[str, Path]:
    """Nombre -> ficha de cada personaje del proyecto."""
    if not proyecto:
        return {}
    return {str(escritor.leer_frontmatter(n).get("nombre") or n.stem): n
            for n in referencias.fichas_de(boveda, proyecto)}


def mencionado(boveda: Boveda, proyecto: str, texto: str) -> Path | None:
    """Ficha del único personaje del proyecto que se nombra en el texto (por nombre o alias).
    Si se nombran varios, no se elige ninguno: la nota va al archivo de su tipo."""
    plano = escritor.sin_acentos(texto)
    hallados = [nota for nota in referencias.fichas_de(boveda, proyecto)
                if any(_aparece(plano, escritor.sin_acentos(n)) for n in referencias.nombres_de(nota))]
    return hallados[0] if len(hallados) == 1 else None


def descripcion_vacia(ficha: Path) -> bool:
    """True si la ficha no tiene descripción: nada escrito bajo el título (fichas sin secciones,
    desde el 2026-09-30) o la sección "## Descripción" vacía (fichas anteriores)."""
    lineas = ficha.read_text(encoding="utf-8").splitlines()
    try:
        inicio = next(i for i, l in enumerate(lineas) if l.strip() == SECCION_DESCRIPCION)
    except StopIteration:
        cuerpo = escritor.sin_frontmatter(ficha.read_text(encoding="utf-8")).splitlines()
        return not any(l.strip() and not l.startswith("# ") for l in cuerpo)
    for linea in lineas[inicio + 1:]:
        if linea.startswith("## "):
            return True
        if linea.strip():
            return False
    return True


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
        if descripcion and descripcion_vacia(hallado[1]):
            if SECCION_DESCRIPCION in hallado[1].read_text(encoding="utf-8"):
                referencias.insertar_en_seccion(hallado[1], SECCION_DESCRIPCION, descripcion.strip())
            else:   # ficha sin secciones: la descripción va bajo el título
                escritor.agregar_al_final(hallado[1], f"\n{descripcion.strip()}")
            boveda.registrar_diario(f"Descripción de [[{boveda.enlace(hallado[1])}|{hallado[1].stem}]]")
        elif descripcion:
            anotar(boveda, hallado[1], descripcion, origen)
        return hallado[1], False
    ficha = referencias.crear_personaje(boveda, proyecto, nombre, descripcion)
    boveda.registrar_diario(f"Personaje nuevo [[{boveda.enlace(ficha)}|{ficha.stem}]] en {proyecto}")
    return ficha, True
