"""Cadena de proveedores de imágenes con failover.

Día 4 (hecho): se prueban en el orden de config.yaml; el primero que responde gana.
Si todos fallan se lanza SinProveedores con el motivo de cada uno, y quien llama
muestra el mensaje y el diagnóstico. Sin cola: la idea se guarda como nota.

Día 6 (hecho): cortacircuitos. Tras `fallos` errores seguidos, el proveedor queda en
pausa `espera_min` minutos y la cadena lo salta sin llamarlo (el usuario no espera ~55 s
por algo que va a fallar). Pasada la pausa se prueba una vez: si falla, vuelve a la pausa;
si responde, se reinicia la cuenta. El estado vive en SQLite (sobrevive a reinicios).
"Falta configurar" no cuenta como fallo: no es culpa del proveedor.

Día 6 (pendiente):
- 429 con retry-after: esperar y reintentar (máx. 3).
- Cuota diaria agotada: pausar hasta 00:00 UTC.
- Saldo agotado (402, credit_balance_exhausted...): desactivar hasta /reactivar.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Mapping, Protocol

if TYPE_CHECKING:
    from ..estado.db import Estado

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


class Cortacircuitos:
    """Cuenta fallos seguidos por proveedor y lo pone en pausa al llegar al umbral."""

    def __init__(self, estado: "Estado", fallos: int = 3, espera_min: float = 5,
                 reloj: Callable[[], float] = time.time):
        self.estado, self.umbral, self.espera_s, self.reloj = estado, fallos, espera_min * 60, reloj

    def en_pausa(self, proveedor: str) -> str | None:
        """Motivo de la pausa si el proveedor no debe llamarse ahora, o None."""
        fallos, hasta, motivo = self.estado.estado_proveedor(proveedor)
        if hasta <= self.reloj():
            return None
        hora = time.strftime("%H:%M", time.localtime(hasta))
        return f"en pausa hasta las {hora} tras {fallos} fallos seguidos (último: {motivo})"

    def fallo(self, proveedor: str, motivo: str) -> None:
        fallos = self.estado.estado_proveedor(proveedor)[0] + 1
        hasta = self.reloj() + self.espera_s if fallos >= self.umbral else 0.0
        if hasta:
            log.warning("Cortacircuitos: %s en pausa %.0f min tras %d fallos seguidos",
                        proveedor, self.espera_s / 60, fallos)
        self.estado.fijar_estado_proveedor(proveedor, fallos, hasta, motivo)

    def exito(self, proveedor: str) -> None:
        if self.estado.estado_proveedor(proveedor)[0]:
            self.estado.fijar_estado_proveedor(proveedor, 0, 0.0, "")


class CadenaImagenes:
    def __init__(self, proveedores: list[ProveedorImagen], cortacircuitos: Cortacircuitos | None = None):
        self.proveedores = proveedores
        self.cortacircuitos = cortacircuitos

    def _fallo(self, nombre: str, motivo: str) -> None:
        if self.cortacircuitos:
            self.cortacircuitos.fallo(nombre, motivo)

    async def generar(self, prompt: str) -> Imagen:
        fallos: list[tuple[str, str]] = []
        for p in self.proveedores:
            motivo = p.falta_configurar()
            if motivo:
                fallos.append((p.nombre, motivo))
                continue
            pausa = self.cortacircuitos.en_pausa(p.nombre) if self.cortacircuitos else None
            if pausa:
                fallos.append((p.nombre, pausa))
                continue
            try:
                imagen = await p.generar(prompt)
            except ErrorProveedor as e:
                log.warning("Proveedor de imágenes %s falló: %s", p.nombre, e)
                fallos.append((p.nombre, str(e)))
                self._fallo(p.nombre, str(e))
                continue
            except Exception as e:  # noqa: BLE001 - un proveedor roto no debe cortar la cadena
                log.exception("Error inesperado en el proveedor %s", p.nombre)
                fallos.append((p.nombre, f"error inesperado: {e}"))
                self._fallo(p.nombre, f"error inesperado: {e}")
                continue
            if self.cortacircuitos:
                self.cortacircuitos.exito(p.nombre)
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
                texto = await p.diagnosticar()
            except Exception as e:  # noqa: BLE001
                texto = f"error al diagnosticar: {e}"
            pausa = self.cortacircuitos.en_pausa(p.nombre) if self.cortacircuitos else None
            resultado.append((p.nombre, f"{texto} · {pausa}" if pausa else texto))
        return resultado


def crear_cadena(cfg: dict, entorno: Mapping[str, str] | None = None,
                 estado: "Estado | None" = None) -> CadenaImagenes:
    """Arma la cadena según proveedores.imagen de config.yaml; las claves vienen del entorno.

    Con `estado`, la cadena usa el cortacircuitos de config.yaml (`cortacircuitos`).
    """
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
    corte = None
    if estado is not None:
        opciones_corte = cfg.get("cortacircuitos") or {}
        corte = Cortacircuitos(estado, int(opciones_corte.get("fallos", 3)),
                               float(opciones_corte.get("espera_min", 5)))
    return CadenaImagenes(proveedores, corte)
