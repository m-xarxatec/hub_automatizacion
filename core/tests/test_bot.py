"""Prueba el bot completo sin internet: una sesión falsa captura lo que se enviaría a Telegram."""

import asyncio
import io
from datetime import datetime

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText, GetFile,
                             SendChatAction, SendMessage, SendPhoto, SendVoice)
from aiogram.types import CallbackQuery, Chat, File, Message, PhotoSize, Update, User, Voice

from app.ajustes import Ajustes
from app.entradas import telegram_bot
from app.estado.db import Estado
from app.router.cascada import Router

USUARIO = 1111


class SesionFalsa(BaseSession):
    def __init__(self):
        super().__init__()
        self.enviados = []

    async def make_request(self, bot, method, timeout=None):
        self.enviados.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=len(self.enviados), date=datetime.now(),
                           chat=Chat(id=method.chat_id, type="private"), text=method.text)
        if isinstance(method, SendPhoto):
            return Message(message_id=len(self.enviados), date=datetime.now(),
                           chat=Chat(id=method.chat_id, type="private"), caption=method.caption)
        if isinstance(method, SendVoice):
            return Message(message_id=len(self.enviados), date=datetime.now(),
                           chat=Chat(id=method.chat_id, type="private"),
                           voice=Voice(file_id="R", file_unique_id="r", duration=2))
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="photos/a.jpg")
        if isinstance(method, (AnswerCallbackQuery, EditMessageText, EditMessageReplyMarkup, SendChatAction)):
            return True
        raise AssertionError(f"Método no esperado: {type(method).__name__}")

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b"\x89PNG-imagen-de-prueba"

    async def close(self):
        pass


def _ajustes(tmp_path, usuarios=frozenset({USUARIO})):
    return Ajustes(telegram_token="123:ABC", usuarios=usuarios, boveda=tmp_path / "Boveda",
                   datos=tmp_path / "datos", config_path=tmp_path / "no.yaml", servidor_nombre="test",
                   zona="Europe/Madrid", ollama_url="http://127.0.0.1:9", openclaw_url="http://127.0.0.1:9",
                   openclaw_token="", lan_ip="127.0.0.1", web_port=8080, forzar_arranque=False)


def _montar(tmp_path, cfg, boveda, usuarios=frozenset({USUARIO})):
    ctx = telegram_bot.Contexto(_ajustes(tmp_path, usuarios), cfg, boveda,
                                Estado(tmp_path / "datos" / "hub.sqlite3"), Router(cfg, tmp_path / "x"))
    ctx.ajustes.datos.mkdir(parents=True, exist_ok=True)
    bot_real, dp = telegram_bot.crear_bot(ctx)
    sesion = SesionFalsa()
    bot = Bot("123:ABC", session=sesion)
    return ctx, dp, bot, sesion


def _msg(texto=None, uid=USUARIO, **extra):
    return Update(update_id=1, message=Message(
        message_id=1, date=datetime.now(), chat=Chat(id=uid, type="private"),
        from_user=User(id=uid, is_bot=False, first_name="M"), text=texto, **extra))


def _boton(data, uid=USUARIO, voz=False):
    """Pulsar un botón; con voz=True, el botón va en una respuesta hablada (nota de voz)."""
    medio = {"voice": Voice(file_id="R", file_unique_id="r", duration=2)} if voz else {"text": "?"}
    return Update(update_id=2, callback_query=CallbackQuery(
        id="c", chat_instance="i", data=data, from_user=User(id=uid, is_bot=False, first_name="M"),
        message=Message(message_id=5, date=datetime.now(), chat=Chat(id=uid, type="private"), **medio)))


def _textos(sesion):
    return [m.text for m in sesion.enviados if isinstance(m, (SendMessage, EditMessageText))]


def _run(dp, bot, *updates):
    async def go():
        for u in updates:
            await dp.feed_update(bot, u)
    asyncio.run(go())


def test_flujo_proyecto_nota_tarea(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("/nota idea: villana con máscara"),
         _msg("tengo que terminar el storyboard"), _msg("/tareas"))
    textos = _textos(sesion)
    assert "Proyecto Webtoon creado y activo" in textos[0] and "¿De qué trata Webtoon" in textos[0]
    assert "Nota (idea) agregada a Proyectos/Webtoon/Ideas.md" in textos[1]
    assert "Tarea agregada a Proyectos/Webtoon/tareas.md" in textos[2]
    assert "1. terminar el storyboard" in textos[3]


def test_texto_dudoso_pide_confirmacion_y_boton_guarda(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("la villana usa una máscara de zorro"))
    pedido = sesion.enviados[-1]
    assert "¿Qué hago con esto?" in pedido.text
    dato = pedido.reply_markup.inline_keyboard[0][0].callback_data
    _run(dp, bot, _boton(dato))
    assert "Nota (historia) agregada a 00-Bandeja/Notas.md" in _textos(sesion)[-1]


