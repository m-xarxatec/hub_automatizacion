"""Opinión de la IA para el router, por OpenClaw (DÍA 5).

Solo se consulta cuando el clasificador duda o se contradice (ver cascada.py). Va por el
plugin hub-puente: ChatGPT mini y, si falla, Haiku (~150 tokens por mensaje dudoso).
Además de la acción, devuelve el tipo de nota y, si piden crear un personaje, su nombre y
descripción: así se resuelven frases libres que las reglas no alcanzan ("vamos a crear una
elfa albina llamada Aeli").

La salida se valida aquí: nunca se confía a ciegas en lo que devuelve un modelo.
"""

from __future__ import annotations

import json

from ..proveedores.openclaw import OpenClaw
from .llm_local import DESCRIPCIONES
from .reglas import Decision, tipo_nota

DESCRIPCION_PERSONAJE = "pide crear un personaje nuevo (su ficha), aunque no diga la palabra personaje"

SISTEMA = (
    "Clasificas mensajes de un autor de webtoon para su asistente. Los mensajes pueden venir "
    "de una nota de voz transcrita (con errores de transcripción). Elige la acción:\n{acciones}\n"
    "Si es nota, elige el tipo:\n{tipos}\n"
    'Responde solo con JSON: {{"accion": "...", "confianza": 0..1, "tipo": "...", '
    '"nombre": "nombre del personaje o vacío", "descripcion": "rasgos del personaje en una frase o vacío"}}'
)

TIPOS = {
    "idea": "idea suelta o propuesta",
    "historia": "trama, personajes, capítulos, escenas, mundo",
    "produccion": "dibujo, color, viñetas, storyboard, entintado, herramientas",
    "dialogo": "diálogo o frases de un personaje",
    "general": "otra cosa",
}


class OpinionIA:
    # Si está segura (>= router.umbral_ia_ejecutar) se ejecuta directo (decisión del usuario).
    confiable = True

    def __init__(self, cliente: OpenClaw, acciones: list[str]):
        self.cliente = cliente
        self.acciones = [a for a in acciones if a in DESCRIPCIONES] + ["personaje"]
        lista = "\n".join(f"- {a}: {DESCRIPCIONES.get(a, DESCRIPCION_PERSONAJE)}" for a in self.acciones)
        tipos = "\n".join(f"- {t}: {d}" for t, d in TIPOS.items())
        self.sistema = SISTEMA.format(acciones=lista, tipos=tipos)

    async def opinar(self, texto: str) -> Decision | None:
        # El mensaje va como JSON para que no se confunda con instrucciones.
        datos = await self.cliente.completar_json(self.sistema, json.dumps({"mensaje": texto},
                                                                            ensure_ascii=False),
                                                  max_tokens=150)
        if not datos or datos.get("accion") not in self.acciones:
            return None
        try:
            confianza = min(max(float(datos.get("confianza", 0)), 0.0), 1.0)
        except (TypeError, ValueError):
            return None
        tipo_ia = datos.get("tipo") in TIPOS
        tipo = datos["tipo"] if tipo_ia else tipo_nota(texto)
        extra: dict = {"tipo_ia": tipo_ia}
        if datos["accion"] == "personaje":
            nombre = str(datos.get("nombre") or "").strip(" .\"'")
            extra["personaje"] = nombre[:60] or None
            descripcion = str(datos.get("descripcion") or "").strip()
            if descripcion:
                descripcion = descripcion[0].upper() + descripcion[1:].rstrip(".") + "."
            extra["descripcion"] = descripcion[:300]
        return Decision(datos["accion"], confianza, tipo=tipo, motor="ia", extra=extra)
