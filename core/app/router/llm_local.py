"""Segunda opinión del router con el LLM local (DÍA 3).

Solo se consulta cuando el clasificador y las reglas dudan. La salida está
restringida por esquema JSON a las acciones de config.yaml y además se valida
aquí: nunca se confía a ciegas en lo que devuelve un modelo.
"""

from __future__ import annotations

from ..proveedores.ollama import Ollama
from .reglas import Decision, tipo_nota

DESCRIPCIONES = {
    "nota": "guardar una idea, dato de la historia, personaje, escena o diálogo",
    "tarea": "algo pendiente que el usuario debe hacer",
    "imagen": "pide generar una imagen, boceto o ilustración",
    "consulta": "pregunta de conocimiento general o técnica que se responde en el momento",
    "analisis": "pide evaluar o revisar a fondo la historia o las notas del proyecto",
    "busqueda": "pide buscar o investigar información o referencias en internet",
}

SISTEMA = (
    "Clasificas mensajes de un autor de webtoon para su asistente. "
    "Elige la acción que mejor describe el mensaje:\n{lista}\n"
    "Responde solo con JSON. confianza va de 0 a 1."
)


class LLMLocal:
    # Un modelo de 3B se equivoca más: su opinión nunca se ejecuta sin confirmar.
    confiable = False

    def __init__(self, cliente: Ollama, acciones: list[str]):
        self.cliente = cliente
        self.acciones = [a for a in acciones if a in DESCRIPCIONES]
        lista = "\n".join(f"- {a}: {DESCRIPCIONES[a]}" for a in self.acciones)
        self.sistema = SISTEMA.format(lista=lista)
        self.esquema = {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "enum": self.acciones},
                "confianza": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["accion", "confianza"],
        }

    async def opinar(self, texto: str) -> Decision | None:
        datos = await self.cliente.chat_json(self.sistema, texto, self.esquema)
        if not datos or datos.get("accion") not in self.acciones:
            return None
        try:
            confianza = min(max(float(datos.get("confianza", 0)), 0.0), 1.0)
        except (TypeError, ValueError):
            return None
        return Decision(datos["accion"], confianza, tipo=tipo_nota(texto), motor="llm local")
