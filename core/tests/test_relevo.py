"""Relevo entre servidores: el de guardia cede el bot y lo retoma solo (sin internet ni Syncthing).

Telegram es de mentira: getUpdates responde vacío, o con el error 409 cuando "otro equipo lee el bot".
Los latidos del otro equipo se escriben a mano en la carpeta, como los dejaría Syncthing.
"""

import asyncio
import json
import time
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramConflictError, TelegramServerError
from aiogram.methods import GetMe, GetUpdates, SendMessage
from aiogram.types import Chat, Message, User

from app.entradas import telegram_bot
from app.estado import latido
from app.estado.db import Estado
from app.estado.latido import ACTIVO, APAGADO, ESPERA
from app.estado.relevo import Observador, Relevo, a_quien_ceder, adoptar_en, hace
from test_bot import _montar, _msg, _run, _textos
from test_conflictos import _conflicto

USUARIO = 1111
CFG = {"activo": True, "ceden": ["pc-casa"], "revisar_s": 0.02, "sondeo_s": 0}


class TelegramFalso(BaseSession):
    """getUpdates vacío, o 409 si `otro_lee`; guarda los mensajes enviados."""

    def __init__(self):
        super().__init__()
        self.otro_lee = False
        self.caido = False     # Telegram responde 5xx
        self.espera_s = 0.01   # lo que tarda getUpdates (el sondeo real escucha varios segundos)
        self.lecturas = 0
        self.enviados = []

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return User(id=123, is_bot=True, first_name="Hub", username="hub_bot")
        if isinstance(method, GetUpdates):
            self.lecturas += 1
            await asyncio.sleep(self.espera_s)
            if self.caido:
                raise TelegramServerError(method=method, message="Bad Gateway")
            if self.otro_lee:
                raise TelegramConflictError(method=method, message="Conflict: terminated by other getUpdates request")
            return []
        if isinstance(method, SendMessage):
            self.enviados.append((method.chat_id, method.text))
            return Message(message_id=len(self.enviados), date=datetime.now(),
                           chat=Chat(id=method.chat_id, type="private"), text=method.text)
        raise AssertionError(f"Método no esperado: {type(method).__name__}")

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b""

    async def close(self):
        pass


def _latido(carpeta, nombre):
    return json.loads(latido.ruta(carpeta, nombre).read_text(encoding="utf-8"))


async def _hasta(condicion, segundos=3.0):
    fin = time.monotonic() + segundos
    while not condicion():
        assert time.monotonic() < fin, "la condición no se cumplió a tiempo"
        await asyncio.sleep(0.01)


def _montar_relevo(carpeta, nombre, **conectar):
    tg = TelegramFalso()
    bot = Bot("123:ABC", session=tg)
    r = Relevo(carpeta, nombre, CFG, vigencia_s=180, intervalo_s=60)
    r.conectar(bot, frozenset({USUARIO}), **conectar)
    return r, tg, bot, Dispatcher()


# --- reglas ---------------------------------------------------------------------------------
def test_solo_cede_el_de_guardia_y_ante_otro_que_atiende():
    ahora = 1000.0
    edad = lambda d: ahora - d["epoch"]   # noqa: E731
    laptop = {"servidor": "laptop", "epoch": ahora - 10, "estado": ACTIVO}
    guardias = {"pc-casa"}
    assert a_quien_ceder([laptop], "pc-casa", guardias, edad, 180) is laptop
    assert a_quien_ceder([laptop], "laptop", guardias, edad, 180) is None              # la laptop no cede
    assert a_quien_ceder([{**laptop, "epoch": ahora - 500}], "pc-casa", guardias, edad, 180) is None  # viejo
    for estado in (ESPERA, APAGADO):
        assert a_quien_ceder([{**laptop, "estado": estado}], "pc-casa", guardias, edad, 180) is None
    viejo = {"servidor": "laptop", "epoch": ahora - 10}                                 # formato anterior
    assert a_quien_ceder([viejo], "pc-casa", guardias, edad, 180) is viejo
    # Dos de guardia atendiendo a la vez: cede el de nombre mayor, nunca los dos.
    otra = {"servidor": "a-pc", "epoch": ahora - 10, "estado": ACTIVO, "cede": True}
    assert a_quien_ceder([otra], "pc-casa", guardias, edad, 180) is otra
    assert a_quien_ceder([{**otra, "servidor": "pc-casa"}], "a-pc", guardias | {"a-pc"}, edad, 180) is None


