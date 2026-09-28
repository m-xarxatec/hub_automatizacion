"""Reglas por palabras clave: el nivel más barato del router.

Sirven de respaldo cuando el clasificador local (día 3) no está entrenado
o no responde, y detectan patrones claros como
"esta imagen es referencia para Zamael" sin gastar ningún modelo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..boveda.escritor import sin_acentos


@dataclass
class Decision:
    accion: str
    confianza: float
    tipo: str = "general"
    extra: dict = field(default_factory=dict)
    motor: str = "reglas"


# Se evalúan sobre el texto en minúsculas y sin acentos.
_ACCIONES: list[tuple[str, float, re.Pattern]] = [
    ("tarea", 0.85, re.compile(
        r"^(tengo que|hay que|pendiente\b|recordar\b|recuerda(me)?\b|no olvidar|todo\s*:|tarea\s*:)")),
    ("imagen", 0.85, re.compile(
        r"\b(genera(r|me)?|crea(r|me)?|dibuja(r|me)?|haz(me)?|quiero)\b.{0,40}"
        r"\b(imagen|ilustracion|dibujo|boceto|render)\b")),
    ("analisis", 0.80, re.compile(
        r"\b(es viable|seria viable|encaja(ria)?|analiza(r|me)?|tiene sentido que)\b")),
    ("busqueda", 0.75, re.compile(r"^(busca(me)?|investiga|encuentra)\b")),
    ("consulta", 0.60, re.compile(r"\?\s*$|^(que|como|cual|cuando|donde|por que|quien)\b")),
]

_TIPOS: list[tuple[str, re.Pattern]] = [
    ("idea", re.compile(r"^(idea\b|se me ocurrio|y si\b)")),
    ("dialogo", re.compile(r"\b(dialogo|le dice|responde:|dice:)")),
    ("produccion", re.compile(r"\b(storyboard|vinetas?|panel(es)?|entintado|color(es|ear)?|paleta|bocetos?|layout)\b")),
    ("historia", re.compile(r"\b(capitulos?|escenas?|trama|arcos?|personajes?|villan[oa]s?|protagonistas?)\b")),
]

# Sobre el texto original para conservar mayúsculas del nombre.
_REF_PERSONAJE = re.compile(
    r"referencia\s+(?:visual\s+)?(?:para|de|del)\s+(?:el\s+|la\s+)?(?:personaje\s+)?"
    r"(?P<nombre>[^\s,.;:!?]+(?:\s+[A-ZÁÉÍÓÚÑ][^\s,.;:!?]*)*)",
    re.IGNORECASE,
)
_ES_PERSONAJE = re.compile(
    r"^(?:este|esta|esto)\s+es\s+(?:el\s+|la\s+)?(?:personaje\s+)?(?P<nombre>[A-ZÁÉÍÓÚÑ][^\s,.;:!?]*)"
)


# Verbos con los que se pide guardar algo: "añade la tarea...", "apúntame una nota...".
_VERBO_GUARDAR = (r"(?:agreg(?:a|ar)|a[ñn]ad(?:e|ir)|anot(?:a|ar)|ap[uú]nt(?:a|ar)|pon(?:er)?|"
                  r"cr[eé](?:a|ar|es)|guard(?:a|ar))(?:me)?")

_PREFIJO_TAREA = re.compile(
    r"^\s*(tengo que|hay que|pendiente\s*:?|recordar\s*:?|recu[eé]rda(me)?\s*(que)?|"
    r"no olvidar\s*(que)?|todo\s*:|"
    rf"{_VERBO_GUARDAR}\s+(?:una\s+|la\s+)?(?:nueva\s+)?tarea\s*[:,.]?|(?:nueva\s+)?tarea\s*:)\s*",
    re.IGNORECASE)


def limpiar_tarea(texto: str) -> str:
    """'tengo que terminar el storyboard' -> 'terminar el storyboard'."""
    limpio = _PREFIJO_TAREA.sub("", texto, count=1).strip().rstrip(" .")
    return limpio or texto.strip()


def normalizar(texto: str) -> str:
    return " ".join(sin_acentos(texto).lower().split())


def tipo_nota(texto: str) -> str:
    t = normalizar(texto)
    for tipo, patron in _TIPOS:
        if patron.search(t):
            return tipo
    return "general"


def nombre_personaje(texto: str) -> str | None:
    """Nombre del personaje si el pie de foto lo indica.

    Para no confundir "referencia de iluminación" con un personaje, se exige
    que aparezca la palabra "personaje" o que el nombre empiece en mayúscula.
    """
    menciona_personaje = "personaje" in normalizar(texto)
    for patron in (_REF_PERSONAJE, _ES_PERSONAJE):
        m = patron.search(texto.strip())
        if not m:
            continue
        nombre = m.group("nombre").strip(" \"'()[]")
        if not nombre or nombre.lower() in {"el", "la", "este", "esta", "un", "una"}:
            continue
        if menciona_personaje or nombre[0].isupper():
            return nombre
    return None


def decidir(texto: str, tiene_imagen: bool = False) -> Decision:
    texto = texto or ""
    if tiene_imagen:
        nombre = nombre_personaje(texto)
        if nombre:
            return Decision("referencia_personaje", 0.90, extra={"personaje": nombre})
        return Decision("referencia", 0.80)

    t = normalizar(texto)
    for accion, confianza, patron in _ACCIONES:
        if patron.search(t):
            return Decision(accion, confianza, tipo=tipo_nota(texto))
    # Sin patrón claro: se propone nota con confianza baja, el bot pregunta.
    return Decision("nota", 0.45, tipo=tipo_nota(texto))


# --- órdenes habladas ------------------------------------------------------------------
# Al hablar no hay "/": estas frases se traducen al comando equivalente antes del router.
# Whisper agrega puntuación ("Nota, idea. La villana..."), por eso los separadores son amplios.
_SEP = r"[\s:,.;\-]+"
_ORDENES: list[tuple[str, re.Pattern]] = [
    ("proyecto_nuevo", re.compile(
        rf"^(?:crea(?:r|me)?|haz(?:me)?|abre|abrir)?\s*(?:un{_SEP})?(?:nuevo{_SEP}proyecto|proyecto{_SEP}nuevo)"
        rf"(?:{_SEP}(?:llamado|que se llame|de nombre))?{_SEP}(?P<a>.+)$", re.I)),
    ("proyecto", re.compile(
        rf"^(?:cambia(?:r)?|pasa(?:r)?|usa(?:r)?|activa(?:r)?|elige|ir)(?:{_SEP}(?:a|al|el))*"
        rf"{_SEP}proyecto{_SEP}(?P<a>.+)$", re.I)),
    ("proyectos", re.compile(
        rf"^(?:(?:ver|mu[eé]strame|muestra|lista(?:r)?|cu[aá]les son){_SEP})?(?:mis{_SEP}|los{_SEP})?proyectos$", re.I)),
    ("tareas", re.compile(
        rf"^(?:(?:ver|mu[eé]strame|muestra|lista(?:r)?|dime|cu[aá]les son){_SEP})?(?:mis{_SEP}|las{_SEP})?"
        rf"tareas(?:{_SEP}pendientes)?$|^qu[eé]{_SEP}(?:tareas{_SEP})?tengo{_SEP}pendientes?$", re.I)),
    # El artículo solo se acepta tras un verbo: "la tarea de hoy es difícil" no es una orden.
    ("tarea", re.compile(
        rf"^(?:{_VERBO_GUARDAR}{_SEP}(?:(?:una|la){_SEP})?)?(?:nueva{_SEP})?tarea{_SEP}(?P<a>.+)$", re.I)),
    ("nota", re.compile(
        rf"^(?:{_VERBO_GUARDAR}{_SEP}(?:(?:una|la){_SEP})?)?(?:nueva{_SEP})?nota(?:{_SEP}de)?"
        rf"(?:{_SEP}(?P<tipo>idea|historia|producci[oó]n|di[aá]logo))?{_SEP}(?P<a>.+)$", re.I)),
    ("estado", re.compile(rf"^(?:(?:ver|dame|mu[eé]strame|muestra){_SEP}(?:el{_SEP})?)?estado(?:{_SEP}del servidor)?$", re.I)),
    ("img", re.compile(
        rf"^(?:gen[eé]ra|cr[eé]a|haz|dib[uú]ja)(?:me)?{_SEP}(?:una?{_SEP})?(?:imagen|ilustraci[oó]n|dibujo)"
        rf"(?:{_SEP}(?:de|del|con|sobre))?{_SEP}(?P<a>.+)$", re.I)),
]


# --- archivo aparte y personajes ---------------------------------------------------
# Por defecto las notas se acumulan en Ideas.md, Historia.md…; solo se crea un archivo
# propio si el usuario lo pide con estas frases.
_ADJ_APARTE = r"(?:aparte|nuev[oa]|propi[oa]|separad[oa])"
_APARTE = [
    re.compile(rf"^(?:{_VERBO_GUARDAR}|haz(?:me)?|abre){_SEP}(?:(?:un|una|otro){_SEP})?(?:archivo|documento)"
               rf"(?:{_SEP}{_ADJ_APARTE})?(?:{_SEP}(?:de|del|sobre|con|para|llamado|que diga))?{_SEP}(?P<a>.+)$", re.I),
    re.compile(rf"^(?:{_VERBO_GUARDAR}{_SEP}(?:(?:una|la|otra){_SEP})?)?nota{_SEP}(?:aparte|separada|propia)"
               rf"(?:{_SEP}(?:de|del|sobre|con|para))?{_SEP}(?P<a>.+)$", re.I),
    # Al final de la frase se exige el adjetivo: "…está en otro archivo" no es un pedido.
    re.compile(rf"^(?P<a>.+?){_SEP}(?:en|como){_SEP}(?:un|una){_SEP}(?:archivo|documento|nota){_SEP}{_ADJ_APARTE}$", re.I),
    re.compile(rf"^aparte{_SEP}(?P<a>.+)$", re.I),   # /nota aparte: …
]


def archivo_aparte(texto: str) -> str | None:
    """'Crea un archivo sobre el mercado flotante' -> 'el mercado flotante'.

    Devuelve el texto de la nota si el usuario pidió un archivo propio; si no, None.
    """
    limpio = (texto or "").strip().rstrip(".!… ").strip()
    for patron in _APARTE:
        m = patron.match(limpio)
        if m and m.group("a").strip(" .,:"):
            arg = m.group("a").strip(" .,:")
            return arg[0].upper() + arg[1:]
    return None


_PERSONAJE = re.compile(
    rf"^(?:(?:{_VERBO_GUARDAR}|haz(?:me)?|invent(?:a|ar)(?:me)?|dise[ñn](?:a|ar)(?:me)?){_SEP}"
    rf"(?:(?:un|una|el|la|otro|otra){_SEP})?(?:nuev[oa]{_SEP})?|nuev[oa]{_SEP})personaje(?P<resto>(?:{_SEP}.*)?)$",
    re.I)
# Sin re.I global: las palabras siguientes del nombre deben empezar en mayúscula ("Ana Luz"),
# así "llamado Bruno que sea carnicero" no se lleva "que sea carnicero".
_NOMBRE_DADO = re.compile(
    r"(?:,\s*)?\b(?i:llamad[oa]|que se llam[ea]|de nombre|con el nombre(?:\s+de)?)\s+"
    r"(?P<nombre>[^\s,.;:!?]+(?:\s+[A-ZÁÉÍÓÚÑ][^\s,.;:!?]*)*)")
# "Nuevo personaje: Kira, una espadachina" -> el nombre va primero, con mayúscula y seguido de coma.
_NOMBRE_PRIMERO = re.compile(
    rf"^{_SEP}(?P<nombre>[A-ZÁÉÍÓÚÑ][^\s,.;:!?]*(?:\s+[A-ZÁÉÍÓÚÑ][^\s,.;:!?]*)*)\s*(?:[,;:]|\.?\s*$)")
_RELLENO_DESCRIPCION = re.compile(r"^(?:que\s+(?:sea|es|ser[aá])|que|con|de)\s+", re.I)


# Introducciones habituales antes del pedido: "Bueno, vamos a crear un personaje…",
# "Quiero que crees un personaje…". También se busca el pedido en una oración posterior:
# "Tengo una idea. Crea un personaje llamado Kira."
_INTRO_PEDIDO = re.compile(
    r"^(?:(?:bueno|vale|ok|oye|muy bien|entonces|ahora|y)[\s,.]+)*"
    r"(?:(?:quiero|me gustar[ií]a|necesito)(?:\s+que)?|vamos\s+a|vas\s+a|puedes|podr[ií]as)\s+", re.I)
_ORACION = re.compile(r"(?<=[.!?])\s+")


def pedido_personaje(texto: str) -> tuple[str | None, str] | None:
    """'Crea un personaje llamado Bruno que sea carnicero' -> ('Bruno', 'Carnicero').

    Devuelve (nombre o None, descripción) si la frase pide crear un personaje; si no, None.
    Lo que viene antes del pedido (introducción u oraciones previas) no entra en la ficha.
    """
    oraciones = _ORACION.split((texto or "").strip())
    for i in range(len(oraciones)):
        desde = " ".join(oraciones[i:]).strip().strip("¿¡")
        m = _PERSONAJE.match(_INTRO_PEDIDO.sub("", desde, count=1))
        if m:
            break
    else:
        return None
    resto = m.group("resto")
    nombre = None
    dado = _NOMBRE_DADO.search(resto) or _NOMBRE_PRIMERO.match(resto)
    if dado:
        nombre = dado.group("nombre").strip(" \"'")
        resto = resto[:dado.start()] + " " + resto[dado.end():]
    descripcion = re.sub(r"\s+", " ", resto).strip(" .,;:-")
    descripcion = _RELLENO_DESCRIPCION.sub("", descripcion).strip(" .,;:-")
    if descripcion:
        descripcion = descripcion[0].upper() + descripcion[1:] + "."
    return nombre, descripcion


# La respuesta suele ser una frase completa: "El nombre del personaje será Aeli".
# El nombre se busca después de estas expresiones; sus palabras siguientes deben ir en mayúscula.
_NOMBRE_EN_FRASE = re.compile(
    r"(?i:\b(?:se\s+(?:va\s+a\s+)?llam(?:a|ar[aá]|ar)|"
    r"(?:su|el)\s+nombre(?:\s+(?:del?\s+)?(?:personaje|ella|[eé]l))?\s+(?:es|ser[aá]|va\s+a\s+ser)|"
    r"ll[aá]m(?:a|e)(?:lo|la|le)|p[oó]n(?:le|lo|la)|le\s+(?:vamos\s+a\s+poner|pondremos|pongo)))"
    r"\s*:?\s+[\"'«]?(?P<nombre>[^\s,.;:!?\"'»]+(?:\s+[A-ZÁÉÍÓÚÑ][^\s,.;:!?\"'»]*)*)")
_PREFIJO_NOMBRE = re.compile(r"^(?:es|nombre\s*:?)\s+", re.I)


def nombre_respondido(texto: str) -> str | None:
    """'El nombre del personaje será Aeli.' -> 'Aeli'; 'Bruno' -> 'Bruno'.
    None si la respuesta no parece un nombre."""
    limpio = (texto or "").strip().strip("¿¡").rstrip(".!?… ").strip()
    m = _NOMBRE_EN_FRASE.search(limpio)
    if m:
        return m.group("nombre")
    limpio = _PREFIJO_NOMBRE.sub("", limpio).strip(" \"'.,«»")
    if not limpio or len(limpio.split()) > 3:
        return None
    return limpio


def orden_hablada(texto: str) -> tuple[str, str] | None:
    """'Nota idea, la villana usa una máscara.' -> ('nota', 'idea: la villana usa una máscara').

    Devuelve (comando, argumentos) con el mismo formato que los comandos escritos,
    o None si la frase no es una orden directa (entonces decide el router).
    """
    limpio = (texto or "").strip().strip("¿¡").rstrip(".!?… ").strip()
    if archivo_aparte(limpio):
        return "nota", limpio   # la nota decide después que va en archivo propio
    for comando, patron in _ORDENES:
        m = patron.match(limpio)
        if not m:
            continue
        arg = (m.groupdict().get("a") or "").strip(" .,")
        if comando == "proyecto_nuevo":
            return "proyecto", f"nuevo {arg}"
        if comando == "proyectos":
            return "proyecto", ""
        if comando == "nota" and m.group("tipo"):
            return "nota", f"{sin_acentos(m.group('tipo')).lower()}: {arg}"
        return comando, arg
    return None


# --- nombre de la última imagen generada --------------------------------------------------
# "La imagen que se acaba de crear será el personaje Aeli" / "Renombra la imagen como Kira".
_NOMBRE_LIBRE = r"(?P<nombre>[^\s,.;:!?\"'«»]+(?:\s+[A-ZÁÉÍÓÚÑ][^\s,.;:!?\"'«»]*)*)"
_IMAGEN_SERA = re.compile(
    r"^(?i:(?:(?:bueno|vale|ok|muy bien|entonces|ahora|y)[\s,.]+)*(?:la|esta|esa)\s+(?:[uú]ltima\s+)?imagen"
    r"(?:\s+que\s+(?:se\s+)?acab\w*\s+de\s+\w+)?\s+(?:ser[aá]|es|se\s+llama(?:r[aá])?|va\s+a\s+ser)\s+"
    r"(?:(?:el|la|de|del)\s+)?(?P<personaje>personaje\s+)?)" + _NOMBRE_LIBRE)
_IMAGEN_RENOMBRA = re.compile(
    r"^(?i:(?:renombra|ll[aá]ma|nombra|p[oó]n(?:le)?\s+de\s+nombre)\s+(?:a\s+)?(?:la|esta|esa)\s+"
    r"(?:[uú]ltima\s+)?imagen\s+(?:como\s+|a\s+)?)" + _NOMBRE_LIBRE)


def renombrar_imagen(texto: str) -> str | None:
    """'La imagen que se acaba de crear será el personaje Aeli' -> 'Aeli'; si no, None.

    Con "es/será" se exige mayúscula o la palabra "personaje": "la imagen es muy bonita"
    no renombra nada. Con un verbo explícito ("renombra la imagen como kira") basta el nombre.
    """
    limpio = (texto or "").strip().strip("¿¡").rstrip(".!?… ").strip()
    m = _IMAGEN_RENOMBRA.match(limpio)
    if m:
        return m.group("nombre")
    m = _IMAGEN_SERA.match(limpio)
    if m and (m.group("personaje") or m.group("nombre")[0].isupper()):
        return m.group("nombre")
    return None