def test_imagen_referencia_personaje(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    foto = [PhotoSize(file_id="F1", file_unique_id="u1", width=10, height=10)]
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"),
         _msg(None, photo=foto, caption="esta imagen quiero que sea referencia para el personaje (zamael)"))
    pregunta = sesion.enviados[-1]
    assert "zamael no tiene nota en Webtoon" in pregunta.text
    _run(dp, bot, _boton(pregunta.reply_markup.inline_keyboard[0][0].callback_data))
    assert "insertada en Proyectos/Webtoon/Personajes/Zamael.md" in _textos(sesion)[-1]
    # Segunda imagen: ya existe la nota, se inserta directo.
    _run(dp, bot, _msg(None, photo=foto, caption="referencia para Zamael"))
    assert "insertada en" in _textos(sesion)[-1]
    nota = (boveda.carpeta_proyectos / "Webtoon/Personajes/Zamael.md").read_text(encoding="utf-8")
    assert nota.count("![[") == 2


def test_usuario_no_autorizado_se_ignora(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/nota hola", uid=999))
    assert sesion.enviados == []


def test_modo_configuracion_devuelve_id(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda, usuarios=frozenset())
    _run(dp, bot, _msg("/start", uid=4242))
    assert "Tu ID de Telegram es 4242" in _textos(sesion)[0]


def _con_botones(sesion):
    return next(m for m in reversed(sesion.enviados) if getattr(m, "reply_markup", None))


def _boton_con(sesion, prefijo):
    teclado = _con_botones(sesion).reply_markup.inline_keyboard
    return next(b.callback_data for fila in teclado for b in fila if b.callback_data.startswith(prefijo))


def test_boton_elegido_se_guarda_como_correccion(tmp_path, cfg, boveda):
    from app.router import ejemplos
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("la villana usa una máscara de zorro"))
    _run(dp, bot, _boton(_boton_con(sesion, "a:tarea:")))
    assert "Tarea agregada" in _textos(sesion)[-1]
    assert ejemplos.leer_correcciones(ctx.router.carpeta) == [
        {"texto": "la villana usa una máscara de zorro", "accion": "tarea"}]


def test_corregir_hacia_accion_futura_registra_y_ofrece_guardar(tmp_path, cfg, boveda):
    from app.router import ejemplos
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("la regla de los tercios en viñetas"))
    _run(dp, bot, _boton(_boton_con(sesion, "o:consulta:")))
    respuesta = _con_botones(sesion)
    assert "aprenderé que esto es consulta" in respuesta.text and "día 5" in respuesta.text
    # Guardarla como nota mientras tanto no es otra corrección.
    _run(dp, bot, _boton(_boton_con(sesion, "a:nota:")))
    assert "Nota (" in _textos(sesion)[-1]
    assert [c["accion"] for c in ejemplos.leer_correcciones(ctx.router.carpeta)] == ["consulta"]


def test_accion_futura_guardada_como_nota_no_se_registra(tmp_path, cfg, boveda):
    from app.router import ejemplos
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("¿qué significa kitsune?"))
    assert "llega el día 5" in sesion.enviados[-1].text
    _run(dp, bot, _boton(_boton_con(sesion, "a:nota:")))
    assert ejemplos.leer_correcciones(ctx.router.carpeta) == []


def test_reentrenar_responde_con_resumen(tmp_path, cfg, boveda, monkeypatch):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    monkeypatch.setattr(ctx.router, "reentrenar",
                        lambda: {"ejemplos": 120, "correcciones": 3, "segundos": 1.5})
    _run(dp, bot, _msg("/reentrenar"))
    textos = _textos(sesion)
    assert "Entrenando el router" in textos[0]
    assert "Router reentrenado con 120 ejemplos (3 correcciones, 0 aprendidos de la IA)" in textos[-1]


def test_reentrenar_informa_la_calidad(tmp_path, cfg, boveda, monkeypatch):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    monkeypatch.setattr(ctx.router, "reentrenar", lambda: {
        "ejemplos": 615, "segundos": 800.0, "evaluacion": {"porcentaje": 0.937},
        "evaluacion_anterior": {"porcentaje": 0.742}})
    _run(dp, bot, _msg("/reentrenar"))
    assert "Acierta el 94% de las frases de prueba (antes, 74%)." in _textos(sesion)[-1]


def test_reentrenar_descarta_modelo_peor(tmp_path, cfg, boveda, monkeypatch):
    from app.router.clasificador import ModeloRechazado
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)

    def peor():
        raise ModeloRechazado("el nuevo acierta el 60 %", {})
    monkeypatch.setattr(ctx.router, "reentrenar", peor)
    _run(dp, bot, _msg("/reentrenar"))
    assert "salió peor en las pruebas" in _textos(sesion)[-1]
    assert "sigo con el anterior" in _textos(sesion)[-1]


