"""Dónde va cada nota.

1. Si el usuario pidió un archivo propio ("crea un archivo…", "nota aparte…") -> archivo nuevo.
2. Si nombra a un personaje con ficha en el proyecto -> "## Notas" de esa ficha.
3. Si no -> al final del archivo de su tipo (Ideas.md, Historia.md, Produccion.md).
Las tareas siguen en boveda/proyectos.py (agregar_tarea).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..boveda.proyectos import Boveda
from ..router.reglas import archivo_aparte
from . import personajes


@dataclass
class Guardado:
    ruta: Path
    como: str   # "agregada" | "aparte" | "personaje"


def guardar(boveda: Boveda, texto: str, proyecto: str | None, tipo: str, origen: str) -> Guardado:
    propio = archivo_aparte(texto)
    if propio:
        return Guardado(boveda.guardar_nota(propio, proyecto, tipo, origen, aparte=True), "aparte")
    if proyecto:
        ficha = personajes.mencionado(boveda, proyecto, texto)
        if ficha:
            return Guardado(personajes.anotar(boveda, ficha, texto, origen), "personaje")
    return Guardado(boveda.guardar_nota(texto, proyecto, tipo, origen), "agregada")
