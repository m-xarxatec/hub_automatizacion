"""Bot de Telegram: entrada principal del hub.

Implementado: lista blanca, /estado, /proyecto, /nota, /tarea, /tareas, /nuevo,
/limpiar, texto libre con botones, respuesta en espejo (voz -> voz con Kokoro, paso C),
referencias de imagen (incluida la referencia de
personaje), /reentrenar (día 3), /img y /diagnostico (día 4), consultas por OpenClaw con
/consulta o texto libre (día 5, con historial corto; /nuevo lo reinicia), modo análisis con
/analisis o texto libre (confirmación por botones, decisión 4) y /modelo. Las notas se acumulan
por tipo (Ideas.md, Historia.md…) o en la ficha del personaje nombrado; archivo propio
solo si se pide. "Crea un personaje…" crea su ficha y pregunta el nombre si falta. El resto de acciones
responde en qué día llegan y ofrece guardar el contenido como nota para no perderlo.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError, TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup,
                           Message, TelegramObject)

from ..acciones import analisis
from ..acciones import consulta as consultas
from ..acciones import notas, personajes, referencias
from ..acciones.imagenes import GeneradorImagenes
from ..ajustes import Ajustes
from ..boveda.proyectos import Boveda
from ..estado import limpieza
from ..estado.db import Estado
from ..proveedores.cadena import SinProveedores
from ..proveedores.openclaw import OpenClaw
from ..router.cascada import Router as RouterHub
from ..router.reglas import (Decision, archivo_aparte, limpiar_tarea, nombre_respondido, orden_hablada,
                             pedido_personaje, renombrar_imagen, tipo_nota)
from ..voz.cliente import ClienteVoz, ErrorVoz, para_hablar

log = logging.getLogger(__name__)

PENDIENTE_TTL_S = 600
# Respuesta en espejo (decisión 9): True mientras se atiende una nota de voz, o un botón
# pulsado sobre una respuesta hablada. decir() responde entonces con voz y no con texto.
_hablado: ContextVar[bool] = ContextVar("hablado", default=False)

LLEGA = {"consulta": "día 5", "analisis": "día 5", "busqueda": "la fase 3"}
NOMBRES = {"imagen": "imagen", "consulta": "consulta", "analisis": "análisis", "busqueda": "búsqueda"}
# Acciones de la segunda fila de botones, en este orden.
OTRAS = ["imagen", "consulta", "analisis", "busqueda"]
SIN_IMAGENES = ("En este momento no se pueden generar imágenes, revisa los logs para encontrar "
                "el fallo (./hub.sh logs) o usa /diagnostico.")

AYUDA = """Comandos disponibles:
/proyecto  ver o elegir el proyecto activo
/proyecto nuevo <nombre>  crear proyecto con sus carpetas
/proyecto ninguno  guardar en 00-Bandeja
/nota [tipo:] <texto>  tipos: idea, historia, produccion, dialogo
/nota aparte: <texto>  en un archivo propio
/tarea <texto>  agregar pendiente
/tareas  ver pendientes del proyecto
/consulta <pregunta>  responder con ChatGPT (o Claude si falla)
/analisis <pedido>  análisis a fondo de las notas del proyecto con un modelo grande
    (antes muestro notas y tokens y eliges el modelo)
/modelo  elegir el modelo de análisis predeterminado
/img <idea>  generar una imagen de referencia
/diagnostico  revisar los proveedores de imágenes
/estado  servidor, proyecto, servicios
/nuevo  empezar una conversación nueva (olvida las consultas anteriores)
/limpiar  borrar temporales (/limpiar simular para ver qué borraría)
/reentrenar  entrenar el router con tus correcciones y lo que decidió la IA

