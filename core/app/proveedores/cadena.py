"""Cadena de proveedores de imágenes con failover.

Día 4 (hecho): se prueban en el orden de config.yaml; el primero que responde gana.
Si todos fallan se lanza SinProveedores con el motivo de cada uno, y quien llama
muestra el mensaje y el diagnóstico. Sin cola: la idea se guarda como nota.

Día 6 (pendiente):
- 429 con retry-after: esperar y reintentar (máx. 3).
- Cuota diaria agotada: pausar hasta 00:00 UTC.
- Saldo agotado (402, credit_balance_exhausted...): desactivar hasta /reactivar.
- 3 fallos seguidos: cortacircuitos abierto 5 min.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Mapping, Protocol

log = logging.getLogger(__name__)


@dataclass
class Imagen:
    datos: bytes
    extension: str   # ".jpg", ".png"...
    proveedor: str
    modelo: str


class ErrorProveedor(Exception):
    """Fallo esperable de un proveedor (sin clave, error HTTP, respuesta inválida)."""


class SinProveedores(Exception):
    def __init__(self, fallos: list[tuple[str, str]]):
        self.fallos = fallos
        super().__init__("; ".join(f"{n}: {m}" for n, m in fallos) or "no hay proveedores activos")


class ProveedorImagen(Protocol):
    nombre: str

    def falta_configurar(self) -> str | None:
        """Motivo por el que no se puede usar (p. ej. falta la clave), o None si está listo."""

    async def generar(self, prompt: str) -> Imagen: ...

    async def diagnosticar(self) -> str:
        """Comprueba credenciales y conexión sin generar imágenes (no gasta cuota)."""


def extension_de(datos: bytes) -> str:
    """Detecta el formato real por sus primeros bytes."""
    if datos.startswith(b"\x89PNG"):
        return ".png"
    if datos.startswith(b"\xff\xd8"):
        return ".jpg"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return ".webp"
    return ".png"


class CadenaImagenes:
    def __init__(self, proveedores: list[ProveedorImagen]):
        self.proveedores = proveedores

    async def generar(self, prompt: str) -> Imagen:
        fallos: list[tuple[str, str]] = []
        for p in self.proveedores:
            motivo = p.falta_configurar()
            if motivo:
                fallos.append((p.nombre, motivo))
                continue
            try:
                imagen = await p.generar(prompt)
            except ErrorProveedor as e:
                log.warning("Proveedor de imágenes %s falló: %s", p.nombre, e)
                fallos.append((p.nombre, str(e)))
                continue
            except Exception as e:  # noqa: BLE001 - un proveedor roto no debe cortar la cadena
                log.exception("Error inesperado en el proveedor %s", p.nombre)
                fallos.append((p.nombre, f"error inesperado: {e}"))
                continue
            return imagen
        raise SinProveedores(fallos)

    async def diagnosticar(self) -> list[tuple[str, str]]:
        resultado = []
        for p in self.proveedores:
            motivo = p.falta_configurar()
            if motivo:
                resultado.append((p.nombre, f"sin configurar: {motivo}"))
                continue
            try:
                resultado.append((p.nombre, await p.diagnosticar()))
            except Exception as e:  # noqa: BLE001
                resultado.append((p.nombre, f"error al diagnosticar: {e}"))
        return resultado


def crear_cadena(cfg: dict, entorno: Mapping[str, str] | None = None) -> CadenaImagenes:
    """Arma la cadena según proveedores.imagen de config.yaml; las claves vienen del entorno."""
    from .chatgpt_img import ChatGPTImagen
    from .cloudflare_img import CloudflareImagen
    from .tensorart_img import TensorArtImagen

    entorno = os.environ if entorno is None else entorno
    clases = {"chatgpt": ChatGPTImagen, "cloudflare": CloudflareImagen, "tensorart": TensorArtImagen}
    proveedores: list[ProveedorImagen] = []
    for opciones in cfg.get("proveedores", {}).get("imagen", []):
        nombre = opciones.get("nombre")
        if not opciones.get("activo", True):
            continue
        if nombre not in clases:
            log.warning("Proveedor de imágenes desconocido en config.yaml: %s", nombre)
            continue
        proveedores.append(clases[nombre](opciones, entorno))
    return CadenaImagenes(proveedores)
