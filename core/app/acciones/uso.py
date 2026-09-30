"""Tokens gastados por el bot: /tokens y la línea de uso de /estado (2026-09-30).

Cada llamada a un modelo se suma en SQLite (tabla `uso`, ver estado/db.py y el contador de
proveedores/openclaw.py) por día, función y modelo. Las imágenes se cuentan sin tokens: el
gateway de OpenClaw no los informa. Con suscripción no hay cobro por token, pero los tokens
cuentan para los límites de uso de ChatGPT y Claude: por eso vale la pena verlos.
"""

from __future__ import annotations

from datetime import date

from ..estado.db import Estado

FUNCIONES = {"interprete": "Intérprete", "redactor": "Redactor", "consulta": "Consulta",
             "analisis": "Análisis", "router": "Router (dudas)", "imagen": "Imágenes"}
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre")
NOTA_ESTIMADA = ("~ salida estimada por el largo del texto: Claude por Claude Code no la informa bien, "
                 "y su entrada no incluye el prompt propio del programa (~3.700 tokens por llamada).")
NOTA_LOCAL = "La voz (Whisper y Kokoro), los comandos y las órdenes fijas no gastan tokens."


def miles(n: int) -> str:
    """41230 -> "41.230"."""
    return f"{int(n):,}".replace(",", ".")


def para_decir(n: int) -> str:
    """41230 -> "41 mil"; 850 -> "850"; 1250000 -> "1,3 millones" (para la voz)."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{round(n / 1000)} mil"
    return f"{n / 1_000_000:.1f}".replace(".", ",").removesuffix(",0") + " millones"


def _fecha(dia: str) -> date:
    return date.fromisoformat(dia)


def _llamadas(n: int) -> str:
    return f"{n} llamada" + ("" if n == 1 else "s")


def _totales(filas: list[tuple]) -> tuple[int, int, int, int]:
    """(llamadas de texto, entrada, salida, imágenes) de filas que terminan en
    (llamadas, entrada, salida, estimadas); las de imagen van aparte."""
    texto = [f for f in filas if f[0] != "imagen"]
    imagenes = sum(f[-4] for f in filas if f[0] == "imagen")
    return (sum(f[-4] for f in texto), sum(f[-3] for f in texto), sum(f[-2] for f in texto), imagenes)


def texto_tokens(estado: Estado, hoy: date) -> str:
    dia = hoy.isoformat()
    filas_hoy = estado.uso(dia, dia)                           # (funcion, modelo, llamadas, entrada, salida, estimadas)
    primero = estado.primer_dia_de_uso()
    if not primero:
        return ("Todavía no hay llamadas a modelos registradas.\n" + NOTA_LOCAL)
    lineas = ["Tokens usados por el bot",
              "Con suscripción no se cobra por token, pero cuentan para los límites de uso.", ""]
    llamadas, entrada, salida, imagenes = _totales(filas_hoy)
    if filas_hoy:
        lineas.append(f"Hoy ({hoy:%d/%m}): {miles(entrada + salida)} tokens en {_llamadas(llamadas)} "
                      f"({miles(entrada)} de entrada y {miles(salida)} de salida)")
        for funcion, modelo, n, ent, sal, estimadas in filas_hoy:
            nombre = f"{FUNCIONES.get(funcion, funcion)} · {modelo}"
            if funcion == "imagen":
                lineas.append(f"• {nombre}: {n} generada{'s' if n != 1 else ''} (sin datos de tokens)")
            else:
                lineas.append(f"• {nombre}: {miles(ent + sal)} en {_llamadas(n)}{' ~' if estimadas else ''}")
    else:
        lineas.append(f"Hoy ({hoy:%d/%m}): sin llamadas a modelos todavía.")
    if primero < dia:
        total = estado.uso(por=("funcion", "modelo"))
        llamadas_t, entrada_t, salida_t, imagenes_t = _totales(total)
        lineas += ["", f"Desde el {_fecha(primero):%d/%m}: {miles(entrada_t + salida_t)} tokens en "
                       f"{_llamadas(llamadas_t)}" + (f" y {imagenes_t} imágenes" if imagenes_t else "")]
        por_modelo: dict[str, list[int]] = {}
        for funcion, modelo, n, ent, sal, estimadas in total:
            if funcion != "imagen":
                acumulado = por_modelo.setdefault(modelo, [0, 0])
                acumulado[0] += ent + sal
                acumulado[1] += estimadas
        lineas += [f"• {modelo}: {miles(tokens)}{' ~' if estimadas else ''}"
                   for modelo, (tokens, estimadas) in sorted(por_modelo.items(), key=lambda x: -x[1][0])]
    if any(f[-1] for f in estado.uso(por=("modelo",))):
        lineas += ["", NOTA_ESTIMADA]
    lineas += ["", NOTA_LOCAL]
    return "\n".join(lineas)


def hablado_hoy(estado: Estado, hoy: date) -> str:
    """"Hoy llevas 41 mil tokens en 18 llamadas." (para la voz de /tokens y de /estado)."""
    dia = hoy.isoformat()
    llamadas, entrada, salida, _ = _totales(estado.uso(dia, dia))
    return (f"Hoy llevas {para_decir(entrada + salida)} tokens en {_llamadas(llamadas)}."
            if llamadas else "Hoy todavía no hay llamadas a modelos.")


def hablado_tokens(estado: Estado, hoy: date) -> str:
    dia = hoy.isoformat()
    primero = estado.primer_dia_de_uso()
    if not primero:
        return "Todavía no hay llamadas a modelos registradas."
    frase = hablado_hoy(estado, hoy)
    if primero < dia:
        _, entrada_t, salida_t, _ = _totales(estado.uso())
        inicio = _fecha(primero)
        frase += f" Desde el {inicio.day} de {MESES[inicio.month - 1]}, {para_decir(entrada_t + salida_t)}."
    return frase + " Para el detalle, escribe barra tokens."


def linea_estado(estado: Estado, hoy: date) -> str:
    dia = hoy.isoformat()
    llamadas, entrada, salida, imagenes = _totales(estado.uso(dia, dia))
    if not llamadas and not imagenes:
        return "Uso de hoy: sin llamadas a modelos todavía"
    extra = f", {imagenes} imagen{'es' if imagenes != 1 else ''}" if imagenes else ""
    return f"Uso de hoy: {_llamadas(llamadas)}, {miles(entrada + salida)} tokens{extra} (detalle: /tokens)"