def test_arrancar_solo_choca_con_otro_que_atiende_y_no_cede(tmp_path):
    latido.escribir(tmp_path, "pc-casa", cede=True)
    assert Relevo(tmp_path, "laptop", CFG, 180, 60).choque_al_arrancar() is None        # la PC cederá
    latido.escribir(tmp_path, "tablet")
    assert "tablet" in Relevo(tmp_path, "laptop", CFG, 180, 60).choque_al_arrancar()
    latido.escribir(tmp_path, "tablet", estado=APAGADO)
    assert Relevo(tmp_path, "laptop", CFG, 180, 60).choque_al_arrancar() is None
    latido.escribir(tmp_path, "tablet")
    assert Relevo(tmp_path, "pc-casa", CFG, 180, 60).choque_al_arrancar() is None       # guardia: espera
    # Sin relevo, un latido en espera tampoco impide arrancar.
    latido.escribir(tmp_path, "tablet", estado=ESPERA)
    assert latido.conflicto(tmp_path, "laptop", 180) is None


def test_la_edad_del_latido_se_mide_con_el_reloj_propio():
    o = Observador()
    atrasado = {"servidor": "laptop", "epoch": 400.0}          # reloj de la laptop 10 min atrás
    assert o.edad(atrasado, 1000.0) == 600                      # primera vista: su hora
    assert o.edad(atrasado, 1005.0) == 605
    assert o.edad({**atrasado, "epoch": 460.0}, 1060.0) == 0    # su latido cambió: está vivo
    assert o.edad({**atrasado, "epoch": 460.0}, 1100.0) == 40
    assert o.edad({"servidor": "pc", "epoch": 5000.0}, 1000.0) == 0   # reloj adelantado


def test_hace():
    assert [hace(5), hace(300), hace(7200), hace(3 * 86400)] == ["5 s", "5 min", "2 h", "3 d"]


def test_el_proyecto_activo_viaja_con_el_latido(tmp_path):
    t = time.time()
    latido.escribir(tmp_path, "pc-casa", t - 100, estado=ESPERA, desde=t - 100, cede=True,
                    proyectos={USUARIO: "Viejo"})
    latido.escribir(tmp_path, "laptop", t - 50, estado=APAGADO, desde=t - 50, proyectos={USUARIO: "Nuevo"})
    # La laptop atendió después que la PC: al arrancar de nuevo, no adopta el proyecto (más viejo) de la PC.
    laptop = Relevo(tmp_path, "laptop", CFG, 180, 60)
    laptop.adoptar = lambda p: p
    assert laptop._adoptar_proyectos(laptop.otros()) == {}
    # La PC sí adopta el de la laptop al retomar el bot.
    pc = Relevo(tmp_path, "pc-casa", CFG, 180, 60)
    pc.adoptar = lambda p: p
    assert pc._adoptar_proyectos(pc.otros()) == {USUARIO: "Nuevo"}
    # Solo usuarios autorizados y proyectos que ya están en la bóveda; lo que ya coincide no cuenta.
    estado = Estado(tmp_path / "hub.sqlite3")
    estado.fijar_proyecto(2222, "Nuevo")
    adoptar = adoptar_en(estado, lambda: ["Nuevo", "Webtoon"], frozenset({USUARIO, 2222}))
    assert adoptar({USUARIO: "Webtoon", 2222: "Nuevo", 3333: "Webtoon", 4444: "Borrado"}) == {USUARIO: "Webtoon"}
    assert estado.proyectos_activos() == {USUARIO: "Webtoon", 2222: "Nuevo"}


