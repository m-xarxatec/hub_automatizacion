"""Cliente del LLM local en Ollama.

Modelo por defecto: qwen2.5:3b-instruct-q4_K_M.
Usos: segunda opinión del router (día 3), prompt de imágenes (día 4),
último respaldo de consulta (día 5).

Nunca lanza excepciones hacia afuera: si Ollama no responde, devuelve None
y quien llama sigue con el siguiente nivel de la cascada.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class Ollama:
    def __init__(self, url: str, modelo: str, timeout: float = 15,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout
        self._transport = transport  # para pruebas con httpx.MockTransport

    async def precargar(self) -> bool:
        """Carga el modelo y lo "calienta" para que el primer mensaje no espere.

        Cargar el modelo no basta: la primera respuesta con formato JSON después de
        cargarlo también tarda (hasta ~20 s en una GTX 1650). Por eso se hace una
        llamada real, corta y con esquema, al arrancar.
        """
        cuerpo = {
            "model": self.modelo,
            "messages": [{"role": "user", "content": "hola"}],
            "format": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
            "stream": False,
            "options": {"num_predict": 8},
        }
        try:
            async with httpx.AsyncClient(timeout=240, transport=self._transport) as cli:
                resp = await cli.post(f"{self.url}/api/chat", json=cuerpo)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("No se pudo precargar %s en Ollama: %s", self.modelo, e)
            return False
        log.info("Modelo %s cargado en Ollama", self.modelo)
        return True

    async def chat_json(self, sistema: str, usuario: str, esquema: dict[str, Any]) -> dict | None:
        """Pide una respuesta que cumpla `esquema` (JSON Schema). None si algo falla."""
        cuerpo = {
            "model": self.modelo,
            "messages": [{"role": "system", "content": sistema},
                         {"role": "user", "content": usuario}],
            "format": esquema,
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as cli:
                resp = await cli.post(f"{self.url}/api/chat", json=cuerpo)
                resp.raise_for_status()
            contenido = resp.json()["message"]["content"]
            datos = json.loads(contenido)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
            log.warning("Ollama no dio una respuesta válida: %s", e)
            return None
        return datos if isinstance(datos, dict) else None
