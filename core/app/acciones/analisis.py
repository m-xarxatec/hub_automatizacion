"""Modo análisis profundo (decisión 4, día 5).

1. `preparar`: junta las notas del proyecto activo (todo menos Analisis/) hasta el tope de
   tokens de config.yaml. Si no caben todas, van primero las que comparten palabras con el
   pedido; la que no cabe entera se recorta dejando su final (lo más reciente, porque las
   notas se agregan al final). Los tokens se estiman por caracteres: no se gasta nada.
2. El bot muestra notas y tokens estimados y un botón por modelo (el predeterminado de
   /modelo primero). Al elegir modelo, otros botones con el esfuerzo (nivel de razonamiento)
   que acepta ese modelo; el menor va primero (decisión 3). Nada se envía sin confirmación.
3. `analizar`: un único modelo, el elegido, por OpenClaw. Si falla, el bot explica el motivo
   y ofrece los otros modelos; nunca cambia de modelo por su cuenta.
4. `guardar`: archivo propio en Proyectos/<p>/Analisis/ y línea en el diario.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..boveda import escritor
from ..boveda.proyectos import Boveda
from ..proveedores.openclaw import Nivel, OpenClaw, Respuesta

# Estimación conservadora para español (los tokenizadores dan ~4 caracteres por token).
CARACTERES_POR_TOKEN = 3.5
# Si queda menos espacio que esto, no vale la pena mandar un trozo de nota.
MIN_TOKENS_RECORTE = 300
PREFERENCIA = "modelo_analisis"

SISTEMA = (
    "Eres editor de un webtoon y analizas las notas del autor según su pedido. Responde en "
    "español latinoamericano, en Markdown sencillo con títulos cortos: primero la conclusión en "
    "dos o tres frases y después el detalle (incoherencias, huecos, riesgos y sugerencias "
    "concretas). Básate solo en las notas y cita el archivo cuando te refieras a una. Si falta "
    "información para responder, dilo."
)

# Palabras que no ayudan a elegir notas (sin acentos, de 4 letras o más).
VACIAS = {
    "analiza", "analizar", "analisis", "revisa", "revisar", "evalua", "evaluar", "busca", "buscar",
    "crees", "seria", "viable", "tiene", "sentido", "encaja", "encajaria", "creible", "coherente",
    "coherencia", "notas", "nota", "proyecto", "para", "como", "esta", "este", "esto", "estos",
    "estas", "sobre", "entre", "cuando", "donde", "porque", "pero", "todo", "todos", "todas",
    "algo", "otra", "otro", "otros", "muy", "mucho", "demasiado", "demasiados", "sean", "mis",
    "que", "con", "del", "los", "las", "una", "unos", "unas", "desde", "hasta", "tan", "pronto",
}


# Esfuerzo (nivel de razonamiento) tal como lo nombra OpenClaw -> texto de los botones.
ESFUERZOS = {"off": "Sin razonamiento", "minimal": "Mínimo", "low": "Bajo", "medium": "Medio",
             "high": "Alto", "xhigh": "Muy alto", "max": "Máximo"}


@dataclass(frozen=True)
class Opcion:
    modelo: str
    nombre: str
    razonamiento: str       # esfuerzo por defecto: el menor que acepta el modelo (decisión 3)
    aislado: bool = False
    extra_tokens: int = 0   # prompt propio del programa (Claude Code agrega ~3.700)
    esfuerzos: tuple[str, ...] = ()   # los que acepta el modelo, de menor a mayor

    def nivel(self) -> Nivel:
        return Nivel(self.modelo, self.razonamiento, self.aislado)

    def con_esfuerzo(self, esfuerzo: str) -> Opcion:
        return replace(self, razonamiento=esfuerzo)

    def lista_esfuerzos(self) -> tuple[str, ...]:
        """Los permitidos; si config.yaml no los dice, solo el de por defecto."""
        return self.esfuerzos or (self.razonamiento,)


@dataclass(frozen=True)
class NotaIncluida:
    ruta: Path
    tokens: int
    recortada: bool = False


@dataclass
class Preparado:
    proyecto: str
    pedido: str
    notas: list[NotaIncluida]
    fuera: list[Path]      # no entraron por el tope
    contexto: str          # mensaje completo para el modelo
    tokens: int            # estimados: sistema + pedido + notas


def nombre_esfuerzo(opcion: Opcion) -> str:
    return ESFUERZOS.get(opcion.razonamiento, opcion.razonamiento).lower()


def estimar_tokens(texto: str) -> int:
    return math.ceil(len(texto) / CARACTERES_POR_TOKEN)


def ajustes(cfg: dict) -> dict[str, Any]:
    return cfg.get("proveedores", {}).get("analisis", {}) or {}


def opciones_desde_config(cfg: dict) -> list[Opcion]:
    """proveedores.analisis.opciones; ignora entradas sin modelo. Sin razonamiento: el menor de
    `esfuerzos` (o "low", el mínimo que aceptan los modelos grandes)."""
    opciones = []
    for o in ajustes(cfg).get("opciones") or []:
        if isinstance(o, dict) and o.get("modelo"):
            modelo = str(o["modelo"])
            esfuerzos = tuple(str(e) for e in o.get("esfuerzos") or [] if str(e) in ESFUERZOS)
            razonamiento = str(o.get("razonamiento") or (esfuerzos[0] if esfuerzos else "low"))
            opciones.append(Opcion(modelo, str(o.get("nombre") or modelo.split("/")[-1]), razonamiento,
                                   bool(o.get("aislado")), int(o.get("extra_tokens") or 0), esfuerzos))
    return opciones


def predeterminado(cfg: dict, preferido: str | None) -> Opcion | None:
    """El elegido con /modelo si sigue en la lista; si no, el recomendado; si no, el primero."""
    opciones = opciones_desde_config(cfg)
    for modelo in (preferido, ajustes(cfg).get("recomendado")):
        for o in opciones:
            if o.modelo == modelo:
                return o
    return opciones[0] if opciones else None


def ordenar(opciones: list[Opcion], primero: Opcion | None) -> list[Opcion]:
    """El predeterminado va primero; el resto conserva el orden de config.yaml."""
    if primero not in opciones:
        return list(opciones)
    return [primero] + [o for o in opciones if o != primero]


def palabras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-zñ0-9]{4,}", escritor.sin_acentos(texto).lower())
            if p not in VACIAS}


def _prioridad(relativa: Path) -> int:
    """A igual coincidencia: historia y personajes, ideas, producción y el resto."""
    raiz = relativa.parts[0].removesuffix(".md").lower()
    return {"historia": 0, "ideas": 1, "produccion": 2}.get(raiz, 3)


def preparar(boveda: Boveda, proyecto: str, pedido: str, tope_tokens: int = 20000) -> Preparado:
    carpeta = boveda.carpeta_proyectos / proyecto
    salida = boveda.carpeta_para(proyecto, "analisis")
    archivos = [p for p in carpeta.rglob("*.md")
                if not p.name.startswith(".") and salida not in p.parents] if carpeta.exists() else []
    claves = palabras(pedido)
    textos = {p: p.read_text(encoding="utf-8", errors="replace") for p in archivos}

    def coincidencias(p: Path) -> int:
        return len(claves & palabras(f"{p.relative_to(carpeta).as_posix()} {textos[p]}"))

    archivos.sort(key=lambda p: (-coincidencias(p), _prioridad(p.relative_to(carpeta)),
                                 -p.stat().st_mtime))
    encabezado = f"Pedido del autor: {pedido.strip()}\n\nNotas del proyecto {proyecto}:\n"
    restante = tope_tokens - estimar_tokens(SISTEMA) - estimar_tokens(encabezado)
    bloques: list[str] = []
    notas: list[NotaIncluida] = []
    fuera: list[Path] = []
    for p in archivos:
        relativa = p.relative_to(carpeta).as_posix()
        bloque = f"\n### {relativa}\n{textos[p].strip()}\n"
        tokens = estimar_tokens(bloque)
        recortada = False
        if tokens > restante:
            if restante < MIN_TOKENS_RECORTE:
                fuera.append(p)
                continue
            titulo = f"\n### {relativa} (recortada: solo el final)\n…"
            caben = int(restante * CARACTERES_POR_TOKEN) - len(titulo) - 2
            bloque = f"{titulo}{textos[p].strip()[-caben:]}\n"
            tokens, recortada = estimar_tokens(bloque), True
        bloques.append(bloque)
        notas.append(NotaIncluida(p, tokens, recortada))
        restante -= tokens
    contexto = encabezado + "".join(bloques)
    return Preparado(proyecto, pedido.strip(), notas, fuera, contexto,
                     estimar_tokens(SISTEMA) + estimar_tokens(contexto))


def miles(tokens: int) -> str:
    """1234 -> '1.234' (separador de miles en español)."""
    return f"{tokens:,}".replace(",", ".")


def etiqueta(opcion: Opcion, prep: Preparado, marcar: bool) -> str:
    total = prep.tokens + opcion.extra_tokens
    return f"{'✓ ' if marcar else ''}{opcion.nombre} · ~{miles(total)} tokens"


def resumen(prep: Preparado, carpeta: Path, minutos: int) -> str:
    """Texto de confirmación: qué notas entran (relativas a la carpeta del proyecto) y cuántos
    tokens se estiman."""
    nombres = [n.ruta.relative_to(carpeta).as_posix() + (" (recortada)" if n.recortada else "")
               for n in prep.notas]
    lista = ", ".join(nombres[:8]) + (f" y {len(nombres) - 8} más" if len(nombres) > 8 else "")
    lineas = [f"Análisis en {prep.proyecto}: «{prep.pedido}»",
              f"Notas ({len(prep.notas)}): {lista}"]
    if prep.fuera:
        lineas.append(f"Fuera por el tope de tokens: {len(prep.fuera)} nota(s)")
    lineas += [f"Tokens de entrada estimados: ~{miles(prep.tokens)} (en cada botón, el total con ese modelo).",
               f"¿Con qué modelo lo analizo? Los botones caducan en {minutos} minutos."]
    return "\n".join(lineas)


def resumen_hablado(prep: Preparado) -> str:
    """Versión corta para la voz (decisión 9): sin rutas ni listas."""
    mil = round(prep.tokens / 1000)
    tokens = {0: "menos de mil tokens", 1: "unos mil tokens"}.get(mil, f"unos {mil} mil tokens")
    notas = "una nota" if len(prep.notas) == 1 else f"{len(prep.notas)} notas"
    return f"Voy a analizar {notas} de {prep.proyecto}, {tokens}. Elige el modelo en los botones."


async def analizar(cliente: OpenClaw, opcion: Opcion, prep: Preparado, cfg: dict) -> Respuesta | None:
    a = ajustes(cfg)
    return await cliente.completar_con(opcion.nivel(), prep.contexto, SISTEMA,
                                       int(a.get("max_tokens_salida") or 2500),
                                       float(a.get("tiempo_max_s") or 300), funcion="analisis")


def guardar(boveda: Boveda, prep: Preparado, respuesta: Respuesta, opcion: Opcion) -> Path:
    """Archivo propio con nombre único (decisión 6) y enlaces a las notas analizadas."""
    ahora = boveda.ahora()
    primera = prep.pedido.splitlines()[0] if prep.pedido else "análisis"
    titulo = primera[:80] + ("…" if len(primera) > 80 else "")
    ruta = escritor.ruta_unica(boveda.carpeta_para(prep.proyecto, "analisis"), titulo, ".md", ahora)
    meta = {
        "tipo": "analisis",
        "proyecto": prep.proyecto,
        "fecha": ahora.strftime("%Y-%m-%dT%H:%M"),
        "modelo": respuesta.modelo,
        "esfuerzo": opcion.razonamiento,
        "pedido": prep.pedido,
        "tokens_entrada": respuesta.tokens_entrada or prep.tokens,
        "tokens_salida": respuesta.tokens_salida,
    }
    enlaces = ", ".join(f"[[{boveda.enlace(n.ruta)}|{n.ruta.stem}]]" for n in prep.notas)
    cuerpo = (f"# Análisis: {titulo}\n\n**Pedido:** {prep.pedido}\n\n"
              f"**Modelo:** {opcion.nombre} (esfuerzo {nombre_esfuerzo(opcion)})\n\n**Notas analizadas:** {enlaces}\n\n---\n\n"
              f"{respuesta.texto.strip()}\n")
    escritor.escribir_atomico(ruta, escritor.con_frontmatter(meta, cuerpo))
    boveda.registrar_diario(f"Análisis [[{ruta.stem}]] con {opcion.nombre} (esfuerzo "
                            f"{nombre_esfuerzo(opcion)}) en {prep.proyecto}")
    return ruta