# --- el ciclo completo ------------------------------------------------------------------------
def test_la_pc_de_guardia_cede_con_el_409_y_vuelve_cuando_la_laptop_se_apaga(tmp_path):
    async def ir():
        pc, tg, bot, dp = _montar_relevo(tmp_path, "pc-casa")
        tarea = asyncio.create_task(pc.correr(dp, bot, senales=False))
        await _hasta(lambda: pc.atendiendo and tg.lecturas > 2)      # nadie más: sondea y atiende
        assert _latido(tmp_path, "pc-casa")["estado"] == ACTIVO and _latido(tmp_path, "pc-casa")["cede"]
        assert tg.enviados == []                                     # arranque normal: sin aviso
        # La laptop empieza a leer el bot: la PC recibe el 409 y pasa a espera sin reiniciarse.
        tg.otro_lee = True
        await _hasta(lambda: pc.estado == ESPERA)
        assert "409" in pc.motivo and _latido(tmp_path, "pc-casa")["estado"] == ESPERA
        latido.escribir(tmp_path, "laptop")                          # su latido llega por Syncthing
        await asyncio.sleep(0.1)
        lecturas = tg.lecturas
        await asyncio.sleep(0.1)
        assert pc.estado == ESPERA and tg.lecturas == lecturas        # en espera no lee el bot
        # `hub parar` en la laptop: deja de leer y su latido dice "apagado". La PC sondea y vuelve.
        tg.otro_lee = False
        latido.escribir(tmp_path, "laptop", estado=APAGADO)
        await _hasta(lambda: pc.atendiendo)
        assert tg.enviados == [(USUARIO, "Vuelve a atender pc-casa: laptop se apagó.")]
        pc.detener()
        await tarea
        assert _latido(tmp_path, "pc-casa")["estado"] == APAGADO
    asyncio.run(ir())


def test_la_laptop_toma_el_bot_avisa_y_sigue_en_el_proyecto(tmp_path):
    async def ir():
        latido.escribir(tmp_path, "pc-casa", cede=True, proyectos={USUARIO: "Webtoon"})
        estado = Estado(tmp_path / "hub.sqlite3")
        laptop, tg, bot, dp = _montar_relevo(
            tmp_path, "laptop", proyectos=estado.proyectos_activos,
            adoptar=adoptar_en(estado, lambda: ["Webtoon"], frozenset({USUARIO})))
        tarea = asyncio.create_task(laptop.correr(dp, bot, senales=False))
        await _hasta(lambda: laptop.atendiendo)
        assert estado.proyecto_activo(USUARIO) == "Webtoon"
        assert tg.enviados == [(USUARIO, "Ahora atiende laptop. pc-casa queda en espera y retoma el bot cuando "
                                         "laptop se apague. Proyecto activo: Webtoon.")]
        # Quien no es de guardia nunca cede: un 409 solo queda en el log.
        tg.otro_lee = True
        await asyncio.sleep(0.1)
        assert laptop.atendiendo
        laptop.detener()
        await tarea
        d = _latido(tmp_path, "laptop")
        assert d["estado"] == APAGADO and not d["cede"] and d["proyectos"] == {str(USUARIO): "Webtoon"}
    asyncio.run(ir())


def test_si_otro_lee_el_bot_sin_latido_la_pc_espera_cada_vez_mas(tmp_path):
    async def ir():
        pc, tg, bot, dp = _montar_relevo(tmp_path, "pc-casa")
        tg.otro_lee = True                                   # p. ej. la laptop sin Syncthing en la sala
        tarea = asyncio.create_task(pc.correr(dp, bot, senales=False))
        await _hasta(lambda: pc.pausa_s == 180)
        await asyncio.sleep(0.1)
        assert pc.estado == ESPERA and pc.no_antes_de > time.time() + 170 and tg.lecturas == 1
        pc._pausar(time.time())
        assert pc.pausa_s == 360                             # la siguiente pausa es el doble
        # Si ese equipo avisa que se apagó, se prueba ya, sin esperar la pausa.
        tg.otro_lee = False
        latido.escribir(tmp_path, "laptop", estado=APAGADO)
        await _hasta(lambda: pc.atendiendo)
        assert pc.pausa_s == 0
        pc.detener()
        await tarea
    asyncio.run(ir())