def test_reentrenar_fallido_sigue_con_modelo_anterior(tmp_path, cfg, boveda, monkeypatch):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)

    def falla():
        raise RuntimeError("sin internet para bajar el modelo base")
    monkeypatch.setattr(ctx.router, "reentrenar", falla)
    _run(dp, bot, _msg("/reentrenar"))
    assert "sigo con el modelo anterior" in _textos(sesion)[-1]


# --- imágenes (día 4) ---------------------------------------------------------------
def _con_imagenes(ctx, boveda, error=None):
    from app.acciones.imagenes import GeneradorImagenes
    from app.proveedores.cadena import CadenaImagenes, ErrorProveedor, Imagen

    class Proveedor:
        nombre = "cloudflare"

        def falta_configurar(self):
            return None

        async def generar(self, prompt):
            if error:
                raise ErrorProveedor(error)
            return Imagen(b"\xff\xd8imagen", ".jpg", "cloudflare", "flux")

        async def diagnosticar(self):
            return "token rechazado (HTTP 401)" if error else "ok: token active"

    ctx.imagenes = GeneradorImagenes(boveda, CadenaImagenes([Proveedor()]))


def _fotos(sesion):
    return [m for m in sesion.enviados if isinstance(m, SendPhoto)]


def test_img_envia_foto_y_guarda_en_el_proyecto(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("/img templo en ruinas"))
    fotos = _fotos(sesion)
    assert len(fotos) == 1 and "Proyectos/Webtoon/Imagenes/" in fotos[0].caption
    assert "(cloudflare)" in fotos[0].caption
    assert len(list((boveda.carpeta_proyectos / "Webtoon" / "Imagenes").glob("*.jpg"))) == 1


def test_img_sin_proveedores_avisa_y_guarda_la_idea(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda, error="HTTP 401")
    _run(dp, bot, _msg("/img templo en ruinas"))
    ultimo = _textos(sesion)[-1]
    assert "En este momento no se pueden generar imágenes" in ultimo
    assert "Nota (idea) agregada a 00-Bandeja/Notas.md" in ultimo and not _fotos(sesion)


def test_diagnostico_lista_proveedores(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda, error="HTTP 401")
    _run(dp, bot, _msg("/diagnostico"))
    assert "- cloudflare: token rechazado (HTTP 401)" in _textos(sesion)[-1]


def test_texto_libre_de_imagen_genera_directo(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda)
    _run(dp, bot, _msg("genera una imagen de Zamael bajo la lluvia"))
    assert len(_fotos(sesion)) == 1


def test_nombrar_la_ultima_imagen_por_texto_y_voz(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda)
    _run(dp, bot, _msg("la imagen es de Aeli"))
    assert "No encontré imágenes generadas" in _textos(sesion)[-1]
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("/img una elfa pálida"),
         _msg("La imagen que se acaba de crear será el personaje Aeli"))
    assert _textos(sesion)[-1] == "Listo: la imagen elfa1 ahora se llama aeli1."
    carpeta = boveda.carpeta_proyectos / "Webtoon" / "Imagenes"
    assert sorted(p.name for p in carpeta.iterdir()) == ["aeli1.jpg", "aeli1.md"]
    _run(dp, bot, _voz(ctx, "Renombra la imagen como Kira."))
    assert ctx.voz.hablados[-1] == "Listo, la imagen ahora se llama Kira."
    assert sorted(p.name for p in carpeta.iterdir()) == ["kira1.jpg", "kira1.md"]


def test_boton_imagen_registra_y_genera(tmp_path, cfg, boveda):
    from app.router import ejemplos
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda)
    _run(dp, bot, _msg("la villana usa una máscara de zorro"))
    _run(dp, bot, _boton(_boton_con(sesion, "o:imagen:")))
    assert len(_fotos(sesion)) == 1
    assert [c["accion"] for c in ejemplos.leer_correcciones(ctx.router.carpeta)] == ["imagen"]


# --- notas de voz (paso A) -------------------------------------------------------------
class VozFalsa:
    def __init__(self, texto="", error=None):
        self.texto, self.error = texto, error
        self.hablados = []        # lo que el bot dijo en voz alta
        self.error_habla = None

    async def hablar(self, texto):
        if self.error_habla:
            raise self.error_habla
        self.hablados.append(texto)
        return b"OggS-voz"

    async def transcribir(self, audio, idioma="es"):
        assert audio == b"\x89PNG-imagen-de-prueba"  # lo que "descarga" la sesión falsa
        if self.error:
            raise self.error
        return self.texto

    async def estado(self):
        return "listo (whisper small, cpu)"


