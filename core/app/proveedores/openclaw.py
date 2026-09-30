"""Cliente de OpenClaw para core (DÍA 5).

No usa el agente de OpenClaw (/v1/chat/completions): su prompt propio suma ~5.700 tokens
a cada mensaje. Llama al plugin del hub (openclaw/plugins/hub-puente), que manda al
modelo solo nuestro prompt: POST {OPENCLAW_URL}/hub/completar con el token del gateway.

Cadena (decisión 3, config.yaml → proveedores.consulta): ChatGPT mini por suscripción
con el menor razonamiento que acepta ("low") → Claude Haiku por Claude Code sin
pensamiento. Haiku es un programa (CLI), no una API: va en modo "aislado", que admite
un solo mensaje, así que el historial se le pasa aplanado en un texto.

Como el cliente de Ollama, nunca lanza excepciones hacia afuera: si ningún modelo
responde devuelve None y quien llama sigue con el siguiente nivel de la cascada.
El motivo del último fallo queda en `ultimo_error` (para explicarlo al usuario).

Modo análisis (decisión 4): `completar_con` usa un único modelo, el que eligió el usuario,
con más tiempo de espera; si falla no prueba otro por su cuenta.

Uso (2026-09-30, /tokens y /estado): cada respuesta se pasa a `contador(funcion, respuesta)`, que
la suma en SQLite. `funcion` es la del cliente (intérprete, redactor…) o la que se indique en la
llamada (el cliente de la consulta también hace los análisis). Claude por Claude Code informa mal
los tokens de salida ("2" en un análisis largo): si lo informado es absurdo, se estima por el largo.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import httpx

log = logging.getLogger(__name__)

ROLES = {"user": "Usuario", "assistant": "Asistente"}


@dataclass(frozen=True)
class Nivel:
    modelo: str
    razonamiento: str
    aislado: bool = False


@dataclass(frozen=True)
class Respuesta:
    texto: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    salida_estimada: bool = False   # la informada era absurda: se estimó por el largo del texto


# Recibe (función, respuesta) por cada llamada que responde; lo usa /tokens.
Contador = Callable[[str, Respuesta], None]
CARACTERES_POR_TOKEN = 3.5   # el mismo cálculo aproximado que el modo análisis


def estimar_salida(texto: str) -> int:
    return math.ceil(len(texto) / CARACTERES_POR_TOKEN)


CADENA_POR_DEFECTO = (
    Nivel("openai/gpt-6-luna", "low"),
    Nivel("claude-cli/claude-haiku-4-5", "off", aislado=True),
)


def cadena_desde_config(opciones: Iterable[dict[str, Any]] | None) -> tuple[Nivel, ...]:
    """Convierte proveedores.consulta de config.yaml; ignora entradas incompletas."""
    niveles = []
    for o in opciones or []:
        if isinstance(o, dict) and o.get("modelo") and o.get("razonamiento"):
            niveles.append(Nivel(str(o["modelo"]), str(o["razonamiento"]), bool(o.get("aislado"))))
    return tuple(niveles) or CADENA_POR_DEFECTO


def aplanar(mensajes: list[tuple[str, str]]) -> str:
    """Historial en un solo texto, para el modo aislado (un único mensaje)."""
    if len(mensajes) == 1:
        return mensajes[0][1]
    previos = "\n".join(f"{ROLES.get(rol, rol)}: {texto}" for rol, texto in mensajes[:-1])
    return f"Conversación previa:\n{previos}\n\nMensaje actual del usuario:\n{mensajes[-1][1]}"


def quitar_cercas(texto: str) -> str:
    """Quita ```json ... ``` si el modelo envolvió la respuesta (Haiku lo hace)."""
    t = texto.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


class OpenClaw:
    def __init__(self, url: str, token: str, cadena: Iterable[Nivel] = CADENA_POR_DEFECTO,
                 timeout: float = 60, transport: httpx.AsyncBaseTransport | None = None,
                 funcion: str = "consulta", contador: Contador | None = None):
        self.url = url.rstrip("/")
        self.token = token
        self.cadena = tuple(cadena)
        self.timeout = timeout
        self._transport = transport  # para pruebas con httpx.MockTransport
        self.ultimo_error: str | None = None
        self.funcion = funcion        # para el registro de uso (/tokens)
        self.contador = contador

    def falta_configurar(self) -> str | None:
        return None if self.token else "falta OPENCLAW_GATEWAY_TOKEN en .env"

    async def completar(self, mensajes: str | list[tuple[str, str]], sistema: str | None = None,
                        max_tokens: int | None = None, funcion: str | None = None) -> Respuesta | None:
        """Respuesta del primer modelo de la cadena que conteste. None si ninguno.

        `mensajes` es el texto del usuario o una lista [(rol, texto)] con rol "user" o
        "assistant"; el último debe ser del usuario.
        """
        if self.falta_configurar():
            log.warning("OpenClaw sin usar: %s", self.falta_configurar())
            return None
        lista = [("user", mensajes)] if isinstance(mensajes, str) else list(mensajes)
        if not lista or lista[-1][0] != "user":
            log.warning("OpenClaw: el último mensaje debe ser del usuario")
            return None
        for nivel in self.cadena:
            respuesta = await self._pedir(nivel, lista, sistema, max_tokens, funcion=funcion)
            if respuesta:
                return respuesta
        return None

    async def completar_con(self, nivel: Nivel, mensaje: str, sistema: str | None = None,
                            max_tokens: int | None = None, tiempo_max_s: float | None = None,
                            funcion: str | None = None) -> Respuesta | None:
        """Un solo modelo, sin cadena. None si falla; el motivo queda en `ultimo_error`."""
        self.ultimo_error = None
        if self.falta_configurar():
            self.ultimo_error = self.falta_configurar()
            return None
        return await self._pedir(nivel, [("user", mensaje)], sistema, max_tokens, tiempo_max_s, funcion)

    async def completar_json(self, sistema: str, texto: str,
                             max_tokens: int | None = None) -> dict | None:
        """Pide un objeto JSON; prueba el siguiente modelo si la respuesta no lo es."""
        for nivel in self.cadena:
            respuesta = await self._pedir(nivel, [("user", texto)], sistema, max_tokens)
            if not respuesta:
                continue
            try:
                datos = json.loads(quitar_cercas(respuesta.texto))
            except ValueError:
                datos = None
            if isinstance(datos, dict):
                return datos
            log.warning("OpenClaw: %s no devolvió un objeto JSON", nivel.modelo)
        return None

    async def _pedir(self, nivel: Nivel, mensajes: list[tuple[str, str]], sistema: str | None,
                     max_tokens: int | None, tiempo_max_s: float | None = None,
                     funcion: str | None = None) -> Respuesta | None:
        if self.falta_configurar():
            return None
        cuerpo: dict[str, Any] = {"modelo": nivel.modelo, "razonamiento": nivel.razonamiento}
        if nivel.aislado:
            cuerpo.update(aislado=True, mensaje=aplanar(mensajes))
        else:
            cuerpo["mensajes"] = [{"rol": rol, "texto": texto} for rol, texto in mensajes]
        if sistema:
            cuerpo["sistema"] = sistema
        if max_tokens:
            cuerpo["max_tokens"] = max_tokens
        espera = self.timeout
        if tiempo_max_s:
            cuerpo["tiempo_max_s"] = tiempo_max_s
            espera = tiempo_max_s + 15   # margen: que corte el gateway y explique el motivo
        try:
            async with httpx.AsyncClient(timeout=espera, transport=self._transport) as cli:
                resp = await cli.post(f"{self.url}/hub/completar", json=cuerpo,
                                      headers={"Authorization": f"Bearer {self.token}"})
            datos = resp.json()
            if resp.status_code != 200:
                detalle = datos.get("error", "") if isinstance(datos, dict) else ""
                log.warning("OpenClaw %s: HTTP %s %s", nivel.modelo, resp.status_code, detalle)
                self.ultimo_error = f"HTTP {resp.status_code} {detalle}".strip()
                return None
            texto = str(datos.get("texto") or "").strip()
            uso = datos.get("uso") or {}
        except httpx.TimeoutException:
            log.warning("OpenClaw %s: tiempo de espera agotado (%s s)", nivel.modelo, espera)
            self.ultimo_error = f"no respondió en {int(espera)} s"
            return None
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            log.warning("OpenClaw %s no respondió: %s", nivel.modelo, e)
            self.ultimo_error = f"sin conexión con OpenClaw ({type(e).__name__})"
            return None
        if not texto:
            log.warning("OpenClaw %s devolvió una respuesta vacía", nivel.modelo)
            self.ultimo_error = "respuesta vacía"
            return None
        entrada = int(uso.get("inputTokens") or 0) + int(uso.get("cacheReadTokens") or 0)
        salida = int(uso.get("outputTokens") or 0)
        estimada = salida * 4 < estimar_salida(texto)   # menos de un cuarto de lo que mide el texto
        log.info("OpenClaw %s: %s tokens de entrada, %s de salida%s, %s ms", nivel.modelo, entrada, salida,
                 f" (se registra ~{estimar_salida(texto)} estimada)" if estimada else "", datos.get("ms"))
        respuesta = Respuesta(texto, str(datos.get("modelo") or nivel.modelo), entrada,
                              estimar_salida(texto) if estimada else salida, estimada)
        if self.contador is not None:
            try:
                self.contador(funcion or self.funcion, respuesta)
            except Exception:  # noqa: BLE001 - contar nunca debe romper una respuesta
                log.exception("No se pudo registrar el uso de %s", nivel.modelo)
        return respuesta
