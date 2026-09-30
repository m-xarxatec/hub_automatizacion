"""Presentación de Telegram en local: HTML seguro, sin llamadas a modelos."""

from html import escape
import re


def titulo(texto: str) -> str:
    """Identifica respuestas del core; las consultas conservan su propio título."""
    opciones = (
        (("No pude", "No entendí", "El entrenamiento falló"), "⚠️ Necesito tu atención"),
        (("Nota (", "Nota agregada", "Referencia guardada", "Anotado en el diario", "Guardado"), "✅ Guardado en tu bóveda"),
        (("Tarea agregada",), "✅ Un paso más hacia tu idea"),
        (("Pendientes en",), "📋 Tu próxima jugada"),
        (("No hay pendientes",), "✨ Todo al día"),
        (("Proyecto activo:", "Proyecto ", "Sin proyecto activo"), "📂 Tu espacio creativo"),
        (("Servidor:",), "🟢 Hub creativo · Estado"),
        (("Tokens usados", "Todavía no hay llamadas"), "📊 Tu consumo de tokens"),
        (("Contexto reiniciado",), "✨ Empezamos de nuevo"),
        (("¿Qué hago", "¿Lo guardo", "¿Es una", "¿Es un", "¿Creo", "No existe el proyecto"), "💡 Tú eliges el siguiente paso"),
        (("Análisis en",), "🔎 Una mirada a fondo"),
        (("No hay conflictos",), "✅ Tu bóveda está en orden"),
        (("Uso:",), "💡 Prueba así"),
    )
    return next((nombre for prefijos, nombre in opciones if texto.startswith(prefijos)), "")


def formato(texto: str, encabezado: str = "") -> str:
    """Escapa contenido del usuario/modelo antes de añadir etiquetas permitidas.

    Soporta títulos, negritas, código y listas habituales de las consultas.
    Las etiquetas HTML recibidas son texto, nunca instrucciones de formato.
    """
    bloques = re.split(r"(```[^\n`]*\n[\s\S]*?```|`[^`\n]+`)", texto)
    salida = []
    for bloque in bloques:
        if re.fullmatch(r"```[^\n`]*\n[\s\S]*?```", bloque):
            salida.append("<pre>" + escape(bloque.split("\n", 1)[1][:-3]) + "</pre>")
        elif re.fullmatch(r"`[^`\n]+`", bloque):
            salida.append("<code>" + escape(bloque[1:-1]) + "</code>")
        else:
            seguro = escape(bloque)
            seguro = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"<b>\1</b>", seguro)
            seguro = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", seguro)
            seguro = re.sub(r"(?m)^[-*] ", "• ", seguro)
            salida.append(seguro)
    cuerpo = "".join(salida)
    nombre = encabezado or titulo(texto)
    return (f"<b>{escape(nombre)}</b>\n\n" if nombre else "") + cuerpo


def fragmentos(texto: str, limite: int = 3500) -> list[str]:
    """Divide antes del HTML, dejando margen al título y a caracteres UTF-16."""
    partes = []
    while texto:
        unidades = 0
        corte = 0
        for caracter in texto:
            unidades += 2 if ord(caracter) > 0xFFFF else 1
            if unidades > limite:
                break
            corte += 1
        if corte < len(texto):
            salto = texto.rfind("\n", 0, corte)
            if salto > corte // 2:
                corte = salto + 1
        partes.append(texto[:corte])
        texto = texto[corte:]
    return partes or [""]
