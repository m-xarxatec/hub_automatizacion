"""Ejemplos de entrenamiento del clasificador y correcciones hechas con botones.

- ejemplos.yaml (en el repo): frases base escritas a mano.
- correcciones.yaml (en /datos/router/): lo que el usuario eligió con los botones.
- aprendidos.yaml (en /datos/router/): frases en las que el clasificador dudó y la IA
  (LLM local o externo) confirmó la acción, que se ejecutó sin preguntar. Así el modelo
  grande le enseña al chico y cada vez hace falta consultarlo menos.
  Ambos viven fuera del repo y de la bóveda: son estado operativo de cada equipo.

Al entrenar se unen las tres fuentes en este orden: ejemplos, aprendidos, correcciones.
Si dos fuentes etiquetan distinto la misma frase, gana la última: la palabra del
usuario manda sobre la de la IA.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .reglas import normalizar

EJEMPLOS_BASE = Path(__file__).parent / "datos" / "ejemplos.yaml"
ARCHIVO_CORRECCIONES = "correcciones.yaml"
ARCHIVO_APRENDIDOS = "aprendidos.yaml"

# Solo aplican a imágenes con pie de foto y las resuelven las reglas.
SOLO_IMAGEN = frozenset({"referencia", "referencia_personaje"})


def acciones_de_texto(acciones: list[str]) -> list[str]:
    return [a for a in acciones if a not in SOLO_IMAGEN]


def leer_ejemplos(ruta: Path = EJEMPLOS_BASE) -> dict[str, list[str]]:
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return {str(accion): [str(t) for t in (textos or [])] for accion, textos in datos.items()}


def leer_correcciones(carpeta: Path, archivo: str = ARCHIVO_CORRECCIONES) -> list[dict[str, str]]:
    ruta = carpeta / archivo
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or []
    return [d for d in datos if isinstance(d, dict) and d.get("texto") and d.get("accion")]


def leer_aprendidos(carpeta: Path) -> list[dict[str, str]]:
    return leer_correcciones(carpeta, ARCHIVO_APRENDIDOS)


def guardar_correccion(carpeta: Path, texto: str, accion: str,
                       archivo: str = ARCHIVO_CORRECCIONES) -> None:
    """Agrega una entrada al final: una lista YAML sigue siendo válida al crecer."""
    carpeta.mkdir(parents=True, exist_ok=True)
    entrada = yaml.safe_dump([{"texto": texto.strip(), "accion": accion}], allow_unicode=True,
                             sort_keys=False, width=1000)
    with open(carpeta / archivo, "a", encoding="utf-8", newline="\n") as f:
        f.write(entrada)


def guardar_aprendido(carpeta: Path, texto: str, accion: str) -> bool:
    """Como guardar_correccion, pero sin repetir frases ya aprendidas o corregidas."""
    def clave(t: str) -> str:
        return normalizar(t).strip(" .,;:!?¿¡…")
    conocidas = leer_aprendidos(carpeta) + leer_correcciones(carpeta)
    if not clave(texto) or any(clave(c["texto"]) == clave(texto) for c in conocidas):
        return False
    guardar_correccion(carpeta, texto, accion, ARCHIVO_APRENDIDOS)
    return True


def unir(ejemplos: dict[str, list[str]], correcciones: list[dict[str, str]],
         acciones_validas: list[str], aprendidos: list[dict[str, str]] | None = None
         ) -> tuple[list[str], list[str]]:
    """Devuelve (textos, etiquetas) sin duplicados, listos para entrenar.
    Orden: ejemplos, aprendidos de la IA, correcciones del usuario (la última gana)."""
    validas = set(acciones_de_texto(acciones_validas))
    por_texto: dict[str, tuple[str, str]] = {}
    fuentes = [(t, a) for a, textos in ejemplos.items() for t in textos]
    fuentes += [(c["texto"], c["accion"]) for c in (aprendidos or [])]
    fuentes += [(c["texto"], c["accion"]) for c in correcciones]
    for texto, accion in fuentes:
        if accion in validas and texto.strip():
            por_texto[normalizar(texto)] = (texto.strip(), accion)
    textos = [t for t, _ in por_texto.values()]
    etiquetas = [a for _, a in por_texto.values()]
    return textos, etiquetas
