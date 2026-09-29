"""Redactor: decide qué escribir en la bóveda y dónde (decidido por el usuario el 2026-09-30).

El intérprete (router/interprete.py) dice QUÉ quiere el usuario. Cuando es guardar algo (una nota,
un personaje, "crea un archivo ideas y anota…"), el redactor recibe el mensaje y el contenido real
del proyecto y devuelve operaciones:
  - agregar: al final de un archivo existente o al final de una de sus secciones ("## Historia");
  - crear: un archivo o una ficha de personaje nueva, siempre con contenido (nunca esqueletos).
Un mensaje puede repartirse en varios archivos, con [[enlaces]] a los personajes. Si falta algo
esencial (el nombre del personaje que piden crear) pregunta en vez de escribir, y si lo nuevo
contradice lo escrito, avisa.

Lo que el modelo NO decide (lo impone el código):
  - Solo se agrega: nunca se reescribe ni se borra (decisión 6). "crear" sobre un archivo que ya
    existe pasa a "agregar"; "agregar" a uno que no existe, a "crear".
  - Las rutas quedan dentro del proyecto (o de 00-Bandeja si no hay proyecto), con nombres válidos
    en Windows. Imagenes/, Analisis/ y tareas.md son del bot y no se tocan.
  - Las fichas nuevas van a la carpeta de personajes y llevan `tipo: personaje`.
  - Cobertura: las palabras con contenido del mensaje deben aparecer en lo escrito. Si falta mucho,
    no se aplica nada y quien llama guarda el mensaje tal cual (ninguna idea se pierde).
Si el modelo no responde, quien llama guarda la nota por tipo (esquema anterior).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..boveda import escritor
from ..boveda.proyectos import Boveda
from ..proveedores.openclaw import Nivel, OpenClaw
from ..router.interprete import extraer_json
from . import referencias
from .analisis import CARACTERES_POR_TOKEN, estimar_tokens, palabras

log = logging.getLogger(__name__)

SISTEMA = """Eres el redactor de la bóveda de Obsidian de un autor de webtoon. Recibes JSON con su mensaje (a veces
voz transcrita con errores), el proyecto activo, sus archivos con su contenido, sus fichas de personaje y
lo último que hizo el asistente. Decides qué escribir y dónde.

