"""Generación de imágenes para ideas y referencias (nunca para las páginas del cómic).

1. Si el LLM local está activo, convierte la idea en un prompt en inglés (hoy dormido:
   se usa la idea tal cual).
2. Se pide la imagen a la cadena de config.yaml (MVP: solo chatgpt; cloudflare y tensorart
   están desactivados hasta después del MVP).
3. Se guarda la imagen y su nota hermana (mismo nombre, .md) en Proyectos/<p>/Imagenes/
   o en 00-Bandeja, y se anota en el diario.
Si todos los proveedores fallan, la cadena lanza SinProveedores y el bot avisa.

Nombres simples: "elfa1", "elfa2", "mercenario1"… Sin modelos: se quitan el pedido, el estilo
y los artículos, y queda la primera palabra con sentido. Si la idea nombra a un personaje con
ficha, se usa su nombre. "La imagen que se acaba de crear será Aeli" la renombra ("aeli1").
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..boveda import escritor
from ..boveda.proyectos import Boveda
from ..proveedores.cadena import CadenaImagenes
from ..proveedores.ollama import Ollama
from . import personajes

SISTEMA = (
    "Conviertes la idea de un autor de webtoon en un prompt en inglés para un generador de "
    "imágenes: sujeto, entorno, estilo, iluminación y encuadre, en una sola frase de máximo "
    "60 palabras. Responde solo con JSON."
)
ESQUEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}

# Palabras que no nombran lo que se dibuja (en minúsculas y sin acentos).
_RELLENO = set("""muy bien bueno ok vale oye entonces ahora vas vamos a quiero que me gustaria
puedes podrias necesito por favor crea crear crees creo creame genera generar generes generame
dibuja dibujar dibujes dibujame haz hazme hacer hagas imagen ilustracion dibujo boceto render
retrato foto referencia la el lo los las un una unos unas mismo misma otro otra nuevo nueva
este esta ese esa hermosa hermoso bonita bonito linda lindo gran grande""".split())
_ESTILOS = {"anime", "manga", "realista", "acuarela", "chibi", "pixel", "cartoon", "comic", "webtoon"}
_INTRO_ESTILO = {"estilo", "tipo"}   # "en estilo acuarela": la palabra siguiente es el estilo
# Tras una palabra genérica, estas cortan la búsqueda: "una chica en la playa" -> "chica".
_CORTES = {"con", "en", "de", "del", "que", "pero", "y", "sobre", "para", "mientras"}
_GENERICOS = {"chica", "chico", "mujer", "hombre", "persona", "personaje", "nina", "nino", "joven"}


def referente(idea: str) -> str:
    """'Crea una chica anime elfa pálida' -> 'elfa'; 'un templo de noche' -> 'templo'."""
    generico, saltar = None, False
    for palabra in re.findall(r"[a-z0-9]+", escritor.sin_acentos(idea).lower()):
        if saltar:
            saltar = False
        elif palabra in _INTRO_ESTILO:
            saltar = True
        elif palabra in _CORTES:
            if generico:
                break
        elif palabra in _GENERICOS:
            generico = generico or palabra
        elif palabra not in _RELLENO and palabra not in _ESTILOS and len(palabra) > 2 \
                and not palabra.isdigit():
            return palabra
    return generico or "imagen"


@dataclass
class Resultado:
    imagen: Path
    nota: Path
    proveedor: str
    modelo: str
    prompt: str


class GeneradorImagenes:
    def __init__(self, boveda: Boveda, cadena: CadenaImagenes, llm: Ollama | None = None):
        self.boveda = boveda
        self.cadena = cadena
        self.llm = llm

    async def mejorar_prompt(self, idea: str) -> str:
        """Sin LLM, o si responde mal, la idea tal cual (gpt-image-2 entiende español)."""
        idea = idea.strip()
        if self.llm:
            datos = await self.llm.chat_json(SISTEMA, idea, ESQUEMA)
            prompt = str((datos or {}).get("prompt", "")).strip()
            if prompt:
                return prompt
        return idea

    def carpeta(self, proyecto: str | None) -> Path:
        return (self.boveda.carpeta_proyectos / proyecto / "Imagenes") if proyecto else self.boveda.bandeja

    def nombre(self, idea: str, proyecto: str | None) -> str:
        """Personaje con ficha nombrado en la idea o, si no, la palabra que la resume."""
        ficha = personajes.mencionado(self.boveda, proyecto, idea) if proyecto else None
        return ficha.stem if ficha else referente(idea)

    @staticmethod
    def siguiente(carpeta: Path, nombre: str) -> str:
        """'elfa' -> 'elfa3' si ya hay elfa1 y elfa2 (sin distinguir mayúsculas, como Windows)."""
        base = escritor.slug(nombre)
        patron = re.compile(rf"^{re.escape(base)}(\d+)$", re.IGNORECASE)
        usados = [int(m.group(1)) for p in carpeta.glob("*") if (m := patron.match(p.stem))] \
            if carpeta.exists() else []
        return f"{base}{max(usados, default=0) + 1}"

    async def crear(self, idea: str, proyecto: str | None, prompt: str | None = None,
                    nombre: str | None = None) -> Resultado:
        """`prompt` y `nombre` los da el intérprete (GPT) si entendió el pedido; si no, se deducen."""
        prompt = prompt or await self.mejorar_prompt(idea)
        img = await self.cadena.generar(prompt)
        carpeta = self.carpeta(proyecto)
        nombre = self.siguiente(carpeta, nombre or self.nombre(idea, proyecto))
        ruta_img, ruta_nota = carpeta / f"{nombre}{img.extension}", carpeta / f"{nombre}.md"
        escritor.escribir_atomico(ruta_img, img.datos)
        meta = {
            "tipo": "imagen_ia",
            "proyecto": proyecto,
            "fecha": self.boveda.ahora().strftime("%Y-%m-%dT%H:%M"),
            "proveedor": img.proveedor,
            "modelo": img.modelo,
            "imagen": ruta_img.name,
        }
        cuerpo = (f"# {nombre}\n\n![[{ruta_img.name}]]\n\n"
                  f"**Idea:** {idea.strip()}\n\n**Prompt:** {prompt}\n")
        escritor.escribir_atomico(ruta_nota, escritor.con_frontmatter(meta, cuerpo))
        self.boveda.registrar_diario(f"Imagen [[{ruta_nota.stem}]] ({img.proveedor})"
                                     + (f" en {proyecto}" if proyecto else ""))
        return Resultado(ruta_img, ruta_nota, img.proveedor, img.modelo, prompt)

    def ultima(self, proyecto: str | None) -> Path | None:
        """Nota de la imagen generada más reciente del proyecto (o de la bandeja)."""
        carpeta = self.carpeta(proyecto)
        notas = [n for n in carpeta.glob("*.md")
                 if escritor.leer_frontmatter(n).get("tipo") == "imagen_ia"] if carpeta.exists() else []
        return max(notas, key=lambda n: n.stat().st_mtime, default=None)

    def renombrar(self, nota: Path, nombre: str) -> Path:
        """Da a la imagen y a su nota el nombre pedido ("aeli1"). Devuelve la nota nueva.
        Solo toca archivos que creó el bot; en el diario se agrega una línea, no se reescribe."""
        base = escritor.slug(nombre)
        if re.fullmatch(rf"{re.escape(base)}\d+", nota.stem, re.IGNORECASE):
            return nota   # ya se llama así
        imagen = nota.with_name(str(escritor.leer_frontmatter(nota).get("imagen") or ""))
        if not imagen.is_file():
            raise FileNotFoundError(f"no encuentro la imagen de {nota.name}")
        nuevo = self.siguiente(nota.parent, base)
        nueva_img, nueva_nota = imagen.with_name(nuevo + imagen.suffix), nota.with_name(nuevo + ".md")
        texto = nota.read_text(encoding="utf-8").replace(imagen.name, nueva_img.name)
        texto = texto.replace(f"\n# {nota.stem}\n", f"\n# {nuevo}\n", 1)
        # Primero la nota nueva, luego la imagen y al final se quita la nota vieja:
        # si algo falla a medias, no se pierde nada.
        escritor.escribir_atomico(nueva_nota, texto)
        os.replace(imagen, nueva_img)
        nota.unlink()
        self.boveda.registrar_diario(f"Imagen {nota.stem} renombrada a [[{nuevo}]]")
        return nueva_nota

    async def diagnosticar(self) -> str:
        lineas = [f"- {nombre}: {estado}" for nombre, estado in await self.cadena.diagnosticar()]
        return "\n".join(lineas) or "- no hay proveedores activos en config.yaml"