def test_tras_un_apagado_un_409_se_reintenta_pronto(tmp_path):
    """Telegram puede guardar unos segundos la última lectura del que se apagó: no es motivo de pausa larga."""
    async def ir():
        pc, tg, bot, dp = _montar_relevo(tmp_path, "pc-casa")
        pc.reintento_s = 0.05
        tarea = asyncio.create_task(pc.correr(dp, bot, senales=False))
        await _hasta(lambda: pc.atendiendo)
        tg.otro_lee = True
        latido.escribir(tmp_path, "laptop")
        await _hasta(lambda: pc.estado == ESPERA)
        latido.escribir(tmp_path, "laptop", estado=APAGADO)       # se apagó, pero su lectura sigue viva
        await _hasta(lambda: pc.reintentos == 2)
        assert pc.pausa_s == 0 and not pc.atendiendo
        tg.otro_lee = False
        await _hasta(lambda: pc.atendiendo)
        pc.detener()
        await tarea
    asyncio.run(ir())


def test_la_pc_cede_por_el_latido_si_el_409_no_llega(tmp_path):
    async def ir():
        pc, tg, bot, dp = _montar_relevo(tmp_path, "pc-casa")
        tarea = asyncio.create_task(pc.correr(dp, bot, senales=False))
        await _hasta(lambda: pc.atendiendo)
        latido.escribir(tmp_path, "laptop")
        await _hasta(lambda: pc.estado == ESPERA)
        assert pc.motivo == "laptop atiende el bot (según su latido)"
        pc.detener()
        await tarea
    asyncio.run(ir())


def test_si_telegram_no_responde_al_sondear_sigue_en_espera(tmp_path):
    async def ir():
        pc, tg, bot, dp = _montar_relevo(tmp_path, "pc-casa")
        tg.caido = True
        tarea = asyncio.create_task(pc.correr(dp, bot, senales=False))
        await _hasta(lambda: pc.no_antes_de > time.time() + 20)     # reintenta en medio minuto
        assert pc.estado == ESPERA and pc.pausa_s == 0 and tg.lecturas == 1
        pc.detener()
        await tarea
    asyncio.run(ir())


def test_la_orden_de_apagado_corta_el_sondeo(tmp_path):
    """Docker da 10 s tras `docker compose down`: el latido "apagado" no puede esperar al sondeo."""
    async def ir():
        pc, tg, bot, dp = _montar_relevo(tmp_path, "pc-casa")
        tg.espera_s = 30
        tarea = asyncio.create_task(pc.correr(dp, bot, senales=False))
        await _hasta(lambda: tg.lecturas == 1)
        pc.detener()
        await asyncio.wait_for(tarea, 1)
        assert _latido(tmp_path, "pc-casa")["estado"] == APAGADO
    asyncio.run(ir())