1. Guarda TODO lo que dice: cada dato, nombre, lugar y matiz. Puedes ordenarlo, corregir errores evidentes
   de transcripción (usa la ortografía de los nombres que ya están escritos), quitar la orden ("anota
   que…", "crea un archivo…") y las muletillas, y redactarlo claro con su tono. No inventes nada ni opines.
2. Prefiere los archivos que ya existen y encajan. Un mensaje puede ir a varios lugares: lo que describe a
   un personaje con ficha va a su ficha (en la sección que corresponda, ya existente o nueva: "## Apariencia",
   "## Personalidad", "## Historia"…); la trama, los sucesos y las escenas, al archivo de historia (si no
   hay, créalo: "Historia.md"); el mundo y los lugares, a su archivo si lo hay. No copies el mismo texto en
   dos archivos: en el segundo, una frase corta con el enlace ("Perdona a [[Aely]]; ver [[Historia]].").
3. Crea un archivo solo si el autor lo pide ("crea un archivo…", "en un documento aparte"; respeta el
   nombre y la carpeta que diga) o si no hay ninguno donde encaje. Nombre corto ("Historia.md",
   "Mundo.md", "Capitulo 1.md") en la raíz del proyecto. Nunca crees archivos, carpetas ni secciones vacías.
4. Personaje nuevo con nombre (lo presentan o piden crearlo): crea su ficha con "personaje": true, solo con
   lo que se sabe de él: primero un párrafo sin encabezado con quién es (rol, oficio, edad, especie) y
   después secciones solo si tienen contenido. Si piden crear un personaje sin nombre, no escribas nada y
   pregunta cómo se llama. Si ya tiene ficha, agrega a esa ficha.
5. _proyecto.md es solo la descripción general del proyecto: premisa en pocas líneas, género, tono,
   formato. La trama y sus sucesos nunca van ahí, aunque sea el único archivo.
6. Si ultima_accion.accion es "pregunta", este mensaje probablemente la responde: combínalo con
   ultima_accion.mensaje y guarda los dos. Si el mensaje se refiere a algo anterior sin repetirlo ("anota
   esto", "guarda esa idea", "lo que me dijiste"), el contenido está en ultima_accion o en
   ultima_accion.anteriores (p. ej. la respuesta de una consulta): guárdalo completo, sin resumirlo.
7. Personajes con ficha mencionados en otro archivo: [[Nombre]] la primera vez en cada texto.
8. agregar con "seccion" vacía: al final del archivo, con "titulo" (3 a 6 palabras) para el bloque. Con
   "seccion" ("## Apariencia"): al final de esa sección (se crea si no existe), sin título. Markdown
   simple: párrafos o viñetas, sin encabezados de nivel 1.
9. avisos: si lo nuevo contradice lo escrito (especie, edad, parentesco…), explícalo en una frase. Igual
   guarda lo nuevo.
10. respuesta: una frase breve de lo que hiciste ("Anoté la escena en Historia y creé la ficha de Kael."),
   sin rutas.
11. Si no hay nada que guardar (es una pregunta o una charla), operaciones vacías y en "pregunta" qué
   quiere que haga.
Solo JSON: {"operaciones":[{"op":"agregar|crear","archivo":"ruta relativa .md","seccion":"","titulo":"",
"personaje":false,"texto":""}],"respuesta":"","pregunta":"","avisos":[]}"""

# Del bot: el redactor no escribe ahí (imágenes y análisis tienen su propio flujo; tareas, /tarea).
RESERVADAS = ("imagenes", "analisis")
ARCHIVOS_RESERVADOS = ("tareas.md",)
# Palabras de la orden, no del contenido: no cuentan para la cobertura.
ORDEN = {
    "anota", "anotar", "anotes", "apunta", "apuntar", "agrega", "agregar", "agregues", "añade", "anade",
    "crea", "crear", "creame", "guarda", "guardar", "escribe", "escribir", "quiero", "quisiera", "archivo",
    "documento", "ficha", "personaje", "llamado", "llamada", "llama", "dentro", "carpeta", "tambien",
    "ademas", "entonces", "bueno", "pues", "vale", "okay", "ahora", "aparte", "nuevo", "nueva", "idea",
    "ideas", "historia", "favor", "porfa", "podrias", "puedes", "hazme", "ponle", "ponlo", "pon",
}
UMBRAL_COBERTURA = 0.6
MIN_PALABRAS_COBERTURA = 4
MAX_OPERACIONES = 8


@dataclass
class Operacion:
    op: str                 # "agregar" | "crear"
    ruta: Path
    texto: str
    seccion: str = ""       # "## Apariencia" (agregar dentro de una sección)
    titulo: str = ""        # encabezado del bloque al agregar al final
    personaje: bool = False


@dataclass
class Plan:
    operaciones: list[Operacion]
    respuesta: str = ""
    pregunta: str = ""
    avisos: list[str] = field(default_factory=list)
    descartadas: int = 0     # operaciones inválidas que no se aplican (fuera del proyecto, vacías…)


class SinCobertura(ValueError):
    """Lo que propuso el modelo deja fuera demasiado del mensaje: no se aplica."""


# --- contexto ---------------------------------------------------------------------------
def base_de(boveda: Boveda, proyecto: str | None) -> Path:
    return boveda.carpeta_proyectos / proyecto if proyecto else boveda.bandeja


def _reservada(relativa: Path) -> bool:
    return (relativa.parts[0].casefold() in RESERVADAS
            or relativa.name.casefold() in ARCHIVOS_RESERVADOS)


def archivos_escribibles(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md")
                  if not any(parte.startswith(".") for parte in p.relative_to(base).parts)
                  and not _reservada(p.relative_to(base)))


def contexto(boveda: Boveda, proyecto: str | None, mensaje: str, tope_tokens: int) -> dict:
    """Archivos del proyecto con su contenido, los más relacionados con el mensaje primero.
    Los que no caben van solo por nombre (el modelo sabe que existen)."""
    base = base_de(boveda, proyecto)
    fichas = [f.relative_to(base).as_posix() for f in referencias.fichas_de(boveda, proyecto)] if proyecto else []
    claves = palabras(mensaje)
    textos: dict[Path, str] = {}
    for p in archivos_escribibles(base):
        try:
            textos[p] = escritor.sin_frontmatter(p.read_text(encoding="utf-8", errors="replace")).strip()
        except OSError:
            continue

    def orden(p: Path) -> tuple:
        relativa = p.relative_to(base).as_posix()
        return (-len(claves & palabras(f"{relativa} {textos[p]}")), relativa not in fichas, -p.stat().st_mtime)

    incluidos: dict[str, str] = {}
    grandes: list[Path] = []
    restante = tope_tokens
    for p in sorted(textos, key=orden):   # primero los que caben enteros…
        tokens = estimar_tokens(textos[p]) + 10
        if tokens <= restante:
            incluidos[p.relative_to(base).as_posix()] = textos[p]
            restante -= tokens
        else:
            grandes.append(p)
    fuera = [p.relative_to(base).as_posix() for p in grandes]
    if grandes and restante > 300:        # …y del más relacionado que no cupo, el final (lo más reciente)
        caben = int((restante - 20) * CARACTERES_POR_TOKEN)
        incluidos[fuera.pop(0)] = "(recortado: solo el final)\n…" + textos[grandes[0]][-caben:]
    carpeta = (referencias.carpeta_personajes(boveda, proyecto).relative_to(base).as_posix()
               if proyecto else "")
    return {
        "proyecto": proyecto or "ninguno (00-Bandeja)",
        "carpeta_personajes": carpeta or "(sin proyecto no hay fichas)",
        "fichas": fichas,
        "archivos": incluidos,
        "otros_archivos": fuera,
    }


# --- validación -----------------------------------------------------------------------
def _clave(ruta: str) -> str:
    return escritor.sin_acentos(ruta).casefold()


def _ruta_segura(base: Path, archivo: str) -> Path | None:
    """Ruta dentro de `base` con nombres válidos en Windows, o None si no se puede usar."""
    limpio = str(archivo or "").strip().replace("\\", "/").strip("/")
    if not limpio:
        return None
    if not limpio.casefold().endswith(".md"):
        limpio += ".md"
    partes = limpio[:-3].split("/")
    if any(p.strip() in ("", ".", "..") for p in partes):
        return None
    try:
        seguras = [escritor.nombre_carpeta(p) for p in partes]
    except ValueError:
        return None
    relativa = Path(*seguras[:-1], seguras[-1] + ".md")
    if _reservada(relativa):
        return None
    return base / relativa


def _seccion(texto: str) -> str:
    s = " ".join(str(texto or "").split()).lstrip("#").strip()
    return f"## {s}" if s else ""


def validar(datos: dict, boveda: Boveda, proyecto: str | None) -> Plan:
    base = base_de(boveda, proyecto)
    existentes = {_clave(p.relative_to(base).as_posix()): p for p in archivos_escribibles(base)}
    plan = Plan([], respuesta=" ".join(str(datos.get("respuesta") or "").split())[:300],
                pregunta=" ".join(str(datos.get("pregunta") or "").split())[:300],
                avisos=[" ".join(str(a).split())[:300] for a in (datos.get("avisos") or [])
                        if isinstance(a, str) and a.strip()][:3])
    crudas = datos.get("operaciones") or []
    if not isinstance(crudas, list):
        crudas = []
    for cruda in crudas[:MAX_OPERACIONES]:
        op = _operacion(cruda, boveda, proyecto, base, existentes)
        if op is None:
            plan.descartadas += 1
        else:
            plan.operaciones.append(op)
    plan.descartadas += max(0, len(crudas) - MAX_OPERACIONES)
    return plan


def _operacion(cruda: object, boveda: Boveda, proyecto: str | None, base: Path,
               existentes: dict[str, Path]) -> Operacion | None:
    if not isinstance(cruda, dict):
        return None
    texto = str(cruda.get("texto") or "").strip()
    if not texto:
        return None
    personaje = bool(cruda.get("personaje")) and proyecto is not None
    ruta = _ruta_segura(base, str(cruda.get("archivo") or ""))
    if ruta is None:
        return None
    if personaje:
        # Si ya tiene ficha (por nombre o alias), se agrega ahí; si no, va a la carpeta de personajes.
        hallada = referencias.buscar_personaje(boveda, ruta.stem, proyecto)
        ruta = hallada[1] if hallada else referencias.carpeta_personajes(boveda, proyecto) / ruta.name
    ruta = existentes.get(_clave(ruta.relative_to(base).as_posix()), ruta)
    op = "agregar" if ruta.exists() else "crear"
    return Operacion(op, ruta, texto, seccion=_seccion(cruda.get("seccion")) if op == "agregar" else "",
                     titulo=" ".join(str(cruda.get("titulo") or "").split()).strip("# ")[:80],
                     personaje=personaje and op == "crear")


def _raices(texto: str) -> set[str]:
    """Palabras con contenido, recortadas a 5 letras: "personajes" y "personaje" cuentan igual."""
    return {p[:5] for p in palabras(texto) if p not in ORDEN}


def cobertura(mensaje: str, plan: Plan, base: Path) -> float:
    buscadas = _raices(mensaje)
    if len(buscadas) < MIN_PALABRAS_COBERTURA:
        return 1.0
    escrito = " ".join(f"{op.ruta.relative_to(base).as_posix()} {op.seccion} {op.titulo} {op.texto}"
                       for op in plan.operaciones)
    return len(buscadas & _raices(escrito)) / len(buscadas)


# --- aplicar ------------------------------------------------------------------------------
def aplicar(boveda: Boveda, plan: Plan, proyecto: str | None, origen: str) -> list[Path]:
    """Escribe las operaciones (cada archivo de forma atómica). Devuelve las rutas, sin repetir."""
    ahora = boveda.ahora()
    marca = f"{ahora.strftime('%Y-%m-%d %H:%M')} · {'voz' if origen == 'voz' else 'texto'}"
    rutas: list[Path] = []
    for op in plan.operaciones:
        texto = op.texto.strip()
        if op.op == "crear" and op.ruta.exists():   # otra operación del mismo plan ya lo creó
            op.op = "agregar"
        if op.op == "crear":
            titulo = op.ruta.stem
            meta = ({"tipo": "personaje", "proyecto": proyecto, "nombre": titulo, "aliases": []}
                    if op.personaje else {"tipo": "notas", "proyecto": proyecto})
            cuerpo = texto if texto.startswith("# ") else f"# {titulo}\n\n{texto}"
            escritor.escribir_atomico(op.ruta, escritor.con_frontmatter(meta, cuerpo))
            boveda.registrar_diario(("Personaje nuevo" if op.personaje else "Archivo nuevo")
                                    + f" [[{boveda.enlace(op.ruta)}|{op.ruta.stem}]]")
        elif op.seccion:
            referencias.insertar_en_seccion(op.ruta, op.seccion, texto,
                                            parrafo=not texto.startswith(("- ", "* ", "+ ")))
            boveda.registrar_diario(f"Nota en [[{boveda.enlace(op.ruta)}#{op.seccion[3:]}|{op.ruta.stem}]]")
        else:
            encabezado = op.titulo or marca
            fecha = f"_{marca}_\n\n" if op.titulo else ""
            escritor.agregar_al_final(op.ruta, f"\n## {encabezado}\n\n{fecha}{texto}")
            boveda.registrar_diario(f"Nota en [[{boveda.enlace(op.ruta)}#{encabezado}|{op.ruta.stem}]]")
        if op.ruta not in rutas:
            rutas.append(op.ruta)
    return rutas


# --- modelo -------------------------------------------------------------------------------
class Redactor:
    def __init__(self, cliente: OpenClaw, nivel: Nivel, max_tokens: int = 3000,
                 tope_contexto_tokens: int = 12000, tiempo_max_s: float = 90):
        self.cliente = cliente
        self.nivel = nivel
        self.max_tokens = max_tokens
        self.tope = tope_contexto_tokens
        self.tiempo_max_s = tiempo_max_s

    async def planear(self, boveda: Boveda, mensaje: str, proyecto: str | None, origen: str,
                      ultima: dict | None = None, pista: dict | None = None) -> Plan | None:
        """Plan validado, o None si el modelo no responde o responde algo inútil.
        Lanza SinCobertura si lo propuesto deja fuera demasiado del mensaje."""
        entrada = {"mensaje": mensaje, "origen": "voz" if origen == "voz" else "texto",
                   "pista_del_interprete": pista or {},
                   **contexto(boveda, proyecto, mensaje, self.tope),
                   "ultima_accion": ultima or {}}
        texto = json.dumps(entrada, ensure_ascii=False)
        respuesta = await self.cliente.completar_con(self.nivel, texto, SISTEMA, max_tokens=self.max_tokens,
                                                     tiempo_max_s=self.tiempo_max_s)
        if respuesta is None:
            log.warning("Redactor: %s no respondió (%s)", self.nivel.modelo, self.cliente.ultimo_error)
            return None
        log.info("Redactor %s: %d tokens de entrada, %d de salida", respuesta.modelo,
                 respuesta.tokens_entrada, respuesta.tokens_salida)
        datos = extraer_json(respuesta.texto)
        if datos is None:
            log.warning("Redactor: respuesta sin JSON válido (%d caracteres)", len(respuesta.texto))
            return None
        plan = validar(datos, boveda, proyecto)
        if plan.descartadas:
            log.warning("Redactor: %d operaciones descartadas (ruta no válida o vacías)", plan.descartadas)
        if not plan.operaciones and not plan.pregunta:
            return None
        if plan.operaciones:
            nivel = cobertura(mensaje, plan, base_de(boveda, proyecto))
            if nivel < UMBRAL_COBERTURA:
                raise SinCobertura(f"cobertura {nivel:.0%}")
        return plan


def resumen(plan: Plan, rutas: list[Path], relativa) -> str:
    """Mensaje para el usuario: lo que dijo el redactor, dónde quedó y los avisos."""
    lineas = [plan.respuesta or "Listo, guardado."]
    lineas += [f"- {relativa(r)}" for r in rutas]
    lineas += [f"⚠ {a}" for a in plan.avisos]
    return "\n".join(lineas)


def resumen_hablado(plan: Plan) -> str:
    frase = plan.respuesta or "Listo, lo guardé."
    if plan.avisos:
        frase += " Ojo: " + plan.avisos[0]
    # [[Ruta/Aely|Aely]] -> "Aely"; [[Kael]] -> "Kael": en voz no se leen rutas.
    return re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
                  lambda m: m.group(2) or m.group(1).rsplit("/", 1)[-1], frase)