También puedes escribir sin comando y el router decide; lo que elijas con los
botones se guarda como ejemplo para el próximo /reentrenar.
Las notas se agregan a Ideas.md, Historia.md o Produccion.md del proyecto; si nombran
a un personaje con ficha, van a su ficha. Para un archivo propio: "crea un archivo sobre…".
"Crea un personaje llamado Bruno que sea carnicero" crea su ficha (si falta el nombre, pregunto).
Envía una imagen con un pie como "referencia para Zamael" y se inserta en su nota.
Las imágenes generadas se llaman elfa1, elfa2…; para nombrarla: "la imagen que se acaba de
crear será el personaje Aeli".
Envía una nota de voz: se transcribe en local y puedes dar órdenes como
"nota idea, …", "tarea: …", "cambia al proyecto Webtoon" o "genera una imagen de …".
Si me hablas, respondo con voz; si escribes, con texto."""

COMANDOS = [
    ("proyecto", "Ver o elegir proyecto activo"),
    ("nota", "Guardar una nota"),
    ("tarea", "Agregar un pendiente"),
    ("tareas", "Ver pendientes"),
    ("consulta", "Preguntar a ChatGPT"),
    ("analisis", "Analizar las notas del proyecto"),
    ("modelo", "Elegir el modelo de análisis"),
    ("img", "Generar una imagen de referencia"),
    ("diagnostico", "Revisar proveedores de imágenes"),
    ("estado", "Estado del servidor"),
    ("nuevo", "Reiniciar contexto"),
    ("limpiar", "Borrar temporales"),
    ("reentrenar", "Entrenar el router"),
    ("ayuda", "Ver comandos"),
]


@dataclass
class Contexto:
    ajustes: Ajustes
    config: dict
    boveda: Boveda
    estado: Estado
    router: RouterHub
    imagenes: GeneradorImagenes | None = None
    voz: ClienteVoz | None = None
    openclaw: OpenClaw | None = None
    inicio: float = field(default_factory=time.time)
    pendientes: dict[str, dict[str, Any]] = field(default_factory=dict)
    # chat -> clave del pendiente de un personaje al que le falta el nombre
    esperando_nombre: dict[int, str] = field(default_factory=dict)

    def guardar_pendiente(self, **datos: Any) -> str:
        """Guarda datos para un botón. `ttl` (segundos) cambia la caducidad por defecto."""
        self._purgar()
        clave = secrets.token_hex(4)
        self.pendientes[clave] = {**datos, "creado": time.time()}
        return clave

    def tomar_pendiente(self, clave: str) -> dict[str, Any] | None:
        self._purgar()
        return self.pendientes.pop(clave, None)

    def _purgar(self) -> None:
        ahora = time.time()
        for clave in [k for k, v in self.pendientes.items()
                      if v["creado"] < ahora - v.get("ttl", PENDIENTE_TTL_S)]:
            del self.pendientes[clave]

    def relativa(self, ruta: Path) -> str:
        try:
            return ruta.relative_to(self.boveda.raiz).as_posix()
        except ValueError:
            return str(ruta)


class SoloAutorizados(BaseMiddleware):
    """Ignora a cualquier usuario fuera de TELEGRAM_USUARIOS.

    Si la lista está vacía (primera instalación), responde con el ID del
    usuario para que lo copie en .env.
    """

    def __init__(self, usuarios: frozenset[int]):
        self.usuarios = usuarios

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]],
                       event: TelegramObject, data: dict) -> Any:
        usuario = data.get("event_from_user")
        if usuario is not None and usuario.id in self.usuarios:
            return await handler(event, data)
        if not self.usuarios and isinstance(event, Message) and usuario is not None:
            await event.answer(
                f"Modo configuración. Tu ID de Telegram es {usuario.id}.\n"
                "Agrégalo a TELEGRAM_USUARIOS en .env y reinicia con:\n"
                "docker compose restart core")
        return None


def teclado(filas: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texto, callback_data=dato) for texto, dato in fila] for fila in filas
    ])


def separar_tipo(texto: str, tipos: list[str]) -> tuple[str, str]:
    """'/nota idea: ...' -> ('idea', '...'). Sin prefijo, se deduce por reglas."""
    texto = (texto or "").strip()
    cabeza, sep, resto = texto.partition(":")
    clave = cabeza.strip().lower().replace("ó", "o").replace("á", "a")
    if sep and clave in tipos:
        return clave, resto.strip()
    return tipo_nota(texto), texto


class ModoVoz(BaseMiddleware):
    """Activa la respuesta hablada si el mensaje (o el mensaje del botón) es de voz."""

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]],
                       event: TelegramObject, data: dict) -> Any:
        if isinstance(event, CallbackQuery):
            hablado = isinstance(event.message, Message) and event.message.voice is not None
        else:
            hablado = isinstance(event, Message) and (event.voice is not None or event.audio is not None)
        marca = _hablado.set(hablado)
        try:
            return await handler(event, data)
        finally:
            _hablado.reset(marca)


async def _descargar(bot: Bot, file_id: str) -> bytes:
    archivo = await bot.download(file_id)
    if archivo is None:
        raise OSError("Telegram no devolvió el archivo")
    archivo.seek(0)
    return archivo.read()


def crear_router(ctx: Contexto) -> Router:
    r = Router(name="hub")
    tipos = list(ctx.config.get("router", {}).get("tipos_nota",
                 ["idea", "historia", "produccion", "dialogo", "general"]))

    entrenando = asyncio.Lock()
    # Lo que aún no funciona en este equipo: con OpenClaw configurado, consulta y análisis ya existen.
    llega = {a: dia for a, dia in LLEGA.items() if not (a in ("consulta", "analisis") and ctx.openclaw)}

    async def decir(bot: Bot, chat: int, texto: str, reply_markup: InlineKeyboardMarkup | None = None,
                    voz: str | None = None) -> None:
        """Responde con texto, o con voz si el usuario habló (sin rutas y breve: `voz` o para_hablar)."""
        if _hablado.get() and ctx.voz is not None:
            try:
                await bot.send_chat_action(chat, "record_voice")
                audio = await ctx.voz.hablar(voz or para_hablar(texto))
                await bot.send_voice(chat, BufferedInputFile(audio, filename="respuesta.ogg"),
                                     reply_markup=reply_markup)
                return
            except ErrorVoz as e:
                log.warning("No se pudo responder con voz, va en texto: %s", e)
        await bot.send_message(chat, texto, reply_markup=reply_markup)

    def destino(chat_id: int) -> str:
        return ctx.estado.proyecto_activo(chat_id) or "00-Bandeja"

    def registrar(texto: str, accion: str) -> None:
        try:
            ctx.router.registrar(texto, accion)
        except OSError:
            log.exception("No se pudo guardar la corrección del router")

    def aprender(texto: str, d: Decision) -> None:
        """El clasificador dudó y la IA lo resolvió: queda como ejemplo para /reentrenar."""
        try:
            if ctx.router.aprender(texto, d):
                log.info("Router: aprendido de la IA (%s) -> %s", d.motor, d.accion)
        except OSError:
            log.exception("No se pudo guardar lo aprendido de la IA")

    def teclado_acciones(clave: str, propuesta: str, tipo: str, otras: bool = True) -> InlineKeyboardMarkup:
        def marca(accion: str, texto: str) -> str:
            return ("✓ " if accion == propuesta else "") + texto
        filas = [[(marca("nota", f"Nota ({tipo})"), f"a:nota:{clave}"), (marca("tarea", "Tarea"), f"a:tarea:{clave}")]]
        if otras:
            filas.append([(marca(a, NOMBRES[a].capitalize()), f"o:{a}:{clave}")
                          for a in OTRAS if a in ctx.router.acciones_texto])
        filas.append([("Cancelar", f"x:{clave}")])
        return teclado(filas)

    def ejecutar(accion: str, texto: str, tipo: str, chat_id: int, origen: str) -> str:
        proyecto = ctx.estado.proyecto_activo(chat_id)
        try:
            if accion == "tarea":
                ruta = ctx.boveda.agregar_tarea(limpiar_tarea(texto), proyecto)
                return f"Tarea agregada a {ctx.relativa(ruta)}"
            g = notas.guardar(ctx.boveda, texto, proyecto, tipo, origen)
            if g.como == "personaje":
                return f"Nota agregada a la ficha de {g.ruta.stem} ({ctx.relativa(g.ruta)})"
            if g.como == "aparte":
                return f"Nota ({tipo}) guardada en un archivo propio: {ctx.relativa(g.ruta)}"
            return f"Nota ({tipo}) agregada a {ctx.relativa(g.ruta)}"
        except ValueError as e:
            return str(e)
        except OSError as e:
            log.exception("Error escribiendo en la bóveda")
            return f"No pude escribir en la bóveda: {e}"

    async def guardar_referencia(bot: Bot, chat_id: int, file_id: str, ext: str, pie: str) -> str:
        proyecto = ctx.estado.proyecto_activo(chat_id)
        datos = await _descargar(bot, file_id)
        img = referencias.guardar_imagen(ctx.boveda, proyecto, datos, ext, pie or "referencia")
        nota = referencias.nota_de_referencia(ctx.boveda, proyecto, img, pie, "telegram")
        ctx.boveda.registrar_diario(f"Referencia [[{nota.stem}]]" + (f" en {proyecto}" if proyecto else ""))
        return f"Referencia guardada en {ctx.relativa(img)}"

    async def insertar_personaje(bot: Bot, proyecto: str, nota: Path, nombre: str,
                                 file_id: str, ext: str) -> str:
        datos = await _descargar(bot, file_id)
        img = referencias.guardar_imagen(ctx.boveda, proyecto, datos, ext, nombre)
        referencias.insertar_en_personaje(nota, img)
        ctx.boveda.registrar_diario(f"Referencia visual de [[{nota.stem}]] en {proyecto}")
        return f"Referencia de {nota.stem} guardada en {ctx.relativa(img)} e insertada en {ctx.relativa(nota)}"

    async def personaje(m: Message, nombre: str | None, descripcion: str, texto: str, origen: str) -> None:
        chat = m.chat.id
        proyecto = ctx.estado.proyecto_activo(chat)
        if not proyecto:
            await decir(m.bot, m.chat.id, "Primero elige un proyecto con /proyecto: los personajes viven dentro de un proyecto.")
            return
        if not nombre:
            clave = ctx.guardar_pendiente(tipo="personaje", descripcion=descripcion, texto=texto,
                                          chat=chat, origen=origen)
            ctx.esperando_nombre[chat] = clave
            await decir(m.bot, m.chat.id, "¿Cómo se llama el personaje?",
                           reply_markup=teclado([[("Guardar como idea", f"pi:{clave}"), ("Cancelar", f"x:{clave}")]]))
            return
        await decir(m.bot, m.chat.id, crear_personaje(proyecto, nombre, descripcion, origen))

    def crear_personaje(proyecto: str, nombre: str, descripcion: str, origen: str) -> str:
        try:
            ficha, creada = personajes.crear_o_anotar(ctx.boveda, proyecto, nombre, descripcion, origen)
        except ValueError as e:
            return str(e)
        except OSError as e:
            log.exception("Error escribiendo en la bóveda")
            return f"No pude escribir en la bóveda: {e}"
        if creada:
            return f"Personaje {ficha.stem} creado en {ctx.relativa(ficha)}"
        extra = "; agregué la descripción a sus notas" if descripcion else ""
        return f"{ficha.stem} ya tenía ficha{extra}: {ctx.relativa(ficha)}"

    async def respuesta_de_nombre(m: Message, texto: str) -> bool:
        """Si el bot preguntó el nombre de un personaje, este mensaje es la respuesta."""
        clave = ctx.esperando_nombre.pop(m.chat.id, None)
        p = ctx.tomar_pendiente(clave) if clave else None
        if not p:
            return False   # no se esperaba nada, venció o se canceló
        nombre = nombre_respondido(texto)
        proyecto = ctx.estado.proyecto_activo(m.chat.id)
        if not nombre or not proyecto:
            # La descripción no se pierde: queda como nota y se sigue con el mensaje nuevo.
            guardado = ejecutar("nota", p["texto"], "historia", m.chat.id, p["origen"])
            await decir(m.bot, m.chat.id, f"Eso no parece un nombre, así que guardé el personaje como idea. {guardado}")
            return False
        await decir(m.bot, m.chat.id, crear_personaje(proyecto, nombre, p["descripcion"], p["origen"]))
        return True

    async def orden_directa(m: Message, texto: str, origen: str) -> bool:
        """Pedidos que no necesitan router: nombrar la última imagen, crear un personaje
        o una nota en archivo propio."""
        nombre_img = renombrar_imagen(texto)
        if nombre_img and ctx.imagenes is not None:
            log.info("Mensaje (%s): orden directa nombrar imagen", origen)
            await nombrar_imagen(m, nombre_img)
            return True
        pedido = pedido_personaje(texto)
        if pedido:
            log.info("Mensaje (%s): orden directa crear personaje", origen)
            await personaje(m, pedido[0], pedido[1], texto, origen)
            return True
        if archivo_aparte(texto):
            log.info("Mensaje (%s): orden directa nota en archivo propio", origen)
            await decir(m.bot, m.chat.id, ejecutar("nota", texto, tipo_nota(texto), m.chat.id, origen))
            return True
        return False

    # --- comandos -----------------------------------------------------------
    @r.message(CommandStart())
    @r.message(Command("ayuda", "help"))
    async def ayuda(m: Message) -> None:
        await decir(m.bot, m.chat.id, AYUDA)

    @r.message(Command("estado"))
    async def estado_cmd(m: Message) -> None:
        await estado(m)

    async def estado(m: Message) -> None:
        a = ctx.ajustes
        cfg_llm = ctx.config.get("proveedores", {}).get("llm_local", {})
        voz = ctx.voz.estado() if ctx.voz else _constante("no configurada")
        ollama = (_estado_ollama(a.ollama_url, cfg_llm.get("modelo", "")) if cfg_llm.get("activo", True)
                  else _constante("apagado en el MVP (llm_local.activo: false)"))
        ollama, openclaw, voz = await asyncio.gather(
            ollama, _estado_openclaw(a.openclaw_url, a.openclaw_token), voz)
        minutos = int((time.time() - ctx.inicio) / 60)
        lineas = [
            f"Servidor: {a.servidor_nombre} (activo hace {minutos} min)",
            f"Proyecto activo: {destino(m.chat.id)}",
            f"Proyectos: {len(ctx.boveda.listar_proyectos())}",
            f"Router: {ctx.router.motor}",
            f"Ollama: {ollama}",
            f"OpenClaw: {openclaw}",
            f"Voz: {voz}",
            f"Pendientes en cola: {ctx.estado.pendientes()}",
            f"Web local: http://{a.lan_ip}:{a.web_port} (pantallas en fase 2)",
        ]
        await decir(m.bot, m.chat.id, "\n".join(lineas))

    @r.message(Command("proyecto"))
    async def proyecto_cmd(m: Message, command: CommandObject) -> None:
        await proyecto(m, command.args or "")

    async def proyecto(m: Message, arg: str) -> None:
        arg = arg.strip()
        chat = m.chat.id
        if not arg:
            lista = ctx.boveda.listar_proyectos()
            activo = ctx.estado.proyecto_activo(chat)
            if not lista:
                await decir(m.bot, m.chat.id, "No hay proyectos. Crea uno con /proyecto nuevo Webtoon")
                return
            filas = [[(("• " if p == activo else "") + p, f"p:{i}")] for i, p in enumerate(lista[:20])]
            filas.append([("Sin proyecto (00-Bandeja)", "p:-")])
            await decir(m.bot, m.chat.id, f"Proyecto activo: {activo or 'ninguno'}\nElige uno:", reply_markup=teclado(filas))
            return
        bajo = arg.lower()
        if bajo in {"ninguno", "ninguna", "-"}:
            ctx.estado.fijar_proyecto(chat, None)
            await decir(m.bot, m.chat.id, "Sin proyecto activo: todo irá a 00-Bandeja.")
            return
        if bajo.startswith(("nuevo ", "nueva ")):
            nombre = arg.split(None, 1)[1]
            try:
                creado = ctx.boveda.crear_proyecto(nombre)
            except ValueError as e:
                await decir(m.bot, m.chat.id, str(e))
                return
            ctx.estado.fijar_proyecto(chat, creado)
            await decir(m.bot, m.chat.id, f"Proyecto {creado} listo con sus carpetas. Es el proyecto activo.")
            return
        encontrado = ctx.boveda.buscar_proyecto(arg)
        if encontrado:
            ctx.estado.fijar_proyecto(chat, encontrado)
            await decir(m.bot, m.chat.id, f"Proyecto activo: {encontrado}")
            return
        clave = ctx.guardar_pendiente(tipo="crear_proyecto", nombre=arg, chat=chat)
        await decir(m.bot, m.chat.id, f"No existe el proyecto «{arg}». ¿Lo creo?",
                       reply_markup=teclado([[("Crear", f"np:{clave}"), ("Cancelar", f"x:{clave}")]]))

    @r.message(Command("nota"))
    async def nota_cmd(m: Message, command: CommandObject) -> None:
        await nota(m, command.args or "")

    async def nota(m: Message, args: str, origen: str = "telegram") -> None:
        tipo, texto = separar_tipo(args, tipos)
        if not texto:
            await decir(m.bot, m.chat.id, "Uso: /nota [idea:] texto de la nota")
            return
        await decir(m.bot, m.chat.id, ejecutar("nota", texto, tipo, m.chat.id, origen))

    @r.message(Command("tarea"))
    async def tarea_cmd(m: Message, command: CommandObject) -> None:
        await tarea(m, command.args or "")

    async def tarea(m: Message, args: str, origen: str = "telegram") -> None:
        texto = args.strip()
        if not texto:
            await decir(m.bot, m.chat.id, "Uso: /tarea texto del pendiente")
            return
        await decir(m.bot, m.chat.id, ejecutar("tarea", texto, "general", m.chat.id, origen))

    @r.message(Command("tareas"))
    async def tareas_cmd(m: Message) -> None:
        await tareas(m)

    async def tareas(m: Message) -> None:
        proyecto = ctx.estado.proyecto_activo(m.chat.id)
        abiertas = ctx.boveda.tareas_abiertas(proyecto)
        if not abiertas:
            await decir(m.bot, m.chat.id, f"No hay pendientes en {proyecto or '00-Bandeja'}.")
            return
        lista = "\n".join(f"{i}. {t}" for i, t in enumerate(abiertas[:30], 1))
        await decir(m.bot, m.chat.id, f"Pendientes en {proyecto or '00-Bandeja'}:\n{lista}")

    @r.message(Command("nuevo"))
    async def nuevo_cmd(m: Message) -> None:
        ctx.estado.nueva_sesion(m.chat.id)
        await decir(m.bot, m.chat.id, "Contexto reiniciado. La próxima consulta empieza desde cero.")

    @r.message(Command("limpiar"))
    async def limpiar_cmd(m: Message, command: CommandObject) -> None:
        simular = any(p in (command.args or "") for p in ("simular", "que-borraria", "que_borraria"))
        rutas = await asyncio.to_thread(limpieza.limpiar, ctx.ajustes.datos, ctx.boveda.raiz,
                                        ctx.config.get("limpieza", {}), simular)
        if not rutas:
            await decir(m.bot, m.chat.id, "No hay temporales que borrar.")
            return
        verbo = "Borraría" if simular else "Borré"
        muestra = "\n".join(f"- {p.name}" for p in rutas[:10])
        extra = f"\n… y {len(rutas) - 10} más" if len(rutas) > 10 else ""
        await decir(m.bot, m.chat.id, f"{verbo} {len(rutas)} archivos:\n{muestra}{extra}")

    # --- imágenes -------------------------------------------------------------
    @r.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
    async def imagen_msg(m: Message, bot: Bot) -> None:
        pie = m.caption or ""
        if m.photo:
            file_id, ext = m.photo[-1].file_id, ".jpg"
        else:
            file_id = m.document.file_id
            ext = Path(m.document.file_name or "imagen.png").suffix or ".png"
        chat = m.chat.id
        decision = await ctx.router.decidir(pie, tiene_imagen=True)
        try:
            if decision.accion != "referencia_personaje":
                await decir(m.bot, m.chat.id, await guardar_referencia(bot, chat, file_id, ext, pie))
                return
            nombre = decision.extra["personaje"]
            proyecto = ctx.estado.proyecto_activo(chat)
            hallado = referencias.buscar_personaje(ctx.boveda, nombre, proyecto) if proyecto else None
            hallado = hallado or referencias.buscar_personaje(ctx.boveda, nombre)
            if hallado:
                p, nota = hallado
                await decir(m.bot, m.chat.id, await insertar_personaje(bot, p, nota, nombre, file_id, ext))
                return
            clave = ctx.guardar_pendiente(tipo="imagen", file_id=file_id, ext=ext, pie=pie,
                                          personaje=nombre, chat=chat)
            if not proyecto:
                await decir(m.bot, m.chat.id, 
                    f"No encontré a {nombre} en ningún proyecto. Elige un proyecto con /proyecto "
                    "y vuelve a enviar la imagen, o guárdala en la bandeja.",
                    reply_markup=teclado([[("Guardar en bandeja", f"r:{clave}"), ("Cancelar", f"x:{clave}")]]))
                return
            await decir(m.bot, m.chat.id, 
                f"{nombre} no tiene nota en {proyecto}. ¿La creo con esta imagen como referencia?",
                reply_markup=teclado([[(f"Crear a {nombre}", f"cp:{clave}")],
                                      [("Solo guardar referencia", f"r:{clave}"), ("Cancelar", f"x:{clave}")]]))
        except OSError as e:
            log.exception("Error guardando imagen")
            await decir(m.bot, m.chat.id, f"No pude guardar la imagen: {e}")

    async def generar_imagen(bot: Bot, chat: int, idea: str) -> None:
        if ctx.imagenes is None:
            await decir(bot, chat, "La generación de imágenes no está configurada.")
            return
        proyecto = ctx.estado.proyecto_activo(chat)
        if _hablado.get():
            await bot.send_chat_action(chat, "upload_photo")
        else:
            await bot.send_message(chat, "Generando la imagen… puede tardar hasta un minuto.")
        try:
            r_img = await ctx.imagenes.crear(idea, proyecto)
        except SinProveedores as e:
            log.error("No se pudo generar la imagen. Motivos: %s", e)
            diagnostico = await ctx.imagenes.diagnosticar()
            log.warning("Diagnóstico de imágenes:\n%s", diagnostico)
            guardado = ejecutar("nota", idea, "idea", chat, "telegram")
            await decir(bot, chat, f"{SIN_IMAGENES}\nLa idea no se pierde: {guardado}",
                        voz="En este momento no se pueden generar imágenes. Guardé la idea como nota.")
            return
        except OSError as e:
            log.exception("Error guardando la imagen generada")
            await decir(bot, chat, f"La imagen se generó, pero no pude guardarla en la bóveda: {e}")
            return
        foto = BufferedInputFile(r_img.imagen.read_bytes(), filename=r_img.imagen.name)
        if _hablado.get():
            await bot.send_photo(chat, foto)
            await decir(bot, chat, "", voz="Aquí está la imagen que pediste.")
        else:
            await bot.send_photo(chat, foto, caption=f"Guardada en {ctx.relativa(r_img.imagen)} ({r_img.proveedor})")

    async def nombrar_imagen(m: Message, nombre: str) -> None:
        nota = ctx.imagenes.ultima(ctx.estado.proyecto_activo(m.chat.id))
        if nota is None:
            await decir(m.bot, m.chat.id, f"No encontré imágenes generadas en {destino(m.chat.id)}.")
            return
        try:
            nueva = ctx.imagenes.renombrar(nota, nombre)
        except OSError as e:
            log.exception("Error renombrando la imagen")
            await decir(m.bot, m.chat.id, f"No pude renombrar la imagen: {e}")
            return
        await decir(m.bot, m.chat.id, f"Listo: la imagen {nota.stem} ahora se llama {nueva.stem}.",
                    voz=f"Listo, la imagen ahora se llama {nombre}.")

    async def consultar(bot: Bot, chat: int, pregunta: str) -> None:
        await bot.send_chat_action(chat, "typing")
        await decir(bot, chat, await consultas.responder(ctx.openclaw, ctx.estado, chat, pregunta,
                                                         ctx.ajustes.zona, breve=_hablado.get()))

    @r.message(Command("consulta"))
    async def consulta_cmd(m: Message, command: CommandObject, bot: Bot) -> None:
        pregunta = (command.args or "").strip()
        if not ctx.openclaw:
            await decir(m.bot, m.chat.id, "La consulta necesita OpenClaw: falta OPENCLAW_GATEWAY_TOKEN en .env.")
        elif not pregunta:
            await decir(m.bot, m.chat.id, "Uso: /consulta tu pregunta")
        else:
            await consultar(bot, m.chat.id, pregunta)

    # --- modo análisis (decisión 4): siempre con confirmación, nunca cambio automático ---
    def modelo_analisis(chat: int) -> analisis.Opcion | None:
        return analisis.predeterminado(ctx.config, ctx.estado.preferencia(chat, analisis.PREFERENCIA))

    def teclado_analisis(clave: str, opciones: list[analisis.Opcion], prep: analisis.Preparado,
                         marcar: bool = True, reintento: analisis.Opcion | None = None) -> InlineKeyboardMarkup:
        filas = [[(f"Reintentar con {reintento.nombre} · esfuerzo {analisis.nombre_esfuerzo(reintento)}",
                   f"re:{clave}")]] if reintento else []
        filas += [[(analisis.etiqueta(o, prep, marcar and i == 0), f"an:{i}:{clave}")]
                  for i, o in enumerate(opciones)]
        return teclado(filas + [[("Cancelar", f"x:{clave}")]])

    def teclado_esfuerzo(clave: str, opcion: analisis.Opcion) -> InlineKeyboardMarkup:
        """El esfuerzo por defecto (el menor, decisión 3) va primero y marcado."""
        botones = [(("✓ " if e == opcion.razonamiento else "") + analisis.ESFUERZOS[e], f"ef:{e}:{clave}")
                   for e in opcion.lista_esfuerzos()]
        return teclado([botones[i:i + 3] for i in range(0, len(botones), 3)] + [[("Cancelar", f"x:{clave}")]])

    async def reemplazar(c: CallbackQuery, texto: str, markup: InlineKeyboardMarkup, voz: str) -> None:
        """Cambia el mensaje de los botones por otro con botones nuevos (en voz, uno nuevo hablado)."""
        if _hablado.get() and isinstance(c.message, Message):
            await c.message.edit_reply_markup(reply_markup=None)
            await decir(c.bot, c.message.chat.id, texto, reply_markup=markup, voz=voz)
        elif isinstance(c.message, Message):
            await c.message.edit_text(texto, reply_markup=markup)
        await c.answer()

    async def pedir_analisis(bot: Bot, chat: int, pedido: str) -> None:
        """Junta las notas, estima tokens y pide elegir el modelo. No llama a ningún modelo."""
        if not ctx.openclaw:
            await decir(bot, chat, "El análisis necesita OpenClaw: falta OPENCLAW_GATEWAY_TOKEN en .env.")
            return
        proyecto = ctx.estado.proyecto_activo(chat)
        if not proyecto:
            await decir(bot, chat, "El análisis trabaja sobre un proyecto: elige uno con /proyecto.")
            return
        a = analisis.ajustes(ctx.config)
        opciones = analisis.ordenar(analisis.opciones_desde_config(ctx.config), modelo_analisis(chat))
        if not opciones:
            await decir(bot, chat, "No hay modelos de análisis en config.yaml (proveedores.analisis.opciones).")
            return
        try:
            prep = analisis.preparar(ctx.boveda, proyecto, pedido, int(a.get("tope_tokens_entrada") or 20000))
        except OSError as e:
            log.exception("Error leyendo las notas para el análisis")
            await decir(bot, chat, f"No pude leer las notas de {proyecto}: {e}")
            return
        if not prep.notas:
            await decir(bot, chat, f"No hay notas en {proyecto} para analizar.")
            return
        minutos = int(a.get("espera_confirmacion_min") or 10)
        clave = ctx.guardar_pendiente(tipo="analisis", chat=chat, prep=prep, opciones=opciones,
                                      todas=opciones, ttl=minutos * 60)
        log.info("Análisis preparado: %d notas, ~%d tokens, %d fuera", len(prep.notas), prep.tokens,
                 len(prep.fuera))
        await decir(bot, chat, analisis.resumen(prep, ctx.boveda.carpeta_proyectos / proyecto, minutos),
                    reply_markup=teclado_analisis(clave, opciones, prep), voz=analisis.resumen_hablado(prep))

    async def hacer_analisis(bot: Bot, p: dict[str, Any], opcion: analisis.Opcion) -> None:
        chat, prep = p["chat"], p["prep"]
        await bot.send_chat_action(chat, "typing")
        r_an = await analisis.analizar(ctx.openclaw, opcion, prep, ctx.config)
        if r_an is None:
            motivo = ctx.openclaw.ultimo_error or "sin detalle"
            log.warning("Análisis con %s (esfuerzo %s) falló: %s", opcion.modelo, opcion.razonamiento, motivo)
            # Reintentar el mismo (un fallo puede ser pasajero) u otro modelo: decide el usuario.
            otras = [o for o in p["opciones"] if o.modelo != opcion.modelo]
            datos = {k: v for k, v in p.items() if k != "creado"}
            clave = ctx.guardar_pendiente(**{**datos, "opciones": otras, "reintento": opcion})
            await decir(bot, chat, f"{opcion.nombre} no pudo hacer el análisis ({motivo}).\n"
                                   "¿Lo reintento o pruebo con otro modelo? No cambio de modelo sin tu confirmación.",
                        reply_markup=teclado_analisis(clave, otras, prep, marcar=False, reintento=opcion),
                        voz=f"{opcion.nombre} no pudo hacer el análisis. Elige en los botones si lo reintento "
                            "o pruebo otro modelo.")
            return
        ctx.estado.sumar_gasto(ctx.boveda.ahora().date().isoformat(), r_an.modelo)
        try:
            ruta = analisis.guardar(ctx.boveda, prep, r_an, opcion)
            pie = f"\n\nGuardado en {ctx.relativa(ruta)}"
            voz = "El análisis está listo. Lo guardé en la carpeta de análisis del proyecto."
        except OSError as e:
            log.exception("Error guardando el análisis")
            pie = f"\n\nNo pude guardarlo en la bóveda: {e}"
            voz = "El análisis está listo, pero no pude guardarlo en la bóveda."
        texto = r_an.texto.strip()
        limite = consultas.MAX_CARACTERES - len(pie) - 40
        if len(texto) > limite:
            texto = texto[:limite].rstrip() + "… (sigue en el archivo)"
        await decir(bot, chat, texto + pie, voz=voz)

    @r.message(Command("analisis"))
    async def analisis_cmd(m: Message, command: CommandObject, bot: Bot) -> None:
        pedido = (command.args or "").strip()
        if not pedido:
            await decir(m.bot, m.chat.id, "Uso: /analisis qué quieres que revise, por ejemplo: "
                                          "/analisis busca contradicciones en la historia")
            return
        await pedir_analisis(bot, m.chat.id, pedido)

    @r.message(Command("modelo"))
    async def modelo_cmd(m: Message) -> None:
        opciones = analisis.opciones_desde_config(ctx.config)
        actual = modelo_analisis(m.chat.id)
        if not opciones or actual is None:
            await decir(m.bot, m.chat.id, "No hay modelos de análisis en config.yaml.")
            return
        filas = [[(("✓ " if o == actual else "") + o.nombre, f"mo:{o.modelo}")] for o in opciones]
        await decir(m.bot, m.chat.id, f"Modelo de análisis predeterminado: {actual.nombre}.\n"
                                      "Elige otro si quieres; antes de cada análisis igual te pido confirmación.",
                    reply_markup=teclado(filas))

    @r.message(Command("img"))
    async def img_cmd(m: Message, command: CommandObject, bot: Bot) -> None:
        idea = (command.args or "").strip()
        if not idea:
            await decir(m.bot, m.chat.id, "Uso: /img descripción de la imagen que quieres")
            return
        await generar_imagen(bot, m.chat.id, idea)

    @r.message(Command("diagnostico"))
    async def diagnostico_cmd(m: Message) -> None:
        if ctx.imagenes is None:
            await decir(m.bot, m.chat.id, "La generación de imágenes no está configurada.")
            return
        await decir(m.bot, m.chat.id, "Revisando proveedores (sin generar imágenes)…")
        a = ctx.ajustes
        modelo = ctx.config.get("proveedores", {}).get("llm_local", {}).get("modelo", "")
        ollama = (await _estado_ollama(a.ollama_url, modelo) if ctx.imagenes.llm
                  else "apagado en el MVP; se usa la idea tal cual")
        await decir(m.bot, m.chat.id, f"Proveedores de imágenes, en orden:\n{await ctx.imagenes.diagnosticar()}\n"
                       f"LLM local (mejora los prompts): {ollama}")

    @r.message(Command("reentrenar"))
    async def reentrenar_cmd(m: Message) -> None:
        if entrenando.locked():
            await decir(m.bot, m.chat.id, "Ya hay un entrenamiento en curso. Te aviso cuando termine.")
            return
        async with entrenando:
            await decir(m.bot, m.chat.id, "Entrenando el router con tus ejemplos y correcciones. "
                           "Tarda unos minutos; mientras tanto sigo atendiendo.")
            try:
                meta = await asyncio.to_thread(ctx.router.reentrenar)
            except ValueError as e:
                await decir(m.bot, m.chat.id, str(e))
                return
            except Exception:  # noqa: BLE001 - se informa y se sigue con el modelo anterior
                log.exception("Falló el reentrenamiento del router")
                await decir(m.bot, m.chat.id, "El entrenamiento falló; sigo con el modelo anterior. "
                               "Los detalles están en los registros (./hub.sh logs).")
                return
        await decir(m.bot, m.chat.id, f"Router reentrenado con {meta['ejemplos']} ejemplos "
                       f"({meta.get('correcciones', 0)} correcciones, {meta.get('aprendidos', 0)} "
                       f"aprendidos de la IA) en {meta['segundos']} s.")

    @r.message(F.voice | F.audio)
    async def voz_msg(m: Message, bot: Bot) -> None:
        if ctx.voz is None:
            await decir(m.bot, m.chat.id, "La transcripción de voz no está configurada.")
            return
        medio = m.voice or m.audio
        try:
            texto = await ctx.voz.transcribir(await _descargar(bot, medio.file_id))
        except ErrorVoz as e:
            log.warning("No se pudo transcribir una nota de voz: %s", e)
            await decir(m.bot, m.chat.id, f"No pude transcribir la nota de voz: {e}")
            return
        except OSError as e:
            log.warning("No se pudo descargar la nota de voz: %s", e)
            await decir(m.bot, m.chat.id, "No pude descargar la nota de voz de Telegram. Inténtalo de nuevo.")
            return
        if not texto:
            await decir(m.bot, m.chat.id, "No entendí nada en la nota de voz. ¿Puedes repetirla?")
            return
        log.info("Nota de voz transcrita (%d caracteres)", len(texto))
        await procesar_hablado(m, bot, texto)

    async def procesar_hablado(m: Message, bot: Bot, texto: str) -> None:
        """Una orden directa se ejecuta como su comando; si no, decide el router."""
        if await respuesta_de_nombre(m, texto) or await orden_directa(m, texto, "voz"):
            return
        orden = orden_hablada(texto)
        if orden is None:
            await resolver(m, bot, await ctx.router.decidir(texto), texto, origen="voz")
            return
        comando, args = orden
        if comando == "proyecto":
            await proyecto(m, args)
        elif comando == "nota":
            await nota(m, args, origen="voz")
        elif comando == "tarea":
            await tarea(m, args, origen="voz")
        elif comando == "tareas":
            await tareas(m)
        elif comando == "estado":
            await estado(m)
        elif comando == "img":
            await generar_imagen(bot, m.chat.id, args)

    @r.message(F.text.startswith("/"))
    async def comando_desconocido(m: Message) -> None:
        await decir(m.bot, m.chat.id, "Comando no reconocido. Usa /ayuda para ver la lista.")

    # --- texto libre ------------------------------------------------------------
    @r.message(F.text)
    async def texto_libre(m: Message, bot: Bot) -> None:
        if await respuesta_de_nombre(m, m.text) or await orden_directa(m, m.text, "telegram"):
            return
        decision = await ctx.router.decidir(m.text)
        await resolver(m, bot, decision, m.text)

    async def resolver(m: Message, bot: Bot, d: Decision, texto: str, origen: str = "telegram") -> None:
        chat = m.chat.id
        nivel = ctx.router.nivel(d)
        # Sin el contenido del mensaje: solo lo que decidió el router, para revisar pruebas.
        log.info("Mensaje (%s, %d caracteres): %s/%s por %s, confianza %.2f -> %s", origen, len(texto),
                 d.accion, d.tipo, d.motor, d.confianza, nivel)
        if d.accion == "personaje":
            # Solo lo propone la IA (ChatGPT): trae nombre y descripción sacados de la frase.
            nombre, descripcion = d.extra.get("personaje"), d.extra.get("descripcion", "")
            if nivel == "ejecutar":
                await personaje(m, nombre, descripcion, texto, origen)
                return
            clave = ctx.guardar_pendiente(tipo="personaje_ia", texto=texto, nombre=nombre,
                                          descripcion=descripcion, tipo_nota="historia", chat=chat,
                                          propuesta="personaje", origen=origen)
            await decir(m.bot, m.chat.id, f"¿Creo la ficha del personaje {nombre or '(sin nombre)'}?",
                           reply_markup=teclado([[("Crear ficha", f"pf:{clave}"),
                                                  ("Guardar como nota", f"a:nota:{clave}")],
                                                 [("Cancelar", f"x:{clave}")]]))
            return
        if d.accion in ("nota", "tarea") and nivel == "ejecutar":
            aprender(texto, d)
            await decir(m.bot, m.chat.id, ejecutar(d.accion, texto, d.tipo, chat, origen))
            return
        if d.accion == "imagen" and nivel == "ejecutar":
            aprender(texto, d)
            await generar_imagen(bot, chat, texto)
            return
        if d.accion == "consulta" and nivel == "ejecutar" and ctx.openclaw:
            aprender(texto, d)
            await consultar(bot, chat, texto)
            return
        if d.accion == "analisis" and nivel == "ejecutar" and ctx.openclaw:
            # "Ejecutar" aquí es preparar: el análisis igual pide elegir el modelo con botones.
            aprender(texto, d)
            await pedir_analisis(bot, chat, texto)
            return
        clave = ctx.guardar_pendiente(tipo="texto", texto=texto, tipo_nota=d.tipo, chat=chat,
                                      propuesta=d.accion, origen=origen)
        if d.accion in llega:
            mensaje = (f"Parece un pedido de {NOMBRES[d.accion]}; esa función llega el {llega[d.accion]}. "
                       f"¿Lo guardo mientras tanto en {destino(chat)}?")
        elif d.accion == "consulta":
            mensaje = f"¿Es una consulta? Puedo responderla (botón Consulta) o guardarla en {destino(chat)}."
        elif d.accion == "analisis":
            mensaje = (f"¿Es un pedido de análisis? Puedo prepararlo (botón Análisis) o guardarlo "
                       f"en {destino(chat)}.")
        elif nivel == "confirmar":
            mensaje = f"¿Lo guardo como {d.accion} en {destino(chat)}?"
        else:
            mensaje = f"¿Qué hago con esto? Destino: {destino(chat)}"
        await decir(m.bot, m.chat.id, mensaje, reply_markup=teclado_acciones(clave, d.accion, d.tipo))

    # --- botones ---------------------------------------------------------------
    async def cerrar(c: CallbackQuery, texto: str) -> None:
        if _hablado.get() and isinstance(c.message, Message):
            await c.message.edit_reply_markup(reply_markup=None)
            await c.answer()
            await decir(c.bot, c.message.chat.id, texto)
            return
        if isinstance(c.message, Message):
            await c.message.edit_text(texto)
        else:
            await c.answer(texto, show_alert=True)
            return
        await c.answer()

    async def vencido(c: CallbackQuery) -> None:
        await c.answer("Esta opción ya venció. Envía el mensaje de nuevo.", show_alert=True)

    @r.callback_query(F.data.startswith("a:"))
    async def cb_accion(c: CallbackQuery) -> None:
        _, accion, clave = c.data.split(":", 2)
        p = ctx.tomar_pendiente(clave)
        if not p:
            await vencido(c)
            return
        # Si el router propuso una función que aún no existe, elegir nota o tarea es
        # "guárdalo mientras tanto", no una corrección: no se registra.
        if p.get("propuesta") not in llega:
            registrar(p["texto"], accion)
        await cerrar(c, ejecutar(accion, p["texto"], p.get("tipo_nota", "general"), p["chat"],
                                 p.get("origen", "telegram")))

    @r.callback_query(F.data.startswith("o:"))
    async def cb_otra_accion(c: CallbackQuery) -> None:
        _, accion, clave = c.data.split(":", 2)
        p = ctx.tomar_pendiente(clave)
        if not p or accion not in OTRAS:
            await vencido(c)
            return
        registrar(p["texto"], accion)
        if accion == "consulta" and ctx.openclaw:
            await cerrar(c, "Consultando…")
            await consultar(c.bot, p["chat"], p["texto"])
            return
        if accion == "imagen":
            await cerrar(c, "Anotado: aprenderé que esto es un pedido de imagen.")
            await generar_imagen(c.bot, p["chat"], p["texto"])
            return
        if accion == "analisis" and ctx.openclaw:
            await cerrar(c, "Anotado: preparo el análisis.")
            await pedir_analisis(c.bot, p["chat"], p["texto"])
            return
        tipo = p.get("tipo_nota", "general")
        nueva = ctx.guardar_pendiente(tipo="texto", texto=p["texto"], tipo_nota=tipo, chat=p["chat"],
                                      propuesta=accion, origen=p.get("origen", "telegram"))
        texto = (f"Anotado: aprenderé que esto es {NOMBRES[accion]}. Esa función llega el "
                 f"{llega[accion]}. ¿Lo guardo mientras tanto en {destino(p['chat'])}?")
        if _hablado.get() and isinstance(c.message, Message):
            await c.message.edit_reply_markup(reply_markup=None)
            await decir(c.bot, c.message.chat.id, texto,
                        reply_markup=teclado_acciones(nueva, accion, tipo, otras=False))
        elif isinstance(c.message, Message):
            await c.message.edit_text(texto, reply_markup=teclado_acciones(nueva, accion, tipo, otras=False))
        await c.answer()

    @r.callback_query(F.data.startswith("an:"))
    async def cb_analisis(c: CallbackQuery) -> None:
        _, indice, clave = c.data.split(":", 2)
        p = ctx.tomar_pendiente(clave)
        if not p or not indice.isdigit() or int(indice) >= len(p["opciones"]) or not ctx.openclaw:
            await vencido(c)
            return
        opcion = p["opciones"][int(indice)]
        esfuerzos = opcion.lista_esfuerzos()
        if len(esfuerzos) == 1:
            await empezar_analisis(c, p, opcion.con_esfuerzo(esfuerzos[0]))
            return
        datos = {k: v for k, v in p.items() if k not in ("creado", "reintento")}
        nueva = ctx.guardar_pendiente(**{**datos, "opcion": opcion})
        await reemplazar(c, f"Modelo: {opcion.nombre}. ¿Con qué esfuerzo lo analizo?\n"
                            "Más esfuerzo: análisis más profundo, pero más lento y con más tokens de salida.",
                         teclado_esfuerzo(nueva, opcion), voz="Elige el esfuerzo del modelo en los botones.")

    @r.callback_query(F.data.startswith("ef:"))
    async def cb_esfuerzo(c: CallbackQuery) -> None:
        _, esfuerzo, clave = c.data.split(":", 2)
        p = ctx.tomar_pendiente(clave)
        opcion = p.get("opcion") if p else None
        if opcion is None or esfuerzo not in opcion.lista_esfuerzos() or not ctx.openclaw:
            await vencido(c)
            return
        await empezar_analisis(c, p, opcion.con_esfuerzo(esfuerzo))

    @r.callback_query(F.data.startswith("re:"))
    async def cb_reintentar(c: CallbackQuery) -> None:
        p = ctx.tomar_pendiente(c.data.split(":", 1)[1])
        if not p or not p.get("reintento") or not ctx.openclaw:
            await vencido(c)
            return
        await empezar_analisis(c, p, p["reintento"])

    async def empezar_analisis(c: CallbackQuery, p: dict[str, Any], opcion: analisis.Opcion) -> None:
        await cerrar(c, f"Analizando con {opcion.nombre} (esfuerzo {analisis.nombre_esfuerzo(opcion)})… "
                        "puede tardar unos minutos.")
        # Para un posible fallo: se ofrecen de nuevo todos los modelos menos el que falló.
        todas = p.get("todas") or p["opciones"]
        await hacer_analisis(c.bot, {**p, "opciones": todas, "todas": todas}, opcion)

    @r.callback_query(F.data.startswith("mo:"))
    async def cb_modelo(c: CallbackQuery) -> None:
        modelo = c.data.split(":", 1)[1]
        opcion = next((o for o in analisis.opciones_desde_config(ctx.config) if o.modelo == modelo), None)
        if opcion is None:
            await vencido(c)
            return
        chat = c.message.chat.id if c.message else c.from_user.id
        ctx.estado.fijar_preferencia(chat, analisis.PREFERENCIA, opcion.modelo)
        await cerrar(c, f"Listo: el modelo de análisis predeterminado es {opcion.nombre}.")

    @r.callback_query(F.data.startswith("x:"))
    async def cb_cancelar(c: CallbackQuery) -> None:
        ctx.tomar_pendiente(c.data.split(":", 1)[1])
        await cerrar(c, "Cancelado. No se guardó nada.")

    @r.callback_query(F.data.startswith("p:"))
    async def cb_proyecto(c: CallbackQuery) -> None:
        valor = c.data.split(":", 1)[1]
        chat = c.message.chat.id if c.message else c.from_user.id
        if valor == "-":
            ctx.estado.fijar_proyecto(chat, None)
            await cerrar(c, "Sin proyecto activo: todo irá a 00-Bandeja.")
            return
        lista = ctx.boveda.listar_proyectos()
        indice = int(valor)
        if indice >= len(lista):
            await vencido(c)
            return
        ctx.estado.fijar_proyecto(chat, lista[indice])
        await cerrar(c, f"Proyecto activo: {lista[indice]}")

    @r.callback_query(F.data.startswith("np:"))
    async def cb_nuevo_proyecto(c: CallbackQuery) -> None:
        p = ctx.tomar_pendiente(c.data.split(":", 1)[1])
        if not p:
            await vencido(c)
            return
        try:
            creado = ctx.boveda.crear_proyecto(p["nombre"])
        except ValueError as e:
            await cerrar(c, str(e))
            return
        ctx.estado.fijar_proyecto(p["chat"], creado)
        await cerrar(c, f"Proyecto {creado} listo con sus carpetas. Es el proyecto activo.")

    @r.callback_query(F.data.startswith("r:"))
    async def cb_referencia(c: CallbackQuery) -> None:
        p = ctx.tomar_pendiente(c.data.split(":", 1)[1])
        if not p:
            await vencido(c)
            return
        await cerrar(c, await guardar_referencia(c.bot, p["chat"], p["file_id"], p["ext"], p["pie"]))

    @r.callback_query(F.data.startswith("pi:"))
    async def cb_personaje_como_idea(c: CallbackQuery) -> None:
        p = ctx.tomar_pendiente(c.data.split(":", 1)[1])
        if not p:
            await vencido(c)
            return
        ctx.esperando_nombre.pop(p["chat"], None)
        await cerrar(c, ejecutar("nota", p["texto"], "historia", p["chat"], p["origen"]))

    @r.callback_query(F.data.startswith("pf:"))
    async def cb_personaje_ia(c: CallbackQuery) -> None:
        p = ctx.tomar_pendiente(c.data.split(":", 1)[1])
        if not p or not isinstance(c.message, Message):
            await vencido(c)
            return
        await c.answer()
        await personaje(c.message, p["nombre"], p["descripcion"], p["texto"], p["origen"])

    @r.callback_query(F.data.startswith("cp:"))
    async def cb_crear_personaje(c: CallbackQuery) -> None:
        p = ctx.tomar_pendiente(c.data.split(":", 1)[1])
        if not p:
            await vencido(c)
            return
        proyecto = ctx.estado.proyecto_activo(p["chat"])
        if not proyecto:
            await cerrar(c, "Primero elige un proyecto con /proyecto.")
            return
        nota = referencias.crear_personaje(ctx.boveda, proyecto, p["personaje"])
        await cerrar(c, await insertar_personaje(c.bot, proyecto, nota, p["personaje"],
                                                 p["file_id"], p["ext"]))

    return r


async def _constante(texto: str) -> str:
    return texto


async def _estado_ollama(url: str, modelo: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=2) as cli:
            resp = await cli.get(f"{url}/api/tags")
            resp.raise_for_status()
        nombres = [m.get("name", "") for m in resp.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        return "sin respuesta"
    if modelo and not any(n == modelo or n.startswith(modelo + ":") for n in nombres):
        return f"responde, pero falta el modelo {modelo} (ver descargar_modelos)"
    return f"responde ({len(nombres)} modelos)"


async def _estado_openclaw(url: str, token: str) -> str:
    if not token:
        return "no activado (día 5)"
    # Petición vacía al plugin hub-puente: no llega al modelo. 400 = token y plugin bien.
    try:
        async with httpx.AsyncClient(timeout=2) as cli:
            resp = await cli.post(f"{url}/hub/completar", json={},
                                  headers={"Authorization": f"Bearer {token}"})
        return {400: "responde", 401: "rechaza el token",
                404: "falta el plugin hub-puente"}.get(resp.status_code, f"error {resp.status_code}")
    except httpx.HTTPError:
        return "sin respuesta"


def crear_bot(ctx: Contexto) -> tuple[Bot, Dispatcher]:
    bot = Bot(ctx.ajustes.telegram_token)
    dp = Dispatcher()
    filtro = SoloAutorizados(ctx.ajustes.usuarios)
    dp.message.outer_middleware(filtro)
    dp.callback_query.outer_middleware(filtro)
    dp.message.middleware(ModoVoz())
    dp.callback_query.middleware(ModoVoz())
    dp.include_router(crear_router(ctx))
    return bot, dp


async def preparar(bot: Bot) -> str | None:
    """Comprueba que nadie más lee este bot y publica el menú de comandos.

    Devuelve un mensaje de error si hay otro proceso leyendo (error 409).
    """
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await bot.get_updates(limit=1, timeout=0)
    except TelegramConflictError:
        return ("Otro proceso está leyendo este bot de Telegram (error 409). "
                "Detén el stack en el otro equipo y desactiva el canal de Telegram de "
                "cualquier OpenClaw que tengas instalado fuera de este proyecto.")
    except TelegramUnauthorizedError:
        return "Telegram rechazó el token. Revisa TELEGRAM_TOKEN en .env (lo da @BotFather)."
    except TelegramNetworkError as e:
        return f"No hay conexión con Telegram ({e}). Docker reintentará en unos segundos."
    await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMANDOS])
    return None
