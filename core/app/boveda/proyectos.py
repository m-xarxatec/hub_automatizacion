"""Estructura de la bóveda: bandeja, diario y proyectos."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import escritor

STIGNORE = """// Generado por hub-creativo. No sincronizar estado de la interfaz ni temporales.
// Con "*" también se ignoran sus copias .sync-conflict (móvil y tablet escriben cada uno el suyo).
.obsidian/workspace.*
.obsidian/workspace-mobile*
.trash/
*.tmp
"""


def _clave(texto: str) -> str:
    return escritor.sin_acentos(texto).casefold().strip()


class Boveda:
    def __init__(self, raiz: Path, config: dict[str, Any], zona: str = "Europe/Madrid"):
        self.raiz = Path(raiz)
        self.cfg = config["boveda"]
        self.zona = ZoneInfo(zona)

    # --- rutas ------------------------------------------------------------
    @property
    def bandeja(self) -> Path:
        return self.raiz / self.cfg["bandeja"]

    @property
    def carpeta_proyectos(self) -> Path:
        return self.raiz / self.cfg["proyectos"]

    @property
    def interna(self) -> Path:
        return self.raiz / self.cfg["interna"]

    def ahora(self) -> datetime:
        return datetime.now(self.zona)

    # --- base ---------------------------------------------------------------
    def asegurar_base(self) -> None:
        for carpeta in (self.bandeja, self.raiz / self.cfg["diario"], self.carpeta_proyectos,
                        self.interna / "plantillas"):
            carpeta.mkdir(parents=True, exist_ok=True)
        stignore = self.raiz / ".stignore"
        if not stignore.exists():
            escritor.escribir_atomico(stignore, STIGNORE)

    # --- proyectos ------------------------------------------------------------
    def listar_proyectos(self) -> list[str]:
        if not self.carpeta_proyectos.exists():
            return []
        return sorted(
            (p.name for p in self.carpeta_proyectos.iterdir()
             if p.is_dir() and not p.name.startswith(".")),
            key=str.casefold,
        )

    def buscar_proyecto(self, texto: str) -> str | None:
        """Coincidencia por nombre o alias, sin distinguir mayúsculas ni acentos."""
        buscado = _clave(texto)
        if not buscado:
            return None
        for nombre in self.listar_proyectos():
            if _clave(nombre) == buscado:
                return nombre
            meta = escritor.leer_frontmatter(self.carpeta_proyectos / nombre / "_proyecto.md")
            alias = meta.get("aliases") or []
            if isinstance(alias, str):
                alias = [alias]
            if any(_clave(str(a)) == buscado for a in alias):
                return nombre
        return None

    def crear_proyecto(self, nombre: str, descripcion: str = "") -> str:
        """Solo la carpeta y su índice (_proyecto.md, con los alias). Nada de esqueleto: las
        carpetas y archivos aparecen cuando hay algo que guardar en ellos (decidido el 2026-09-30)."""
        visible = escritor.nombre_carpeta(nombre)
        existente = self.buscar_proyecto(visible)
        if existente:
            return existente
        carpeta = self.carpeta_proyectos / visible
        fecha = self.ahora().strftime("%Y-%m-%d")
        cuerpo = f"# {visible}\n" + (f"\n{descripcion.strip()}\n" if descripcion.strip() else "")
        indice = escritor.con_frontmatter({"tipo": "proyecto", "creado": fecha, "aliases": []}, cuerpo)
        escritor.escribir_atomico(carpeta / "_proyecto.md", indice)
        return visible

    # --- notas y tareas -------------------------------------------------------
    def carpeta_para(self, proyecto: str | None, tipo: str) -> Path:
        if not proyecto:
            return self.bandeja
        sub = self.cfg["destino_por_tipo"].get(tipo, "Ideas")
        return self.carpeta_proyectos / proyecto / sub

    def archivo_notas(self, proyecto: str | None, tipo: str) -> Path:
        """Archivo donde se acumulan las notas de un tipo: Proyectos/X/Ideas.md, Historia.md…"""
        if not proyecto:
            return self.bandeja / "Notas.md"
        sub = self.cfg["destino_por_tipo"].get(tipo, "Ideas")
        return self.carpeta_proyectos / proyecto / f"{sub}.md"

    def guardar_nota(self, texto: str, proyecto: str | None = None, tipo: str = "general",
                     origen: str = "telegram", aparte: bool = False, titulo: str | None = None) -> Path:
        """Por defecto agrega la nota al final del archivo de su tipo; con aparte=True crea
        un archivo propio con nombre único (solo cuando el usuario lo pide)."""
        texto = texto.strip()
        if not texto:
            raise ValueError("La nota está vacía")
        ahora = self.ahora()
        if aparte:
            return self._nota_aparte(texto, proyecto, tipo, origen, ahora, titulo)
        ruta = self.archivo_notas(proyecto, tipo)
        nombre = f"{ruta.stem} de {proyecto}" if proyecto else "Notas sin proyecto"
        cabecera = escritor.con_frontmatter({"tipo": "notas", "proyecto": proyecto}, f"# {nombre}\n")
        encabezado = self._encabezado(ahora, origen)
        escritor.agregar_al_final(ruta, f"\n## {encabezado}\n\n{texto}", encabezado=cabecera)
        self.registrar_diario(f"Nota en [[{self.enlace(ruta)}#{encabezado}|{nombre}]]")
        return ruta

    @staticmethod
    def _encabezado(ahora: datetime, origen: str) -> str:
        return f"{ahora.strftime('%Y-%m-%d %H:%M')} · {'voz' if origen == 'voz' else 'texto'}"

    def agregar_a_archivo(self, ruta: Path, texto: str, origen: str = "telegram") -> Path:
        """Agrega una nota al final de un archivo que ya existe y que el usuario nombró
        ("anota en referencia elfa que…"). Solo agrega: no toca lo que ya estaba escrito."""
        texto = texto.strip()
        if not texto:
            raise ValueError("La nota está vacía")
        if not ruta.is_file() or not ruta.resolve().is_relative_to(self.raiz.resolve()):
            raise ValueError(f"No encuentro el archivo {ruta.name} en la bóveda")
        encabezado = self._encabezado(self.ahora(), origen)
        escritor.agregar_al_final(ruta, f"\n## {encabezado}\n\n{texto}")
        self.registrar_diario(f"Nota en [[{self.enlace(ruta)}#{encabezado}|{ruta.stem}]]")
        return ruta

    def _nota_aparte(self, texto: str, proyecto: str | None, tipo: str, origen: str,
                     ahora: datetime, titulo: str | None = None) -> Path:
        primera = texto.splitlines()[0]
        titulo = (titulo or "").strip() or primera[:80] + ("…" if len(primera) > 80 else "")
        meta = {"tipo": tipo, "proyecto": proyecto, "fecha": ahora.strftime("%Y-%m-%dT%H:%M"),
                "origen": origen, "tags": []}
        carpeta = self.carpeta_proyectos / proyecto if proyecto else self.bandeja
        ruta = escritor.ruta_unica(carpeta, titulo, ".md", ahora)
        escritor.escribir_atomico(ruta, escritor.con_frontmatter(meta, f"# {titulo}\n\n{texto}\n"))
        self.registrar_diario(f"Nota [[{ruta.stem}]]" + (f" en {proyecto}" if proyecto else ""))
        return ruta

    def enlace(self, ruta: Path) -> str:
        """Ruta sin extensión para enlaces de Obsidian: evita ambigüedad entre proyectos
        (todos tienen su Ideas.md)."""
        return ruta.relative_to(self.raiz).with_suffix("").as_posix()

    def ruta_tareas(self, proyecto: str | None) -> Path:
        if proyecto:
            return self.carpeta_proyectos / proyecto / "tareas.md"
        return self.bandeja / "tareas.md"

    def agregar_tarea(self, texto: str, proyecto: str | None = None) -> Path:
        texto = " ".join(texto.split())
        if not texto:
            raise ValueError("La tarea está vacía")
        ruta = self.ruta_tareas(proyecto)
        titulo = f"# Tareas de {proyecto}\n\n" if proyecto else "# Tareas sin proyecto\n\n"
        escritor.agregar_al_final(ruta, f"- [ ] {texto}", encabezado=titulo)
        return ruta

    def tareas_abiertas(self, proyecto: str | None) -> list[str]:
        ruta = self.ruta_tareas(proyecto)
        if not ruta.exists():
            return []
        return [
            linea.strip()[6:]
            for linea in ruta.read_text(encoding="utf-8").splitlines()
            if linea.strip().startswith("- [ ] ")
        ]

    def registrar_diario(self, linea: str) -> Path:
        ahora = self.ahora()
        ruta = self.raiz / self.cfg["diario"] / f"{ahora.strftime('%Y-%m-%d')}.md"
        encabezado = f"# {ahora.strftime('%Y-%m-%d')}\n\n"
        return escritor.agregar_al_final(ruta, f"- {ahora.strftime('%H:%M')} {linea}",
                                         encabezado=encabezado)