def _voz(ctx, texto="", error=None):
    """Nota de voz del usuario que se transcribe como `texto`; se conserva lo ya hablado."""
    if not isinstance(ctx.voz, VozFalsa):
        ctx.voz = VozFalsa()
    ctx.voz.texto, ctx.voz.error = texto, error
    return _msg(None, voice=Voice(file_id="V1", file_unique_id="v1", duration=4))


def _voces(sesion):
    return [m for m in sesion.enviados if isinstance(m, SendVoice)]


def test_nota_de_voz_con_orden_directa(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _voz(ctx, "Crea un proyecto nuevo llamado Webtoon."))
    _run(dp, bot, _voz(ctx, "Nota idea, la villana usa una máscara de zorro."))
    # Espejo: si el usuario habla, el bot responde solo con voz, sin rutas.
    assert _textos(sesion) == []
    assert ctx.voz.hablados == ["Proyecto Webtoon creado y activo. ¿De qué trata Webtoon o qué quieres "
                                "guardar primero?", "Nota agregada a Ideas"]
    assert len(_voces(sesion)) == 2
    ideas = (boveda.carpeta_proyectos / "Webtoon" / "Ideas.md").read_text(encoding="utf-8")
    assert "· voz\n\nla villana usa una máscara de zorro" in ideas


def test_nota_de_voz_ambigua_pasa_por_el_router(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _voz(ctx, "la villana usa una máscara de zorro"))
    pregunta = sesion.enviados[-1]
    assert isinstance(pregunta, SendVoice) and pregunta.reply_markup   # la voz lleva los botones
    assert "¿Qué hago con esto?" in ctx.voz.hablados[-1]
    _run(dp, bot, _boton(_boton_con(sesion, "a:nota:"), voz=True))
    assert "· voz\n" in (boveda.bandeja / "Notas.md").read_text(encoding="utf-8")
    # Un audio no tiene texto que editar: se quitan los botones y se responde con voz.
    assert any(isinstance(m, EditMessageReplyMarkup) for m in sesion.enviados)
    assert ctx.voz.hablados[-1] == "Nota agregada a Notas" and _textos(sesion) == []


def test_nota_de_voz_pide_imagen_y_tareas(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda)
    _run(dp, bot, _voz(ctx, "Genera una imagen de un elefante albino."))
    assert len(_fotos(sesion)) == 1 and _fotos(sesion)[0].caption is None
    assert ctx.voz.hablados[-1] == "Aquí está la imagen que pediste."
    _run(dp, bot, _voz(ctx, "Tarea: comprar tinta."))
    _run(dp, bot, _voz(ctx, "¿Cuáles son mis tareas?"))
    assert "1. comprar tinta" in ctx.voz.hablados[-1]
    assert _textos(sesion) == []


def test_nota_de_voz_con_fallos(tmp_path, cfg, boveda):
    from app.voz.cliente import ErrorVoz
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _voz(ctx, error=ErrorVoz("el servicio de voz no responde (ConnectError)")))
    assert "No pude transcribir la nota de voz: el servicio de voz no responde" in ctx.voz.hablados[-1]
    _run(dp, bot, _voz(ctx, ""))
    assert "No entendí nada" in ctx.voz.hablados[-1]
    # Si Kokoro falla, la respuesta no se pierde: va en texto.
    ctx.voz.error_habla = ErrorVoz("no se pudo generar la voz (error 503)")
    _run(dp, bot, _voz(ctx, ""))
    assert "No entendí nada" in _textos(sesion)[-1]
    ctx.voz = None
    _run(dp, bot, _msg(None, voice=Voice(file_id="V1", file_unique_id="v1", duration=4)))
    assert "no está configurada" in _textos(sesion)[-1]


# --- notas acumuladas y personajes -------------------------------------------------------
def test_notas_se_acumulan_y_archivo_aparte_solo_si_se_pide(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("/nota idea: el mercado flota"),
         _msg("/nota idea: los barcos son peces"), _msg("Crea un archivo sobre el templo en ruinas"))
    webtoon = boveda.carpeta_proyectos / "Webtoon"
    ideas = (webtoon / "Ideas.md").read_text(encoding="utf-8")
    assert ideas.count("\n## ") == 2 and "el mercado flota" in ideas and "los barcos son peces" in ideas
    assert "archivo propio" in _textos(sesion)[-1]
    propio = [p for p in webtoon.glob("*.md") if "templo" in p.name]   # solo el que se pidió aparte
    assert len(propio) == 1 and "templo-en-ruinas" in propio[0].name
    assert "# El templo en ruinas" in propio[0].read_text(encoding="utf-8")


