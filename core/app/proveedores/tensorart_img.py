"""tensor.art, API TAMS.

Flujo: POST /v1/jobs crea el trabajo -> GET /v1/jobs/{id} hasta SUCCESS o FAILED ->
se descarga job.successInfo.images[0].url.

Cada petición se firma con la clave privada RSA de la aplicación (SHA256withRSA, base64):
    MÉTODO \\n RUTA \\n TIMESTAMP \\n NONCE \\n CUERPO
Formato tomado del ejemplo oficial github.com/Tensor-Art/tams-signature-demo.

Créditos: 1 000 de regalo al registrarse; después, de pago. Por eso va último en la cadena.
Configuración en .env: TENSORART_ENDPOINT (el de tu aplicación, con https://) y
TENSORART_APP_ID. La clave privada va en datos/tensorart_private_key.pem (fuera del repo
y de la bóveda); otra ruta con TENSORART_PRIVATE_KEY_PATH.
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Mapping

import httpx

from .cadena import ErrorProveedor, Imagen, extension_de

RUTA_JOBS = "/v1/jobs"
ESPERA_MAX_S = 180


def firmar(metodo: str, ruta: str, cuerpo: str, app_id: str, clave_pem: bytes,
           timestamp: str | None = None, nonce: str | None = None) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or secrets.token_hex(16)
    texto = f"{metodo.upper()}\n{ruta}\n{timestamp}\n{nonce}\n{cuerpo}"
    clave = serialization.load_pem_private_key(clave_pem, password=None)
    firma = base64.b64encode(clave.sign(texto.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
    return f"TAMS-SHA256-RSA app_id={app_id},nonce_str={nonce},timestamp={timestamp},signature={firma}"


class TensorArtImagen:
    nombre = "tensorart"

    def __init__(self, opciones: dict, entorno: Mapping[str, str],
                 transport: httpx.AsyncBaseTransport | None = None):
        self.endpoint = entorno.get("TENSORART_ENDPOINT", "").strip().rstrip("/")
        if self.endpoint and not self.endpoint.startswith("http"):
            self.endpoint = f"https://{self.endpoint}"
        self.app_id = entorno.get("TENSORART_APP_ID", "").strip()
        self.ruta_clave = Path(entorno.get("TENSORART_PRIVATE_KEY_PATH", "").strip()
                               or "/datos/tensorart_private_key.pem")
        self.opciones = opciones
        self.modelo = str(opciones.get("modelo_id", ""))
        self.espera_s = 2.0
        self._transport = transport

    def falta_configurar(self) -> str | None:
        if not self.endpoint or not self.app_id:
            return "faltan TENSORART_ENDPOINT o TENSORART_APP_ID en .env"
        if not self.modelo:
            return "falta modelo_id de tensorart en config.yaml"
        if not self.ruta_clave.exists():
            return f"no existe la clave privada en {self.ruta_clave}"
        return None

    def _cuerpo(self, prompt: str) -> str:
        o = self.opciones
        datos = {
            "request_id": uuid.uuid4().hex,
            "stages": [
                {"type": "INPUT_INITIALIZE", "inputInitialize": {"seed": -1, "count": 1}},
                {"type": "DIFFUSION", "diffusion": {
                    "width": int(o.get("ancho", 768)), "height": int(o.get("alto", 1024)),
                    "prompts": [{"text": prompt}],
                    "sampler": o.get("sampler", "DPM++ 2M Karras"), "sdVae": "Automatic",
                    "steps": int(o.get("pasos", 15)), "sd_model": self.modelo,
                    "clip_skip": 2, "cfg_scale": 7,
                }},
            ],
        }
        return json.dumps(datos)

    async def _pedir(self, cli: httpx.AsyncClient, metodo: str, ruta: str, cuerpo: str = "") -> dict:
        cabeceras = {"Content-Type": "application/json", "Accept": "application/json",
                     "Authorization": firmar(metodo, ruta, cuerpo, self.app_id, self.ruta_clave.read_bytes())}
        try:
            resp = await cli.request(metodo, f"{self.endpoint}{ruta}", content=cuerpo or None,
                                     headers=cabeceras)
        except httpx.HTTPError as e:
            raise ErrorProveedor(f"sin conexión ({type(e).__name__})") from e
        if resp.status_code != 200:
            raise ErrorProveedor(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise ErrorProveedor("respuesta que no es JSON") from e

    async def generar(self, prompt: str) -> Imagen:
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as cli:
            creado = await self._pedir(cli, "POST", RUTA_JOBS, self._cuerpo(prompt))
            job_id = (creado.get("job") or {}).get("id")
            if not job_id:
                raise ErrorProveedor(f"no se creó el trabajo: {str(creado)[:200]}")
            limite = time.monotonic() + ESPERA_MAX_S
            while True:
                job = (await self._pedir(cli, "GET", f"{RUTA_JOBS}/{job_id}")).get("job") or {}
                estado = job.get("status")
                if estado == "SUCCESS":
                    break
                if estado in ("FAILED", "CANCELED"):
                    motivo = (job.get("failedInfo") or {}).get("reason", "sin motivo")
                    raise ErrorProveedor(f"trabajo {estado.lower()}: {motivo}")
                if time.monotonic() > limite:
                    raise ErrorProveedor(f"el trabajo no terminó en {ESPERA_MAX_S} s (estado {estado})")
                await asyncio.sleep(self.espera_s)
            imagenes = (job.get("successInfo") or {}).get("images") or []
            if not imagenes or not imagenes[0].get("url"):
                raise ErrorProveedor("trabajo terminado sin imagen")
            try:
                resp = await cli.get(imagenes[0]["url"])
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise ErrorProveedor(f"no se pudo descargar la imagen ({type(e).__name__})") from e
        return Imagen(resp.content, extension_de(resp.content), self.nombre, self.modelo)

    async def diagnosticar(self) -> str:
        """Pide el costo estimado de un trabajo: valida firma y cuenta sin generar nada."""
        try:
            async with httpx.AsyncClient(timeout=15, transport=self._transport) as cli:
                datos = await self._pedir(cli, "POST", f"{RUTA_JOBS}/credits", self._cuerpo("diagnostico"))
        except ErrorProveedor as e:
            return f"falla: {e}"
        except ValueError as e:  # clave PEM ilegible
            return f"la clave privada no es válida: {e}"
        return f"ok: firma aceptada; costo estimado por imagen {datos.get('credits', datos)}"