# --- en el bot ------------------------------------------------------------------------------
def test_estado_muestra_los_otros_servidores(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.relevo = Relevo(boveda.interna, "test", {"ceden": ["test"]}, 180, 60)
    latido.escribir(boveda.interna, "laptop", time.time() - 20)
    latido.escribir(boveda.interna, "tablet", time.time() - 7200, estado=APAGADO)
    _run(dp, bot, _msg("/estado"))
    texto = _textos(sesion)[-1]
    assert texto.startswith("<b>🟢 Hub creativo · Estado</b>\n\nServidor: test, de guardia (activo hace 0 min)\n"
                            "Otros servidores: laptop atendiendo (latido hace 20 s); tablet apagado hace 2 h\n")


def test_en_espera_no_avisa_conflictos_de_syncthing(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.relevo = Relevo(boveda.interna, "test", {"ceden": ["test"]}, 180, 60)
    _conflicto(boveda.carpeta_proyectos / "W", "Historia.md", "# Historia\n", "# Historia\nOtra línea.\n")

    async def ir():
        vigilancia = asyncio.create_task(telegram_bot.vigilar_conflictos(bot, ctx, 0.01))
        await asyncio.sleep(0.1)
        assert _textos(sesion) == []                        # en espera: avisa el equipo que atiende
        ctx.relevo.estado = ACTIVO
        await _hasta(lambda: len(_textos(sesion)) == 1)
        vigilancia.cancel()
    asyncio.run(ir())
    assert _textos(sesion)[0].startswith("⚠ Conflicto de Syncthing en Proyectos/W/Historia.md")


# --- terminal: ./hub.sh servidores, ./hub.sh parar y chequeo --------------------------------
def test_tabla_de_servidores():
    from scripts.relevo import tabla
    ahora = 10000.0
    latidos = {"pc-casa": {"servidor": "pc-casa", "epoch": ahora - 12, "estado": ESPERA, "cede": True},
               "laptop": {"servidor": "laptop", "epoch": ahora - 3, "estado": ACTIVO},
               "tablet": {"servidor": "tablet", "epoch": ahora - 7200}}
    assert tabla(latidos, "laptop", {"pc-casa"}, 180, ahora) == (
        "Servidores (latidos en _hub/):\n"
        "  laptop         atendiendo el bot (latido hace 3 s)  [este equipo]\n"
        "  pc-casa        en espera (latido hace 12 s)  [de guardia]\n"
        "  tablet         sin latir desde hace 2 h")


def test_parar_espera_a_que_la_pc_retome_el_bot(tmp_path):
    from scripts.relevo import esperar
    t, salida = [1000.0], []
    latido.escribir(tmp_path, "pc-casa", 990, estado=ESPERA, cede=True)

    def dormir(s):
        t[0] += s
        if t[0] >= 1010:                                           # la PC retoma el bot a los 10 s
            latido.escribir(tmp_path, "pc-casa", t[0], estado=ACTIVO, cede=True)
    assert esperar(tmp_path, "laptop", {"pc-casa"}, 180, reloj=lambda: t[0], dormir=dormir,
                   escribir=salida.append) == 0
    assert salida[0].startswith("Esperando a que pc-casa retome el bot")
    assert salida[-1] == "✓ pc-casa retomó el bot (10 s). Ya puedes apagar este equipo."
    assert esperar(tmp_path, "laptop", {"pc-casa"}, 180, reloj=lambda: t[0], escribir=salida.append) == 0
    assert salida[-1] == "pc-casa ya atiende el bot."
    assert esperar(tmp_path, "pc-casa", {"pc-casa"}, 180, escribir=salida.append) == 0     # el de guardia
    # La PC sigue en espera: se avisa cuánto tardará si se apaga igual.
    latido.escribir(tmp_path, "pc-casa", t[0], estado=ESPERA, cede=True)
    t0 = t[0]
    assert esperar(tmp_path, "laptop", {"pc-casa"}, 180, max_s=20, reloj=lambda: t[0],
                   dormir=lambda s: t.__setitem__(0, t[0] + s), escribir=salida.append) == 1
    assert salida[-2] == "  … sigo esperando (16 s)" and t[0] - t0 == 20
    assert salida[-1].endswith("lo retomará solo en unos 3 min (cuando deje de ver su latido).")
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    assert esperar(vacia, "laptop", {"pc-casa"}, 180, escribir=salida.append) == 1
    assert salida[-1] == "pc-casa no está latiendo (apagado o sin Syncthing): nadie retomará el bot."


def test_chequeo_mide_el_desfase_del_reloj():
    from email.utils import parsedate_to_datetime
    from scripts.chequeo import desfase_reloj
    fecha = "Wed, 30 Sep 2026 10:00:00 GMT"
    base = parsedate_to_datetime(fecha).timestamp()
    assert desfase_reloj(fecha, base + 45) == 45 and desfase_reloj(fecha, base - 90) == -90
    assert desfase_reloj(None, base) is None and desfase_reloj("no es fecha", base) is None