def test_personaje_con_nombre_y_notas_que_lo_nombran(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"),
         _msg("Crea un personaje llamado Bruno que sea carnicero"))
    assert "Personaje Bruno creado en Proyectos/Webtoon/Personajes/Bruno.md" in _textos(sesion)[-1]
    _run(dp, bot, _msg("/nota Bruno usa un gancho de carne"))
    assert "ficha de Bruno" in _textos(sesion)[-1]
    ficha = (boveda.carpeta_proyectos / "Webtoon/Personajes/Bruno.md").read_text(encoding="utf-8")
    assert "# Bruno\n\nCarnicero.\n" in ficha and "## Descripción" not in ficha   # sin esqueleto
    assert ficha.endswith("## Notas\n\n- " + ficha.split("## Notas\n\n- ")[1])
    assert "(texto): Bruno usa un gancho de carne\n" in ficha.split("## Notas")[1]
    # Pedirlo otra vez no pisa la ficha: la descripción va a sus notas.
    _run(dp, bot, _msg("Nuevo personaje: Bruno, tiene una cicatriz"))
    assert "Bruno ya tenía ficha; agregué la descripción" in _textos(sesion)[-1]


def test_personaje_sin_nombre_pregunta_y_usa_la_respuesta(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"),
         _voz(ctx, "Crea un personaje que sea un carnicero que use un gancho de carne."))
    assert ctx.voz.hablados[-1] == "¿Cómo se llama el personaje?"
    _run(dp, bot, _voz(ctx, "El nombre del personaje será Bruno."))
    assert ctx.voz.hablados[-1] == "Personaje Bruno creado"
    ficha = (boveda.carpeta_proyectos / "Webtoon/Personajes/Bruno.md").read_text(encoding="utf-8")
    assert "Un carnicero que use un gancho de carne." in ficha
    assert not ctx.esperando_nombre


def test_personaje_sin_nombre_como_idea_o_respuesta_larga(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("Crea un personaje que sea panadero"))
    _run(dp, bot, _boton(_boton_con(sesion, "pi:")))
    assert "Nota (historia) agregada a Proyectos/Webtoon/Historia.md" in _textos(sesion)[-1]
    # Si la respuesta no parece un nombre, la descripción queda como idea y el mensaje sigue su camino.
    _run(dp, bot, _msg("Crea un personaje que sea herrero"), _msg("tengo que terminar el storyboard del capítulo"))
    textos = _textos(sesion)
    assert "Eso no parece un nombre" in textos[-2]
    assert "Tarea agregada" in textos[-1]
    historia = (boveda.carpeta_proyectos / "Webtoon" / "Historia.md").read_text(encoding="utf-8")
    assert "panadero" in historia and "herrero" in historia


def test_personaje_sin_proyecto_lo_pide(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("Crea un personaje llamado Kira"))
    assert "Primero elige un proyecto" in _textos(sesion)[-1]


def test_decision_resuelta_por_la_ia_se_ejecuta_y_se_aprende(tmp_path, cfg, boveda):
    from app.router import ejemplos
    from app.router.reglas import Decision
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)

    async def decidir(texto, tiene_imagen=False, sin_ia=False):
        return Decision("tarea", 0.85, motor="clasificador+llm local")
    ctx.router.decidir = decidir
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("falta el layout del capítulo 2"))
    assert "Tarea agregada" in _textos(sesion)[-1]
    assert ejemplos.leer_aprendidos(ctx.router.carpeta) == [{"texto": "falta el layout del capítulo 2",
                                                              "accion": "tarea"}]


# --- consulta (día 5) ------------------------------------------------------------
def _con_openclaw(ctx, respuestas=("Un storyboard es el guion dibujado.",), falla=False):
    """OpenClaw real con el gateway simulado; devuelve la lista de cuerpos recibidos."""
    import json

    import httpx

    from app.proveedores.openclaw import OpenClaw
    cuerpos = []
    textos = iter(respuestas)

    def manejar(req):
        cuerpos.append(json.loads(req.content))
        if falla:
            return httpx.Response(502, json={"error": "sin cuota"})
        return httpx.Response(200, json={"texto": next(textos), "modelo": "gpt-6-luna",
                                         "uso": {"inputTokens": 50, "outputTokens": 10}})
    ctx.openclaw = OpenClaw("http://openclaw:18789", "secreto", transport=httpx.MockTransport(manejar))
    return cuerpos


def _montar_con_openclaw(tmp_path, cfg, boveda, **kw):
    """El router lee ctx.openclaw al crearse: se agrega antes de armar el bot."""
    ctx = telegram_bot.Contexto(_ajustes(tmp_path), cfg, boveda,
                                Estado(tmp_path / "datos" / "hub.sqlite3"), Router(cfg, tmp_path / "x"))
    ctx.ajustes.datos.mkdir(parents=True, exist_ok=True)
    cuerpos = _con_openclaw(ctx, **kw)
    _, dp = telegram_bot.crear_bot(ctx)
    sesion = SesionFalsa()
    return ctx, dp, Bot("123:ABC", session=sesion), sesion, cuerpos


