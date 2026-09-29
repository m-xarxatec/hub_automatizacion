"""Referencias visuales: fotos sueltas y referencias de personaje.

"esta imagen quiero que sea referencia para Zamael" ->
  1. busca la ficha de Zamael (nombre o alias, sin distinguir acentos; ver fichas_de)
  2. copia la imagen a Referencias/ con nombre único
  3. la incrusta en la ficha bajo "## Referencias visuales" (la sección se crea si no está)
"""

from __future__ import annotations

from pathlib import Path

from ..boveda import escritor
from ..boveda.proyectos import Boveda

SECCION = "## Referencias visuales"


def _clave(texto: str) -> str:
    return escritor.sin_acentos(texto).casefold().strip()


def carpeta_personajes(boveda: Boveda, proyecto: str) -> Path:
    """Dónde van las fichas nuevas: Historia/Personajes si el proyecto ya la tiene (proyectos
    creados antes del 2026-09-30); si no, la de config.yaml (boveda.personajes)."""
    base = boveda.carpeta_proyectos / proyecto
    anterior = base / "Historia" / "Personajes"
    return anterior if anterior.is_dir() else base / boveda.cfg.get("personajes", "Personajes")


def fichas_de(boveda: Boveda, proyecto: str) -> list[Path]:
    """Fichas del proyecto: las notas de la carpeta de personajes y cualquier nota con
    `tipo: personaje` (así cuentan las que el redactor o el usuario pongan en otra carpeta)."""
    base = boveda.carpeta_proyectos / proyecto
    if not base.is_dir():
        return []
    carpeta = carpeta_personajes(boveda, proyecto)
    return sorted(n for n in base.rglob("*.md") if not n.name.startswith(".")
                  and (n.parent == carpeta or escritor.leer_frontmatter(n).get("tipo") == "personaje"))


def nombres_de(ficha: Path) -> list[str]:
    """Nombre del archivo, `nombre` y alias del frontmatter."""
    meta = escritor.leer_frontmatter(ficha)
    alias = meta.get("aliases") or []
    if isinstance(alias, str):
        alias = [alias]
    return [n for n in [ficha.stem, str(meta.get("nombre") or "")] + [str(a) for a in alias] if n.strip()]


def buscar_personaje(boveda: Boveda, nombre: str, proyecto: str | None = None) -> tuple[str, Path] | None:
    """Busca en el proyecto indicado o, si no hay, en todos los proyectos."""
    buscado = _clave(nombre)
    proyectos = [proyecto] if proyecto else boveda.listar_proyectos()
    encontrados = [(p, nota) for p in proyectos for nota in fichas_de(boveda, p)
                   if any(_clave(n) == buscado for n in nombres_de(nota))]
    return encontrados[0] if len(encontrados) == 1 else None


def crear_personaje(boveda: Boveda, proyecto: str, nombre: str, descripcion: str = "") -> Path:
    """Ficha con lo que se sabe del personaje y nada más: las secciones ("## Notas",
    "## Referencias visuales"…) aparecen cuando hay algo que poner en ellas."""
    visible = escritor.nombre_carpeta(nombre).title() if nombre.islower() else escritor.nombre_carpeta(nombre)
    ruta = carpeta_personajes(boveda, proyecto) / f"{visible}.md"
    if ruta.exists():
        return ruta
    contenido = escritor.con_frontmatter(
        {"tipo": "personaje", "proyecto": proyecto, "nombre": visible, "aliases": []},
        f"# {visible}\n" + (f"\n{descripcion.strip()}\n" if descripcion.strip() else ""),
    )
    escritor.escribir_atomico(ruta, contenido)
    return ruta


def guardar_imagen(boveda: Boveda, proyecto: str | None, datos: bytes, extension: str,
                   descripcion: str) -> Path:
    carpeta = (boveda.carpeta_proyectos / proyecto / "Referencias") if proyecto else boveda.bandeja
    titulo = descripcion.strip() or "referencia"
    ruta = escritor.ruta_unica(carpeta, titulo, extension.lower(), boveda.ahora())
    return escritor.escribir_atomico(ruta, datos)


def nota_de_referencia(boveda: Boveda, proyecto: str | None, imagen: Path, descripcion: str,
                       origen: str) -> Path:
    meta = {"tipo": "referencia", "proyecto": proyecto,
            "fecha": boveda.ahora().strftime("%Y-%m-%dT%H:%M"), "origen": origen,
            "imagen": imagen.name}
    cuerpo = f"# Referencia\n\n![[{imagen.name}]]\n\n{descripcion.strip()}\n"
    ruta = imagen.with_suffix(".md")
    return escritor.escribir_atomico(ruta, escritor.con_frontmatter(meta, cuerpo))


def insertar_en_seccion(nota: Path, seccion: str, linea: str, parrafo: bool = False) -> None:
    """Agrega una línea al final de una sección ("## …") sin tocar el resto.
    Si la sección no existe, se crea al final del archivo. `parrafo`: con una línea en blanco
    antes, para que un párrafo no se pegue al anterior (las viñetas van seguidas)."""
    lineas = nota.read_text(encoding="utf-8").rstrip("\n").split("\n")
    try:
        inicio = next(i for i, l in enumerate(lineas) if l.strip() == seccion)
    except StopIteration:
        lineas += ["", seccion, "", linea]
    else:
        fin = next((i for i in range(inicio + 1, len(lineas)) if lineas[i].startswith("## ")),
                   len(lineas))
        while fin > inicio + 1 and not lineas[fin - 1].strip():
            fin -= 1
        lineas[fin:fin] = ["", linea] if fin == inicio + 1 or parrafo else [linea]
    escritor.escribir_atomico(nota, "\n".join(lineas) + "\n")


def insertar_en_personaje(nota: Path, imagen: Path) -> None:
    """Agrega ![[imagen]] al final de la sección de referencias, sin tocar el resto."""
    incrustar = f"![[{imagen.name}]]"
    if incrustar in nota.read_text(encoding="utf-8"):
        return
    insertar_en_seccion(nota, SECCION, incrustar)
