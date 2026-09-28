"""ChatGPT por suscripción (OAuth de Codex) a través de OpenClaw (DÍA 5).

Primer proveedor de la cadena: usa lo que ya se paga, sin costo por imagen.
POST {OPENCLAW_URL}/hub/imagen (plugin hub-puente, token del gateway) con el prompt, el
modelo (openai/gpt-image-2), la calidad y el tamaño. OpenClaw llama a
api.runtime.imageGeneration y devuelve la imagen en base64: no la guarda en disco, la
guarda core en la bóveda. Medido: ~55 s por imagen de 1024×1536 en calidad "low".
"""

from __future__ import annotations

import base64
import binascii
from typing import Mapping

import httpx

from .cadena import ErrorProveedor, Imagen, extension_de


class ChatGPTImagen:
    nombre = "chatgpt"

    def __init__(self, opciones: dict, entorno: Mapping[str, str],
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = entorno.get("OPENCLAW_URL", "http://openclaw:18789").rstrip("/")
        self.token = entorno.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
        modelo = str(opciones.get("modelo", "gpt-image-2"))
        self.modelo = modelo if "/" in modelo else f"openai/{modelo}"
        self.calidad = str(opciones.get("calidad", "low"))
        self.tamano = str(opciones.get("tamano", "1024x1536"))
        self._transport = transport

    def falta_configurar(self) -> str | None:
        return None if self.token else "falta OPENCLAW_GATEWAY_TOKEN en .env (OpenClaw)"

    def _cliente(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport,
                                 headers={"Authorization": f"Bearer {self.token}"})

    async def generar(self, prompt: str) -> Imagen:
        cuerpo = {"prompt": prompt[:4000], "modelo": self.modelo, "calidad": self.calidad,
                  "tamano": self.tamano}
        try:
            async with self._cliente(200) as cli:
                resp = await cli.post(f"{self.url}/hub/imagen", json=cuerpo)
            datos_json = resp.json()
        except httpx.HTTPError as e:
            raise ErrorProveedor(f"OpenClaw no responde ({type(e).__name__})") from e
        except ValueError as e:
            raise ErrorProveedor(f"respuesta inválida de OpenClaw (HTTP {resp.status_code})") from e
        if resp.status_code != 200:
            raise ErrorProveedor(f"HTTP {resp.status_code}: {str(datos_json.get('error', ''))[:200]}")
        try:
            datos = base64.b64decode(datos_json["imagen"], validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error) as e:
            raise ErrorProveedor("respuesta sin imagen válida") from e
        if not datos:
            raise ErrorProveedor("imagen vacía")
        modelo = str(datos_json.get("modelo") or self.modelo).split("/")[-1]
        return Imagen(datos, extension_de(datos), self.nombre, modelo)

    async def diagnosticar(self) -> str:
        """Petición vacía: comprueba OpenClaw, el token y el plugin sin generar (no gasta cuota)."""
        try:
            async with self._cliente(10) as cli:
                resp = await cli.post(f"{self.url}/hub/imagen", json={})
        except httpx.HTTPError as e:
            return f"OpenClaw no responde ({type(e).__name__})"
        return {400: f"ok: OpenClaw y el plugin responden ({self.modelo}, calidad {self.calidad})",
                401: "OpenClaw rechaza el token (OPENCLAW_GATEWAY_TOKEN)",
                404: "falta el plugin hub-puente o su ruta /hub/imagen"}.get(
                    resp.status_code, f"respuesta inesperada de OpenClaw (HTTP {resp.status_code})")