def test_consulta_con_historial_y_nuevo(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _montar_con_openclaw(
        tmp_path, cfg, boveda, respuestas=("Es el guion dibujado.", "Sí, viñeta por viñeta.", "Hola."))
    _run(dp, bot, _msg("/consulta ¿qué es un storyboard?"), _msg("/consulta ¿se hace por viñeta?"))
    assert _textos(sesion)[-2:] == ["Es el guion dibujado.", "Sí, viñeta por viñeta."]
    assert any(isinstance(m, SendChatAction) for m in sesion.enviados)
    # La segunda pregunta lleva la primera vuelta como historial
    assert [m["texto"] for m in cuerpos[1]["mensajes"]] == [
        "¿qué es un storyboard?", "Es el guion dibujado.", "¿se hace por viñeta?"]
    _run(dp, bot, _msg("/nuevo"), _msg("/consulta hola"))
    assert len(cuerpos[2]["mensajes"]) == 1


def test_pregunta_dudosa_ofrece_boton_consulta(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _montar_con_openclaw(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("¿qué es un storyboard?"))
    assert "¿Es una consulta?" in sesion.enviados[-1].text
    _run(dp, bot, _boton(_boton_con(sesion, "o:consulta:")))
    assert _textos(sesion)[-1] == "Un storyboard es el guion dibujado."
    assert cuerpos[0]["modelo"] == "openai/gpt-6-luna"


def test_consulta_sin_respuesta_avisa(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _montar_con_openclaw(tmp_path, cfg, boveda, falla=True)
    _run(dp, bot, _msg("/consulta ¿qué es un storyboard?"))
    assert "ni ChatGPT ni Claude responden" in _textos(sesion)[-1]
    assert len(cuerpos) == 2   # probó ChatGPT y después Haiku


def test_consulta_sin_openclaw(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/consulta hola"), _msg("¿qué es un storyboard?"))
    textos = _textos(sesion)
    assert "falta OPENCLAW_GATEWAY_TOKEN" in textos[0]
    assert "llega el día 5" in textos[1]


# --- router con la IA (día 5) ------------------------------------------------------
class _IAFija:
    confiable = True

    def __init__(self, decision):
        self.decision = decision

    async def opinar(self, texto):
        return self.decision


def _personaje_ia(confianza):
    from app.router.reglas import Decision
    return _IAFija(Decision("personaje", confianza, tipo="historia", motor="ia",
                            extra={"personaje": "Aeli", "descripcion": "Elfa albina de ojos rojos."}))


def test_ia_crea_la_ficha_del_personaje(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.router.llm = _personaje_ia(0.93)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"),
         _msg("Dentro de personajes vamos a crear una elfa albina de ojos rojos llamada Aeli"))
    assert "Personaje Aeli creado" in _textos(sesion)[-1]
    ficha = (boveda.carpeta_proyectos / "Webtoon" / "Personajes" / "Aeli.md").read_text(encoding="utf-8")
    assert "Elfa albina de ojos rojos." in ficha


def test_ia_poco_segura_pregunta_antes_de_crear_la_ficha(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.router.llm = _personaje_ia(0.6)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("una elfa albina llamada Aeli"))
    assert "¿Creo la ficha del personaje Aeli?" in sesion.enviados[-1].text
    _run(dp, bot, _boton(_boton_con(sesion, "pf:")))
    assert "Personaje Aeli creado" in _textos(sesion)[-1]


# --- respuesta en espejo (paso C) ----------------------------------------------------------
def test_texto_escrito_se_responde_con_texto_aunque_haya_voz(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.voz = VozFalsa()
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("/nota idea: el mercado flota"))
    assert "Nota (idea) agregada a Proyectos/Webtoon/Ideas.md" in _textos(sesion)[-1]
    assert _voces(sesion) == [] and ctx.voz.hablados == []


def test_consulta_por_voz_es_breve_y_hablada(tmp_path, cfg, boveda):
    from app.acciones.consulta import SISTEMA_VOZ
    ctx, dp, bot, sesion, cuerpos = _montar_con_openclaw(tmp_path, cfg, boveda,
                                                         respuestas=("Es el guion **dibujado**.",))
    _run(dp, bot, _voz(ctx, "¿qué es un storyboard?"))
    _run(dp, bot, _boton(_boton_con(sesion, "o:consulta:"), voz=True))
    assert cuerpos[0]["sistema"] == SISTEMA_VOZ
    assert ctx.voz.hablados[-1] == "Es el guion dibujado."
    assert _textos(sesion) == []


# --- modo análisis (decisión 4) ------------------------------------------------------
def _gateway_analisis(ctx, respuestas):
    """Gateway simulado: cada respuesta es un texto (200) o un error (502), en orden."""
    import json

    import httpx

    from app.proveedores.openclaw import OpenClaw
    cuerpos, cola = [], list(respuestas)

    def manejar(req):
        cuerpos.append(json.loads(req.content))
        r = cola.pop(0)
        if r.startswith("ERROR"):
            return httpx.Response(502, json={"error": r[6:]})
        return httpx.Response(200, json={"texto": r, "modelo": cuerpos[-1]["modelo"].split("/")[-1],
                                         "uso": {"inputTokens": 900, "outputTokens": 80}})
    ctx.openclaw = OpenClaw("http://openclaw:18789", "secreto", transport=httpx.MockTransport(manejar))
    return cuerpos


def _con_proyecto(tmp_path, cfg, boveda, respuestas):
    ctx, dp, bot, sesion, _ = _montar_con_openclaw(tmp_path, cfg, boveda)
    cuerpos = _gateway_analisis(ctx, respuestas)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("/nota historia: la villana es la hermana"))
    return ctx, dp, bot, sesion, cuerpos


def _botones(mensaje):
    return [b for fila in mensaje.reply_markup.inline_keyboard for b in fila]


def test_analisis_confirma_modelo_y_esfuerzo_antes_y_guarda(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _con_proyecto(tmp_path, cfg, boveda, ["## Conclusión\nEs viable."])
    _run(dp, bot, _msg("/analisis ¿es viable que la villana sea la hermana?"))
    pregunta = _con_botones(sesion)
    assert "Análisis en Webtoon" in pregunta.text and "Historia.md" in pregunta.text
    assert "Tokens de entrada estimados" in pregunta.text and cuerpos == []   # nada enviado aún
    textos = [b.text for b in _botones(pregunta)]
    assert textos[0].startswith("✓ Opus 5.5 · ~") and textos[1].startswith("Sonnet 5")
    assert textos[2].startswith("GPT-6 Sol") and textos[-1] == "Cancelar"
    # Al elegir el modelo aparece el esfuerzo; todavía no se envía nada.
    _run(dp, bot, _boton(_boton_con(sesion, "an:0:")))
    esfuerzo = sesion.enviados[-2]   # edición del mensaje con los botones nuevos
    assert isinstance(esfuerzo, EditMessageText) and "¿Con qué esfuerzo" in esfuerzo.text and cuerpos == []
    assert [b.text for b in _botones(esfuerzo)] == ["✓ Bajo", "Medio", "Alto", "Muy alto", "Máximo", "Cancelar"]
    _run(dp, bot, _boton(_boton_con(sesion, "ef:high:")))
    assert cuerpos[0]["modelo"] == "claude-cli/claude-opus-5-5" and cuerpos[0]["razonamiento"] == "high"
    assert cuerpos[0]["tiempo_max_s"] == 300
    assert "Analizando con Opus 5.5 (esfuerzo alto)" in _textos(sesion)[-2]
    final = _textos(sesion)[-1]
    assert "Es viable." in final and "Guardado en Proyectos/Webtoon/Analisis/" in final
    archivos = list((boveda.carpeta_proyectos / "Webtoon" / "Analisis").glob("*.md"))
    assert len(archivos) == 1 and "(esfuerzo alto)" in archivos[0].read_text(encoding="utf-8")
    # El botón ya se usó: pulsarlo otra vez no repite el análisis.
    _run(dp, bot, _boton(_boton_con(sesion, "ef:high:")))
    assert len(cuerpos) == 1


def test_esfuerzo_que_el_modelo_no_acepta_no_se_envia(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _con_proyecto(tmp_path, cfg, boveda, [])
    _run(dp, bot, _msg("/analisis revisa la historia"))
    _run(dp, bot, _boton(_boton_con(sesion, "an:0:")))
    clave = _boton_con(sesion, "ef:low:").split(":", 2)[2]
    _run(dp, bot, _boton(f"ef:off:{clave}"))   # Opus no acepta "off"
    assert cuerpos == []


def test_analisis_fallido_ofrece_reintentar_u_otro_modelo(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _con_proyecto(
        tmp_path, cfg, boveda, ["ERROR Plugin LLM completion failed. <- claude salió con código 1",
                                "ERROR otra vez", "Análisis de Sonnet."])
    _run(dp, bot, _msg("/analisis revisa la historia"))
    _run(dp, bot, _boton(_boton_con(sesion, "an:0:")))
    _run(dp, bot, _boton(_boton_con(sesion, "ef:low:")))
    aviso = _con_botones(sesion)
    assert "Opus 5.5 no pudo hacer el análisis (HTTP 502 Plugin LLM completion failed. <- claude salió" in aviso.text
    assert "No cambio de modelo sin tu confirmación" in aviso.text
    assert len(cuerpos) == 1                                        # no probó otro por su cuenta
    textos = [b.text for b in _botones(aviso)]
    assert textos[0] == "Reintentar con Opus 5.5 · esfuerzo bajo"
    assert textos[1].startswith("Sonnet 5") and not any(t.startswith("Opus") for t in textos[1:])
    # Reintentar usa el mismo modelo y esfuerzo, sin volver a preguntar.
    _run(dp, bot, _boton(_boton_con(sesion, "re:")))
    assert cuerpos[1]["modelo"] == "claude-cli/claude-opus-5-5" and cuerpos[1]["razonamiento"] == "low"
    # Falla otra vez: se elige Sonnet con su esfuerzo por defecto ("off").
    _run(dp, bot, _boton(_boton_con(sesion, "an:0:")))
    assert _botones(_con_botones(sesion))[0].text == "✓ Sin razonamiento"
    _run(dp, bot, _boton(_boton_con(sesion, "ef:off:")))
    assert cuerpos[2]["modelo"] == "claude-cli/claude-sonnet-5" and cuerpos[2]["razonamiento"] == "off"
    assert "Análisis de Sonnet." in _textos(sesion)[-1]


def test_analisis_sin_proyecto_o_sin_notas(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, _ = _montar_con_openclaw(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/analisis revisa la historia"))
    assert "elige uno con /proyecto" in _textos(sesion)[-1]
    boveda.crear_proyecto("Vacio")
    ctx.estado.fijar_proyecto(USUARIO, "Vacio")
    for archivo in (boveda.carpeta_proyectos / "Vacio").rglob("*.md"):
        archivo.unlink()
    _run(dp, bot, _msg("/analisis revisa la historia"))
    assert "No hay notas en Vacio" in _textos(sesion)[-1]


def test_modelo_elige_el_predeterminado(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _con_proyecto(tmp_path, cfg, boveda, ["Listo."])
    _run(dp, bot, _msg("/modelo"))
    menu = _con_botones(sesion)
    assert "predeterminado: Opus 5.5" in menu.text
    assert [b.text for b in _botones(menu)] == ["✓ Opus 5.5", "Sonnet 5", "GPT-6 Sol"]
    _run(dp, bot, _boton(_boton_con(sesion, "mo:openai/gpt-6-sol")))
    assert "predeterminado es GPT-6 Sol" in _textos(sesion)[-1]
    # Ahora GPT-6 Sol va primero y marcado; igual se pide confirmación.
    _run(dp, bot, _msg("/analisis revisa la historia"))
    assert _botones(_con_botones(sesion))[0].text.startswith("✓ GPT-6 Sol")
    _run(dp, bot, _boton(_boton_con(sesion, "an:0:")))
    assert [b.text for b in _botones(_con_botones(sesion))][:4] == ["✓ Bajo", "Medio", "Alto", "Muy alto"]
    _run(dp, bot, _boton(_boton_con(sesion, "ef:low:")))
    assert cuerpos[0]["modelo"] == "openai/gpt-6-sol" and cuerpos[0]["razonamiento"] == "low"
    assert "mensajes" in cuerpos[0] and "aislado" not in cuerpos[0]


def test_boton_analisis_del_router_prepara_el_analisis(tmp_path, cfg, boveda):
    from app.router import ejemplos
    ctx, dp, bot, sesion, cuerpos = _con_proyecto(tmp_path, cfg, boveda, [])
    _run(dp, bot, _msg("la villana usa una máscara de zorro"))
    _run(dp, bot, _boton(_boton_con(sesion, "o:analisis:")))
    assert "Anotado: preparo el análisis." in _textos(sesion)
    assert "Análisis en Webtoon" in _con_botones(sesion).text and cuerpos == []
    assert [c["accion"] for c in ejemplos.leer_correcciones(ctx.router.carpeta)] == ["analisis"]


def test_analisis_por_voz_responde_con_frases_cortas(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _con_proyecto(tmp_path, cfg, boveda, ["## Largo análisis…"])
    _run(dp, bot, _voz(ctx, "Analiza si el ritmo del arco 2 es muy lento."))
    if "¿Es un pedido de análisis?" in ctx.voz.hablados[-1]:      # el router pudo dudar
        _run(dp, bot, _boton(_boton_con(sesion, "o:analisis:"), voz=True))
    assert ctx.voz.hablados[-1].startswith("Voy a analizar 2 notas de Webtoon")   # sin tareas.md vacío
    _run(dp, bot, _boton(_boton_con(sesion, "an:0:"), voz=True))
    assert ctx.voz.hablados[-1] == "Elige el esfuerzo del modelo en los botones."
    assert isinstance(_con_botones(sesion), SendVoice)   # la voz lleva los botones de esfuerzo
    _run(dp, bot, _boton(_boton_con(sesion, "ef:low:"), voz=True))
    assert ctx.voz.hablados[-1] == "El análisis está listo. Lo guardé en la carpeta de análisis del proyecto."
    assert not any("Largo análisis" in h for h in ctx.voz.hablados)
