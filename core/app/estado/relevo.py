"""Relevo entre servidores: un equipo de guardia cede el bot y lo retoma solo (2026-09-30).

Caso de uso: la PC de casa queda encendida como servidor. En una presentación se levanta el stack en
la laptop, que toma el bot; la PC pasa a espera (sigue sincronizando la bóveda con Syncthing) y, cuando
la laptop se apaga, vuelve a atender sola. Los equipos de guardia se listan en `relevo.ceden`.

Dos señales:
- El error 409 de Telegram es el candado real: solo un proceso puede leer el bot. Cuando la laptop
  empieza a leer, la petición pendiente de la PC recibe el 409 y la PC cede en uno o dos segundos.
  No depende de Syncthing.
- El latido en `_hub/` (Syncthing, ~10-20 s) es el tablón: quién atiende, quién espera y quién se apagó.
  Con él la laptop sabe que puede tomar el bot y la PC sabe cuándo retomarlo.

Antes de retomar el bot, el de guardia escucha a Telegram unos segundos (sondeo): si otro lo está
leyendo, las peticiones de los dos chocan y llega un 409. Una petición instantánea no basta para
saberlo: la más nueva siempre gana.

En espera el proceso sigue vivo (no se reinicia): escribe su latido, no lee Telegram y no avisa de
conflictos de Syncthing. Lo que estaba procesando al ceder termina y responde (enviar mensajes no
necesita leer el bot).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramAPIError, TelegramConflictError
from aiogram.methods import GetUpdates

from . import latido
from .latido import ACTIVO, APAGADO, ESPERA

log = logging.getLogger(__name__)

PAUSA_MAX_S = 30 * 60   # entre sondeos fallidos sin latido que los explique: 3, 6, 12, 24 y 30 min
SIN_RED_S = 30          # si Telegram no responde al sondear, se vuelve a probar en medio minuto
# Tras un "apagado", Telegram puede guardar unos segundos la última lectura del que se fue (aiogram
# espera hasta 10 s cada una): un 409 entonces se reintenta pronto, no con la pausa larga.
REINTENTO_CORTO_S = 12
REINTENTOS_TRAS_APAGADO = 3


def hace(segundos: float) -> str:
    s = max(0, int(segundos))
    if s < 90:
        return f"{s} s"
    if s < 90 * 60:
        return f"{round(s / 60)} min"
    if s < 36 * 3600:
        return f"{round(s / 3600)} h"
    return f"{round(s / 86400)} d"


def vigencia_proyectos(d: dict) -> float:
    """Hasta cuándo vale el proyecto activo que trae un latido: si el equipo atiende, hasta su último
    latido; si no, hasta que dejó de atender."""
    if latido.estado_de(d) == ACTIVO:
        return float(d.get("epoch", 0) or 0)
    return float(d.get("desde", d.get("epoch", 0)) or 0)


class Observador:
    """Edad de los latidos ajenos medida con el reloj propio.

    La primera vez se usa la hora que escribió el otro equipo; después, cuánto hace que su latido
    cambió según este equipo. Así un reloj desfasado (p. ej. la laptop tras suspenderse) no engaña
    al relevo.
    """

    def __init__(self) -> None:
        self._visto: dict[str, tuple[float, float]] = {}   # servidor -> (epoch leído, cuándo cambió)

    def edad(self, d: dict, ahora: float) -> float:
        nombre, epoch = str(d.get("servidor")), float(d.get("epoch", 0) or 0)
        previo = self._visto.get(nombre)
        if previo is not None and previo[0] == epoch:
            return ahora - previo[1]
        cambio = min(ahora, epoch) if previo is None else ahora
        self._visto[nombre] = (epoch, cambio)
        return ahora - cambio


def a_quien_ceder(otros: list[dict], yo: str, guardias: set[str], edad: Callable[[dict], float],
                  vigencia_s: float) -> dict | None:
    """El latido del equipo al que `yo` debe dejarle el bot, o None.

    Solo ceden los equipos de guardia, y solo ante otro que atiende (latido reciente y `activo`).
    Entre dos de guardia atiende el de nombre menor, para que no se cedan el bot el uno al otro.
    """
    if yo not in guardias:
        return None
    candidatos = []
    for d in otros:
        nombre = str(d.get("servidor"))
        if nombre == yo or latido.estado_de(d) != ACTIVO or edad(d) >= vigencia_s:
            continue
        if (nombre in guardias or d.get("cede")) and nombre > yo:
            continue
        candidatos.append(d)
    return min(candidatos, key=edad, default=None)


def adoptar_en(estado: Any, existentes: Callable[[], list[str]],
               usuarios: frozenset[int]) -> Callable[[dict[int, str]], dict[int, str]]:
    """Función que fija en el SQLite de este equipo el proyecto activo que traía el otro, solo para
    usuarios autorizados y proyectos que ya están en la bóveda. Devuelve lo que cambió."""
    def adoptar(proyectos: dict[int, str]) -> dict[int, str]:
        hay = set(existentes())
        hechos = {}
        for chat, proyecto in proyectos.items():
            if chat in usuarios and proyecto in hay and estado.proyecto_activo(chat) != proyecto:
                estado.fijar_proyecto(chat, proyecto)
                hechos[chat] = proyecto
        return hechos
    return adoptar


class VigiaConflicto(BaseRequestMiddleware):
    """Middleware de la sesión del bot: avisa al relevo cuando Telegram corta nuestra lectura (409)."""

    def __init__(self, al_conflicto: Callable[[], None]):
        self.al_conflicto = al_conflicto

    async def __call__(self, make_request, bot, method):  # type: ignore[no-untyped-def]
        try:
            return await make_request(bot, method)
        except TelegramConflictError:
            if isinstance(method, GetUpdates):
                self.al_conflicto()
            raise


class Relevo:
    """Decide cuándo este equipo lee el bot de Telegram y cuándo espera (ver el docstring del módulo)."""

    def __init__(self, interna: Path, nombre: str, cfg: dict[str, Any], vigencia_s: float,
                 intervalo_s: float):
        self.interna, self.nombre = interna, nombre
        self.guardias = {str(n) for n in (cfg.get("ceden") or [])}
        self.guardia = nombre in self.guardias
        self.revisar_s = float(cfg.get("revisar_s", 5))
        self.sondeo_s = int(cfg.get("sondeo_s", 8))
        self.avisar = bool(cfg.get("avisar", True))
        self.llevar_proyecto = bool(cfg.get("llevar_proyecto", True))
        self.vigencia_s, self.intervalo_s = float(vigencia_s), float(intervalo_s)
        self.estado, self.desde = ESPERA, time.time()   # nadie atiende hasta tomar el bot
        self.observador = Observador()
        self.salir, self.ceder = asyncio.Event(), asyncio.Event()
        self.motivo = ""
        self.desplazado = False   # el de guardia esperó a otro: al volver, avisa
        self.pausa_s = 0.0
        self.no_antes_de = 0.0    # antes de esta hora no se sondea
        self.reintentos = 0       # sondeos con reintento corto que quedan tras un "apagado"
        self.reintento_s = REINTENTO_CORTO_S
        self._apagados: set[tuple[str, float]] = set()   # latidos "apagado" ya vistos
        self._esperando_a: str | None = None
        self._aviso_409 = False
        propio = latido.por_servidor(interna).get(nombre)
        self.proyectos_hasta = vigencia_proyectos(propio) if propio else 0.0
        # Se conectan en main (conectar): el bot, el SQLite de estado y la bóveda.
        self.usuarios: frozenset[int] = frozenset()
        self.proyectos: Callable[[], dict[int, str]] | None = None
        self.adoptar: Callable[[dict[int, str]], dict[int, str]] | None = None
        self.enviar: Callable[[int, str], Awaitable[Any]] | None = None

    def conectar(self, bot: Bot, usuarios: frozenset[int] = frozenset(),
                 proyectos: Callable[[], dict[int, str]] | None = None,
                 adoptar: Callable[[dict[int, str]], dict[int, str]] | None = None,
                 enviar: Callable[[int, str], Awaitable[Any]] | None = None) -> None:
        bot.session.middleware(VigiaConflicto(self.al_conflicto))
        self.usuarios, self.proyectos, self.adoptar = frozenset(usuarios), proyectos, adoptar
        self.enviar = enviar or bot.send_message

    # --- latidos -------------------------------------------------------------------------------
    @property
    def atendiendo(self) -> bool:
        return self.estado == ACTIVO

    def otros(self) -> list[dict]:
        return [d for n, d in latido.por_servidor(self.interna).items() if n != self.nombre]

    def edad(self, d: dict, ahora: float | None = None) -> float:
        return self.observador.edad(d, time.time() if ahora is None else ahora)

    def es_guardia(self, d: dict) -> bool:
        return str(d.get("servidor")) in self.guardias or bool(d.get("cede"))

    def a_quien_ceder(self, ahora: float) -> dict | None:
        return a_quien_ceder(self.otros(), self.nombre, self.guardias, lambda d: self.edad(d, ahora),
                             self.vigencia_s)

    def choque_al_arrancar(self) -> str | None:
        """Como `latido.conflicto`, pero los de guardia nunca chocan: si otro atiende, esperan."""
        if self.guardia:
            return None
        return latido.conflicto(self.interna, self.nombre, int(self.vigencia_s), ceden=self.guardias)

    def latir(self) -> None:
        proyectos = None
        if self.llevar_proyecto and self.proyectos:
            try:
                proyectos = self.proyectos()
            except Exception:  # noqa: BLE001 - sin proyectos el latido sigue sirviendo
                log.warning("Relevo: no se pudo leer el proyecto activo para el latido", exc_info=True)
        try:
            latido.escribir(self.interna, self.nombre, estado=self.estado, desde=self.desde,
                            cede=self.guardia, proyectos=proyectos)
        except OSError as e:
            log.warning("No se pudo escribir el latido: %s", e)

    async def bucle_latido(self) -> None:
        while True:
            self.latir()
            await asyncio.sleep(self.intervalo_s)

    def resumen_otros(self, ahora: float | None = None) -> str | None:
        """"Otros servidores: pc-casa en espera, de guardia (latido hace 20 s)" para /estado."""
        ahora = time.time() if ahora is None else ahora
        partes = []
        for d in sorted(self.otros(), key=lambda d: str(d.get("servidor"))):
            n, edad, estado = d["servidor"], self.edad(d, ahora), latido.estado_de(d)
            if estado == APAGADO:
                partes.append(f"{n} apagado hace {hace(edad)}")
            elif edad >= self.vigencia_s:
                partes.append(f"{n} sin latir desde hace {hace(edad)}")
            elif estado == ESPERA:
                guardia = ", de guardia" if self.es_guardia(d) else ""
                partes.append(f"{n} en espera{guardia} (latido hace {hace(edad)})")
            else:
                partes.append(f"{n} atendiendo (latido hace {hace(edad)})")
        return ("Otros servidores: " + "; ".join(partes)) if partes else None

    # --- ciclo ---------------------------------------------------------------------------------
    def al_conflicto(self) -> None:
        """Telegram cortó nuestra lectura porque otro proceso lee el bot."""
        if self.estado != ACTIVO:
            return
        if self.guardia:
            if not self.ceder.is_set():
                self.motivo = "otro equipo empezó a leer el bot (409 de Telegram)"
                self.ceder.set()
        elif not self._aviso_409:
            self._aviso_409 = True
            log.warning("Relevo: otro proceso intenta leer el bot (409). Sigo atendiendo yo; si es un "
                        "equipo de guardia, cederá solo.")

    def detener(self) -> None:
        self.salir.set()

    async def correr(self, dp: Dispatcher, bot: Bot, allowed_updates: list[str] | None = None,
                     senales: bool = True) -> None:
        """Atiende o espera hasta la señal de apagado; al salir deja el latido en `apagado`."""
        if senales:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                    loop.add_signal_handler(sig, self.detener)
        try:
            while not self.salir.is_set():
                if self.guardia and not await self._esperar_turno(bot):
                    break
                await self._atender(dp, bot, allowed_updates)
                if not self.guardia:
                    break   # el que no es de guardia nunca cede: solo sale al apagarse
        finally:
            self._cambiar(APAGADO)
            log.info("Relevo: %s se apaga (latido en 'apagado')", self.nombre)

    def _cambiar(self, estado: str) -> None:
        self.estado, self.desde = estado, time.time()
        self.latir()

    async def _dormir(self, segundos: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.salir.wait(), timeout=segundos)

    async def _esperar_turno(self, bot: Bot) -> bool:
        """El de guardia espera mientras otro atiende. True cuando puede atender; False al apagarse."""
        while not self.salir.is_set():
            ahora = time.time()
            self._ver_apagados(ahora)
            otro = self.a_quien_ceder(ahora)
            if otro is not None:
                self.desplazado = True
                if self._esperando_a != otro["servidor"]:
                    self._esperando_a = otro["servidor"]
                    log.info("Relevo: %s atiende el bot; %s queda en espera (de guardia)",
                             otro["servidor"], self.nombre)
            elif ahora >= self.no_antes_de:
                resultado = await self._sondear(bot)
                if resultado == "libre":
                    return True
                if resultado == "ocupado" and self.reintentos > 0:
                    self.reintentos -= 1
                    self.no_antes_de = time.time() + self.reintento_s
                    log.info("Relevo: el bot sigue ocupado (Telegram aún puede guardar la última lectura del "
                             "equipo que se apagó); reintento en %d s", self.reintento_s)
                elif resultado == "ocupado":
                    self._pausar(time.time())
                elif resultado == "sin_red":
                    self.no_antes_de = time.time() + SIN_RED_S
            await self._dormir(self.revisar_s)
        return False

    def _ver_apagados(self, ahora: float) -> None:
        """Un equipo que acaba de apagarse (latido nuevo en `apagado`): se prueba ya, sin esperar la pausa,
        y con reintentos cortos."""
        for d in self.otros():
            clave = (str(d.get("servidor")), float(d.get("epoch", 0) or 0))
            if latido.estado_de(d) != APAGADO or clave in self._apagados:
                continue
            self._apagados.add(clave)
            if self.edad(d, ahora) < self.vigencia_s:
                self.no_antes_de, self.reintentos = ahora, REINTENTOS_TRAS_APAGADO

    async def _sondear(self, bot: Bot) -> str:
        """'libre', 'ocupado' (otro lee el bot), 'sin_red' o 'apagando'. No confirma nada: lo que llegue
        lo recibe después quien atienda."""
        log.info("Relevo: nadie atiende según los latidos; escucho a Telegram %d s para ver si el bot "
                 "está libre", self.sondeo_s)
        sondeo = asyncio.ensure_future(bot.get_updates(limit=1, timeout=self.sondeo_s))
        salir = asyncio.ensure_future(self.salir.wait())
        try:
            await asyncio.wait({sondeo, salir}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            salir.cancel()
        if not sondeo.done():   # llegó la orden de apagado: Docker da solo 10 s para escribir "apagado"
            sondeo.cancel()
            return "apagando"
        try:
            sondeo.result()
        except TelegramConflictError:
            return "ocupado"
        except TelegramAPIError as e:   # red caída, error 5xx de Telegram…
            log.warning("Relevo: Telegram no responde (%s); vuelvo a probar en %d s", e, SIN_RED_S)
            return "sin_red"
        return "libre"

    def _pausar(self, ahora: float) -> None:
        self.pausa_s = min(max(self.pausa_s * 2, self.vigencia_s), PAUSA_MAX_S)
        self.no_antes_de = ahora + self.pausa_s
        log.warning("Relevo: otro proceso lee el bot y ningún latido lo explica (¿Syncthing sin conexión "
                    "con ese equipo?). Sigo en espera; vuelvo a probar en %s", hace(self.pausa_s))

    async def _atender(self, dp: Dispatcher, bot: Bot, allowed_updates: list[str] | None) -> None:
        ahora = time.time()
        otros = self.otros()
        self._adoptar_proyectos(otros)
        texto = self._texto_toma(otros, ahora)
        self.ceder.clear()
        self.pausa_s, self.reintentos, self.desplazado = 0.0, 0, False
        self._esperando_a, self._aviso_409 = None, False
        self._cambiar(ACTIVO)
        log.info("Relevo: %s atiende el bot", self.nombre)
        await self._avisar_toma(texto)
        polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False, close_bot_session=False,
                                                       allowed_updates=allowed_updates))
        esperas = [asyncio.create_task(self.ceder.wait()), asyncio.create_task(self.salir.wait())]
        if self.guardia:
            esperas.append(asyncio.create_task(self._vigilar_latidos()))
        try:
            await asyncio.wait([polling, *esperas], return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in esperas:
                t.cancel()
            await asyncio.gather(*esperas, return_exceptions=True)
        if polling.done():
            polling.result()   # la lectura se detuvo sola: el error sube y Docker reinicia core, como hoy
        await self._parar(dp, polling)
        if self.ceder.is_set() and not self.salir.is_set():
            ahora = time.time()
            # Hasta que llegue el latido del otro (o su "apagado"), no se sondea: el sondeo le cortaría
            # la lectura al que acaba de tomar el bot.
            self.proyectos_hasta, self.no_antes_de = ahora, ahora + self.vigencia_s
            self._cambiar(ESPERA)
            log.info("Relevo: %s; %s pasa a espera (de guardia)", self.motivo, self.nombre)

    async def _vigilar_latidos(self) -> None:
        """Mientras atiende, el de guardia mira los latidos: si otro equipo atiende, le cede el bot
        (por si el 409 no llegó)."""
        while True:
            await asyncio.sleep(self.revisar_s)
            otro = self.a_quien_ceder(time.time())
            if otro is not None:
                self.motivo = f"{otro['servidor']} atiende el bot (según su latido)"
                self.ceder.set()
                return

    @staticmethod
    async def _parar(dp: Dispatcher, polling: asyncio.Task) -> None:
        """Detiene la lectura del bot. `stop_polling` falla si la lectura aún no empezó: se reintenta."""
        while not polling.done():
            try:
                await asyncio.wait_for(dp.stop_polling(), timeout=5)
            except (RuntimeError, asyncio.TimeoutError):
                await asyncio.sleep(0.05)
        await polling

    def _adoptar_proyectos(self, otros: list[dict]) -> dict[int, str]:
        """Si otro equipo atendió después que este, sigue en el proyecto activo que él tenía en cada chat."""
        if not (self.llevar_proyecto and self.adoptar):
            return {}
        con = [d for d in otros if isinstance(d.get("proyectos"), dict) and d["proyectos"]]
        mejor = max(con, key=vigencia_proyectos, default=None)
        if mejor is None or vigencia_proyectos(mejor) <= self.proyectos_hasta:
            return {}
        proyectos = {}
        for chat, p in mejor["proyectos"].items():
            with contextlib.suppress(ValueError):
                proyectos[int(chat)] = str(p)
        hechos = self.adoptar(proyectos)
        if hechos:
            log.info("Relevo: sigo en el proyecto activo que tenía %s (%d chat(s))", mejor["servidor"], len(hechos))
        return hechos

    def _texto_toma(self, otros: list[dict], ahora: float) -> str | None:
        """El aviso al tomar el bot, o None en un arranque normal (nadie más atendía)."""
        yo = self.nombre
        if self.guardia and self.desplazado:
            ultimo = min(otros, key=lambda d: self.edad(d, ahora), default=None)   # el último que cambió
            if ultimo is None:
                return f"Vuelve a atender {yo}."
            n, edad = ultimo["servidor"], self.edad(ultimo, ahora)
            if latido.estado_de(ultimo) == APAGADO:
                return f"Vuelve a atender {yo}: {n} se apagó."
            if edad >= self.vigencia_s:
                return f"Vuelve a atender {yo}: {n} dejó de latir hace {hace(edad)}."
            return f"Vuelve a atender {yo}."
        atendia = [d for d in otros if latido.estado_de(d) == ACTIVO and self.edad(d, ahora) < self.vigencia_s]
        if not atendia:
            return None
        n = atendia[0]["servidor"]
        if self.es_guardia(atendia[0]):
            return f"Ahora atiende {yo}. {n} queda en espera y retoma el bot cuando {yo} se apague."
        return f"Ahora atiende {yo} (antes atendía {n})."

    async def _avisar_toma(self, texto: str | None) -> None:
        if not (texto and self.avisar and self.enviar and self.usuarios):
            return
        proyectos = {}
        if self.proyectos:
            with contextlib.suppress(Exception):
                proyectos = self.proyectos()
        for chat in sorted(self.usuarios):
            extra = f" Proyecto activo: {proyectos[chat]}." if chat in proyectos else ""
            try:
                await self.enviar(chat, texto + extra)
            except Exception:  # noqa: BLE001 - un aviso que no sale no debe parar el relevo
                log.warning("Relevo: no se pudo avisar del relevo por Telegram", exc_info=True)
