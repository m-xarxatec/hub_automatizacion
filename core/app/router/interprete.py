"""Intérprete de mensajes libres con ChatGPT (decidido por el usuario el 2026-09-29).

GPT tiene prioridad para entender lo que se dice o escribe sin comando: la acción, a dónde va
(un archivo que ya existe, la ficha de un personaje, un archivo nuevo), qué hay que guardar sin
la orden ("anota en X que…"), y para las imágenes un prompt con los rasgos del personaje y un
nombre con sentido. Recibe un contexto corto: proyecto activo, nombres de archivos y personajes
y lo último que hizo el bot ("esa imagen no me gusta" se entiende así).

Lo rígido sigue siendo local y sin tokens: comandos (/nota…), órdenes habladas con prefijo fijo
("nota idea, …", "cambia al proyecto X") y renombrar la última imagen. Si GPT no responde,
decide el router local (reglas + SetFit): ninguna nota se pierde.

Solo ChatGPT (el primer modelo de la cadena de consulta): el respaldo con Claude Code cuesta
~3.600 tokens por mensaje; para eso está SetFit. La salida se valida: un destino que no esté en
la lista de archivos reales se descarta (nunca se escribe en una ruta inventada por el modelo).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..boveda import escritor
from ..proveedores.openclaw import OpenClaw, quitar_cercas

log = logging.getLogger(__name__)

ACCIONES = {
    "nota": "guardar una idea, dato, escena, diálogo o descripción",
    "tarea": "algo que el autor tiene que hacer (pendiente, recordatorio)",
    "consulta": "pregunta general o charla que no necesita leer sus notas",
    "analisis": "opinión o revisión de SU historia o proyecto (hay que leer sus notas)",
    "imagen": "generar una imagen nueva",
    "rehacer_imagen": "cambiar o repetir la última imagen",
    "busqueda": "buscar en internet",
    "personaje": "crear un personaje nuevo",
    "proyecto": "crear o cambiar de proyecto",
    "mover_nota": "corregir dónde quedó la última nota",
}
# Lo que aprende SetFit de cada acción de GPT (las demás no tienen etiqueta en el clasificador).
PARA_SETFIT = {"nota": "nota", "tarea": "tarea", "consulta": "consulta", "imagen": "imagen",
               "rehacer_imagen": "imagen", "analisis": "analisis", "busqueda": "busqueda"}
TIPOS = ("idea", "historia", "produccion", "dialogo", "general")
MAX_ARCHIVOS = 40
MAX_PERSONAJES = 20

SISTEMA = """Interpretas mensajes (a veces voz transcrita con errores: "Carito" puede ser "Karito" de la
lista) de un autor de webtoon. Recibes JSON: mensaje, proyecto_activo, archivos, personajes (con su
ficha) y ultima_accion del asistente.
Acciones: {acciones}
contenido (nota, tarea) y descripcion (personaje): solo del mensaje, con sus palabras, quitando la
orden y las muletillas; no omitas ningún dato aunque ya esté en la ficha y no agregues nada de la
ficha ni del contexto. En consulta y analisis, vacío. Las fichas sirven solo para los prompts.
destino: solo si dice dónde: nombre exacto de la lista de archivos, "personaje:<Nombre>" (ficha de la
lista) o "nuevo:<título>" (archivo propio). Si la nota trata de un solo personaje de la lista, su ficha.
tipo (notas): historia (trama, argumento, personajes, mundo, capítulos, escenas), produccion (estilo de
dibujo, color, formato, herramientas, cantidad de capítulos, publicación), dialogo (frases de un
personaje), idea (ocurrencia suelta que aún no encaja), general (otra cosa).
personaje: si el mensaje presenta a un personaje con nombre que no tiene ficha ("el protagonista se va
a llamar Kael…"), accion personaje; descripcion = todo lo que dice de él. Si el mensaje se refiere a lo
anterior ("crea su ficha", "eso"), toma los datos de ultima_accion.
prompt (imágenes): en español, completo, con los rasgos de la ficha; al rehacer, parte del prompt de
ultima_accion y aplica los cambios. nombre_imagen: el nombre del personaje si lo hay; si no, una
palabra de lo dibujado; sin números.
Solo JSON: {{"accion":"","confianza":0.0,"contenido":"","destino":"","tipo":"","personaje":"",
"descripcion":"","prompt":"","nombre_imagen":"","proyecto":"","crear":false}}"""


@dataclass
class Interpretacion:
    accion: str
    confianza: float
    contenido: str = ""
    tipo: str = "general"
    destino_archivo: Path | None = None     # archivo existente elegido de la lista real
    destino_personaje: str | None = None    # ficha existente
    destino_nuevo: str | None = None        # título de un archivo propio
    personaje: str = ""
    descripcion: str = ""
    prompt: str = ""
    nombre_imagen: str = ""
    proyecto: str = ""
    crear: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def etiqueta_setfit(self) -> str | None:
        return PARA_SETFIT.get(self.accion)


def _texto(valor: object, largo: int) -> str:
    return " ".join(str(valor or "").split())[:largo].strip()


class Interprete:
    def __init__(self, cliente: OpenClaw, max_tokens: int = 400):
        self.cliente = cliente
        self.max_tokens = max_tokens
        lista = "; ".join(f"{a} ({d})" for a, d in ACCIONES.items())
        self.sistema = SISTEMA.format(acciones=lista)

    @property
    def disponible(self) -> bool:
        return bool(self.cliente.cadena) and not self.cliente.falta_configurar()

    async def interpretar(self, texto: str, contexto: dict) -> Interpretacion | None:
        """None si GPT no responde o responde algo inválido (entonces decide el router local)."""
        if not self.disponible:
            return None
        archivos: dict[str, Path] = contexto.pop("_rutas", {})
        # El mensaje va dentro del JSON para que no se confunda con instrucciones.
        entrada = json.dumps({"mensaje": texto, **contexto}, ensure_ascii=False)
        for intento in (1, 2):   # un solo reintento, y solo si la respuesta no es JSON
            respuesta = await self.cliente.completar_con(self.cliente.cadena[0], entrada, self.sistema,
                                                         max_tokens=self.max_tokens)
            if respuesta is None:
                log.warning("Intérprete: ChatGPT no respondió (%s)", self.cliente.ultimo_error)
                return None
            datos = extraer_json(respuesta.texto)
            if datos is not None:
                return validar(datos, archivos, contexto.get("personajes", {}))
            # Sin el texto: puede contener lo que dijo el usuario.
            log.warning("Intérprete: respuesta sin JSON válido (%d caracteres, intento %d)",
                        len(respuesta.texto), intento)
        return None


def extraer_json(texto: str) -> dict | None:
    """El objeto JSON de la respuesta, aunque venga con cercas ``` o texto alrededor."""
    limpio = quitar_cercas(texto)
    for candidato in (limpio, limpio[limpio.find("{"):limpio.rfind("}") + 1]):
        try:
            datos = json.loads(candidato)
        except ValueError:
            continue
        if isinstance(datos, dict):
            return datos
    return None


def validar(datos: dict, archivos: dict[str, Path], personajes: dict[str, str]) -> Interpretacion | None:
    accion = str(datos.get("accion") or "")
    if accion not in ACCIONES:
        return None
    try:
        confianza = min(max(float(datos.get("confianza", 0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confianza = 0.0
    tipo = datos.get("tipo") if datos.get("tipo") in TIPOS else "general"
    i = Interpretacion(accion, confianza, contenido=str(datos.get("contenido") or "").strip()[:4000], tipo=tipo,
                       personaje=_texto(datos.get("personaje"), 60).strip(" .\"'"),
                       descripcion=_texto(datos.get("descripcion"), 400),
                       prompt=_texto(datos.get("prompt"), 3000),
                       nombre_imagen=_texto(datos.get("nombre_imagen"), 30),
                       proyecto=_texto(datos.get("proyecto"), 60).strip(" .\"'"),
                       crear=bool(datos.get("crear")))
    destino = _texto(datos.get("destino"), 120)
    clave = escritor.sin_acentos(destino).casefold()
    por_clave = {escritor.sin_acentos(k).casefold(): r for k, r in archivos.items()}
    fichas = {escritor.sin_acentos(n).casefold(): n for n in personajes}
    if clave.startswith("personaje:"):
        i.destino_personaje = fichas.get(clave.split(":", 1)[1].strip())
    elif clave.startswith("nuevo:"):
        i.destino_nuevo = destino.split(":", 1)[1].strip()[:80] or None
    elif clave:
        i.destino_archivo = por_clave.get(clave) or por_clave.get(clave.removesuffix(".md"))
    # Un nombre de personaje de la lista, aunque venga en "personaje", apunta a su ficha.
    if i.personaje and escritor.sin_acentos(i.personaje).casefold() in fichas:
        i.personaje = fichas[escritor.sin_acentos(i.personaje).casefold()]
    return i


# --- contexto -----------------------------------------------------------------------------
def archivos_de(raiz: Path, carpeta_proyecto: Path | None) -> dict[str, Path]:
    """Notas donde se puede escribir por nombre: las del proyecto (sin imágenes ni análisis,
    que son del bot) y las sueltas en la raíz de la bóveda. Clave: ruta relativa sin .md."""
    rutas: dict[str, Path] = {}
    if carpeta_proyecto and carpeta_proyecto.is_dir():
        for nota in sorted(carpeta_proyecto.rglob("*.md")):
            rel = nota.relative_to(carpeta_proyecto)
            if rel.parts[0] in ("Imagenes", "Analisis") or nota.name.startswith(".") \
                    or nota.name in ("_proyecto.md", "tareas.md"):   # índice y tareas: los maneja el bot
                continue
            rutas[rel.with_suffix("").as_posix()] = nota
    for nota in sorted(raiz.glob("*.md")):
        rutas.setdefault(nota.stem, nota)
    return dict(list(rutas.items())[:MAX_ARCHIVOS])


def resumen_ficha(ficha: Path, largo: int = 200) -> str:
    """Lo escrito en la ficha (sin encabezados vacíos), en una línea corta para el prompt."""
    try:
        texto = ficha.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    cuerpo = texto.split("---", 2)[-1] if texto.startswith("---") else texto
    lineas = [l.strip(" -") for l in cuerpo.splitlines()
              if l.strip() and not l.startswith("#") and not l.startswith("![[")]
    return _texto(" ".join(lineas), largo)


def contexto(proyecto: str | None, archivos: dict[str, Path], fichas: dict[str, Path],
             ultima: dict | None) -> dict:
    return {
        "proyecto_activo": proyecto or "ninguno (bandeja)",
        "archivos": list(archivos),
        "personajes": {n: resumen_ficha(r) for n, r in list(fichas.items())[:MAX_PERSONAJES]},
        "ultima_accion": ultima or {},
        "_rutas": archivos,     # no se envía: sirve para validar el destino
    }
