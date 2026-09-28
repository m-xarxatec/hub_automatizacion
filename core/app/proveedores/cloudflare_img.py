"""Cloudflare Workers AI, FLUX.1 schnell.

POST https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell
Cuerpo: {"prompt": ..., "steps": 1-8}. Respuesta: {"result": {"image": <JPEG en base64>}}.
Plan gratuito: 10 000 neuronas diarias; se reinicia a las 00:00 UTC.
Claves en .env: CLOUDFLARE_ACCOUNT_ID y CLOUDFLARE_API_TOKEN (permiso Workers AI).
"""

from __future__ import annotations

import base64
import binascii
from typing import Mapping

import httpx

from .cadena import ErrorProveedor, Imagen, extension_de

BASE = "https://api.cloudflare.com/client/v4"


def motivo_http(resp: httpx.Response) -> str:
    """Mensaje legible de un error HTTP de Cloudflare."""
    try:
        errores = resp.json().get("errors") or []
        detalle = errores[0].get("message", "") if errores else ""
    except (ValueError, AttributeError):
        detalle = resp.text[:200]
    return f"HTTP {resp.status_code}" + (f": {detalle}" if detalle else "")


class CloudflareImagen:
    nombre = "cloudflare"

    def __init__(self, opciones: dict, entorno: Mapping[str, str],
                 transport: httpx.AsyncBaseTransport | None = None):
        self.cuenta = entorno.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.token = entorno.get("CLOUDFLARE_API_TOKEN", "").strip()
        self.modelo = opciones.get("modelo", "flux-1-schnell")
        self.pasos = max(1, min(int(opciones.get("pasos", 4)), 8))
        self._transport = transport

    def falta_configurar(self) -> str | None:
        if not self.cuenta or not self.token:
            return "faltan CLOUDFLARE_ACCOUNT_ID o CLOUDFLARE_API_TOKEN en .env"
        return None

    def _cliente(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport,
                                 headers={"Authorization": f"Bearer {self.token}"})

    async def generar(self, prompt: str) -> Imagen:
        url = f"{BASE}/accounts/{self.cuenta}/ai/run/@cf/black-forest-labs/{self.modelo}"
        try:
            async with self._cliente(90) as cli:
                resp = await cli.post(url, json={"prompt": prompt[:2048], "steps": self.pasos})
        except httpx.HTTPError as e:
            raise ErrorProveedor(f"sin conexión ({type(e).__name__})") from e
        if resp.status_code != 200:
            raise ErrorProveedor(motivo_http(resp))
        try:
            datos = base64.b64decode(resp.json()["result"]["image"], validate=True)
        except (ValueError, KeyError, TypeError, binascii.Error) as e:
            raise ErrorProveedor("respuesta sin imagen válida") from e
        return Imagen(datos, extension_de(datos), self.nombre, self.modelo)

    async def diagnosticar(self) -> str:
        """Verifica el token sin generar nada (no gasta neuronas)."""
        try:
            async with self._cliente(10) as cli:
                resp = await cli.get(f"{BASE}/user/tokens/verify")
                if resp.status_code != 200:  # los tokens de cuenta se verifican en otra ruta
                    resp = await cli.get(f"{BASE}/accounts/{self.cuenta}/tokens/verify")
        except httpx.HTTPError as e:
            return f"sin conexión con Cloudflare ({type(e).__name__})"
        if resp.status_code != 200:
            return f"token rechazado ({motivo_http(resp)})"
        estado = (resp.json().get("result") or {}).get("status", "?")
        return f"ok: token {estado}" if estado == "active" else f"token en estado {estado}"
