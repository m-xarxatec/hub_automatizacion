"""Conflictos de Syncthing en la bóveda (pedido del usuario el 2026-09-30).

Syncthing no mezcla contenidos. Si un archivo cambió en dos equipos antes de sincronizarse, conserva
con su nombre la versión modificada más recientemente y renombra la otra a
`nombre.sync-conflict-AAAAMMDD-HHMMSS-EQUIPO.ext`, que viaja a todos los equipos como un archivo más.
Con el bot agregando a archivos existentes (Historia.md, fichas, tareas.md, el diario) puede pasar si el
usuario edita el mismo archivo en el móvil sin conexión.

Aquí se detectan esas copias, se comparan con el archivo actual y se resuelven cuando el usuario elige
(botones en el bot; decisión 6: el bot no borra ni reescribe por su cuenta):
  - unir: al archivo actual se le agregan, en su lugar, las líneas que solo estaban en la copia (si un
    mismo fragmento cambió en las dos, quedan ambas variantes para revisarlas: primero la de la copia,
    que es la más vieja, y debajo la actual) y se borra la copia;
  - actual: se borra la copia;
  - copia: la copia pasa a ser el archivo (sirve también para restaurar uno borrado).
Antes de tocar nada, las dos versiones se copian a datos/conflictos/<fecha-hora>/ (fuera de la bóveda).
El latido (_hub/servidor*.json) es del bot: su copia de conflicto se borra sin preguntar.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import escritor

PATRON = re.compile(r"^(?P<base>.+)\.sync-conflict-(?P<fecha>\d{8})-(?P<hora>\d{6})-(?P<equipo>[A-Z0-9]{7})"
                    r"(?P<ext>\.[^.]*)?$")
# Carpetas de Syncthing y de Obsidian que no son contenido.
IGNORAR = {".stversions", ".stfolder", ".trash", ".git"}
# Se pueden unir línea a línea sin romper el formato (un JSON unido así quedaría inválido).
UNIBLES = {".md", ".txt"}
MAX_LINEAS_MUESTRA = 5


@dataclass
class Conflicto:
    copia: Path
    original: Path
    fecha: datetime
    equipo: str

    @property
    def unible(self) -> bool:
        return self.original.suffix.casefold() in UNIBLES

    def interno(self, raiz: Path, interna: str = "_hub") -> bool:
        """Copia del latido: la escribe el bot cada minuto, no tiene nada del usuario."""
        rel = self.original.relative_to(raiz)
        return rel.parts[0] == interna and rel.name.startswith("servidor")


@dataclass
class Analisis:
    sugerencia: str                 # "unir" | "actual" | "copia"
    motivo: str                     # por qué, en una frase para el usuario
    solo_copia: list[str] = field(default_factory=list)
    solo_actual: list[str] = field(default_factory=list)
    ambos_cambiaron: int = 0        # fragmentos distintos en las dos: al unir quedan las dos variantes
    unido: str | None = None        # resultado de unir (solo texto)
    acciones: tuple[str, ...] = ("actual", "copia")


def leer_nombre(ruta: Path) -> Conflicto | None:
    m = PATRON.match(ruta.name)
    if not m:
        return None
    try:
        fecha = datetime.strptime(m["fecha"] + m["hora"], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return Conflicto(ruta, ruta.with_name(m["base"] + (m["ext"] or "")), fecha, m["equipo"])


def buscar(raiz: Path) -> list[Conflicto]:
    """Copias de conflicto de la bóveda, de la más vieja a la más nueva."""
    hallados = []
    for carpeta, subcarpetas, archivos in os.walk(raiz):
        subcarpetas[:] = [s for s in subcarpetas if s not in IGNORAR]
        for nombre in archivos:
            if ".sync-conflict-" in nombre and not nombre.startswith("."):
                c = leer_nombre(Path(carpeta) / nombre)
                if c:
                    hallados.append(c)
    return sorted(hallados, key=lambda c: (c.fecha, str(c.copia)))


def _partir(texto: str) -> tuple[str, str]:
    """(frontmatter con sus ---, cuerpo)."""
    if texto.startswith("---\n"):
        cierre = texto.find("\n---", 4)
        if cierre != -1:
            fin = texto.find("\n", cierre + 4)
            fin = len(texto) if fin == -1 else fin + 1
            return texto[:fin], texto[fin:]
    return "", texto


def _con_contenido(lineas: list[str]) -> list[str]:
    return [l.strip() for l in lineas if l.strip()]


def unir(actual: str, copia: str) -> tuple[str, list[str], list[str], int]:
    """(texto unido, líneas solo en la copia, solo en la actual, fragmentos que cambiaron en las dos).
    Base: la actual. Lo que solo está en la copia se inserta donde estaba; nada se quita."""
    fm_a, cuerpo_a = _partir(actual)
    fm_c, cuerpo_c = _partir(copia)
    a, c = cuerpo_a.splitlines(), cuerpo_c.splitlines()
    salida: list[str] = []
    solo_a: list[str] = []
    solo_c: list[str] = []
    ambos = 0
    for etiqueta, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, c, autojunk=False).get_opcodes():
        if etiqueta == "equal":
            salida += a[i1:i2]
        elif etiqueta == "delete":
            salida += a[i1:i2]
            solo_a += _con_contenido(a[i1:i2])
        elif etiqueta == "insert":
            salida += c[j1:j2]
            solo_c += _con_contenido(c[j1:j2])
        else:   # replace: el mismo lugar cambió en las dos; sin la versión común no se sabe cuál es la buena.
            # Quedan las dos en orden cronológico: la copia es la más vieja (Syncthing aparta esa).
            salida += c[j1:j2] + a[i1:i2]
            solo_a += _con_contenido(a[i1:i2])
            solo_c += _con_contenido(c[j1:j2])
            if _con_contenido(a[i1:i2]) and _con_contenido(c[j1:j2]):
                ambos += 1
    unido = (fm_a or fm_c) + "\n".join(salida)
    return (unido + "\n" if unido and not unido.endswith("\n") else unido), solo_c, solo_a, ambos


def analizar(c: Conflicto) -> Analisis:
    if not c.original.exists():
        return Analisis("copia", "El archivo original ya no existe (se borró en otro equipo): la copia es "
                                 "lo único que queda. Sugerencia: restaurarla.", acciones=("copia", "actual"))
    if not c.unible:
        iguales = c.original.read_bytes() == c.copia.read_bytes()
        return Analisis("actual", "Las dos versiones son idénticas." if iguales else
                        "No es una nota de texto, así que no se puede unir. Syncthing dejó como actual la "
                        "más reciente.", acciones=("actual", "copia"))
    actual = c.original.read_text(encoding="utf-8", errors="replace")
    copia = c.copia.read_text(encoding="utf-8", errors="replace")
    unido, solo_c, solo_a, ambos = unir(actual, copia)
    if not solo_c:
        return Analisis("actual", "La copia no tiene nada que no esté en la actual: basta con borrarla.",
                        solo_c, solo_a, ambos, unido, ("actual", "unir", "copia"))
    if not solo_a:
        motivo = (f"La copia tiene todo lo de la actual y {_n(len(solo_c), 'línea')} más: al unir quedan "
                  "todas.")
    else:
        motivo = (f"Cada versión tiene algo propio ({_n(len(solo_c), 'línea')} solo en la copia, "
                  f"{len(solo_a)} solo en la actual): al unir no se pierde nada.")
    return Analisis("unir", motivo, solo_c, solo_a, ambos, unido, ("unir", "actual", "copia"))


def _n(n: int, palabra: str) -> str:
    return f"{n} {palabra}" + ("" if n == 1 else "s")


def resolver(c: Conflicto, accion: str, respaldos: Path, ahora: datetime) -> Path | None:
    """Aplica la elección del usuario. Antes copia las dos versiones a `respaldos/<fecha-hora>/`
    (devuelve esa carpeta; None si ya no había nada que resolver)."""
    if not c.copia.exists():
        return None
    carpeta = respaldos / ahora.strftime("%Y%m%d-%H%M%S")
    carpeta.mkdir(parents=True, exist_ok=True)
    if c.original.exists():
        shutil.copy2(c.original, carpeta / f"actual-{c.original.name}")
    shutil.copy2(c.copia, carpeta / c.copia.name)
    if accion == "unir":
        if not c.unible or not c.original.exists():
            raise ValueError("Este archivo no se puede unir línea a línea.")
        escritor.escribir_atomico(c.original, analizar(c).unido or "")   # se recalcula: pudo cambiar
        c.copia.unlink()
    elif accion == "actual":
        c.copia.unlink()
    elif accion == "copia":
        os.replace(c.copia, c.original)
    else:
        raise ValueError(f"Acción desconocida: {accion}")
    return carpeta


class Vigilante:
    """Recuerda qué copias vio y de cuáles avisó. Solo avisa de las que siguen ahí en la revisión
    siguiente: una recién creada puede estar a medio copiar por Syncthing."""

    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.vistas: set[Path] = set()
        self.avisadas: set[Path] = set()

    def revisar(self) -> list[Conflicto]:
        actuales = {c.copia: c for c in buscar(self.raiz)}
        nuevas = [c for ruta, c in actuales.items() if ruta in self.vistas and ruta not in self.avisadas]
        self.vistas = set(actuales)
        self.avisadas &= self.vistas   # olvidar las resueltas: si vuelven a aparecer, se avisa de nuevo
        return nuevas

    def avisada(self, c: Conflicto) -> None:
        self.avisadas.add(c.copia)
