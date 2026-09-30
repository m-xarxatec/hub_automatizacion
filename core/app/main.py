"""Punto de entrada: python -m app.main"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from . import config as config_mod
from .ajustes import Ajustes
from .boveda.proyectos import Boveda
from .entradas import telegram_bot
from .entradas.web import servidor as web
from .estado import latido, limpieza
from .estado.db import Estado
from .acciones.imagenes import GeneradorImagenes
from .proveedores.cadena import crear_cadena
from .proveedores.ollama import Ollama
from .proveedores.openclaw import Nivel, OpenClaw, cadena_desde_config
from .router.llm_local import LLMLocal
from .router.interprete import Interprete
from .acciones.redactor import Redactor
from .router.llm_openclaw import OpinionIA
from .voz.cliente import ClienteVoz
from .router.cascada import Router

log = logging.getLogger("hub")


class FormatoJSON(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        datos = {"hora": self.formatTime(registro, "%Y-%m-%dT%H:%M:%S"), "nivel": registro.levelname,
                 "modulo": registro.name, "mensaje": registro.getMessage()}
        if registro.exc_info:
            datos["error"] = self.formatException(registro.exc_info)
        return json.dumps(datos, ensure_ascii=False)


def configurar_logs(carpeta: Path, dias: int) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    archivo = TimedRotatingFileHandler(carpeta / "hub.log", when="midnight", backupCount=dias,
                                       encoding="utf-8")
    archivo.setFormatter(FormatoJSON())
    logging.basicConfig(level=logging.INFO, handlers=[consola, archivo], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def principal() -> int:
    ajustes = Ajustes.desde_entorno()
    cfg = config_mod.cargar(ajustes.config_path)
    configurar_logs(ajustes.datos / "logs", int(cfg["limpieza"].get("logs_dias", 14)))

    if not ajustes.telegram_token:
        log.error("Falta TELEGRAM_TOKEN en .env")
        return 1
    if not ajustes.boveda.exists():
        log.error("La bóveda no está montada en %s. Revisa VAULT_PATH en .env", ajustes.boveda)
        return 1
    if not ajustes.usuarios:
        log.warning("TELEGRAM_USUARIOS vacío: modo configuración, el bot solo responde con el ID.")

    boveda = Boveda(ajustes.boveda, cfg, ajustes.zona)
    boveda.asegurar_base()

    vigencia = int(cfg["latido"].get("vigencia_s", 180))
    choque = latido.conflicto(boveda.interna, ajustes.servidor_nombre, vigencia)
    if choque and not ajustes.forzar_arranque:
        log.error(choque)
        return 2

    (ajustes.datos / "tmp").mkdir(parents=True, exist_ok=True)
    estado = Estado(ajustes.datos / "hub.sqlite3")
    cfg_router = cfg["router"]
    cfg_llm = cfg["proveedores"]["llm_local"]
    llm_activo = bool(cfg_llm.get("activo", True))
    openclaw = (OpenClaw(ajustes.openclaw_url, ajustes.openclaw_token,
                         cadena_desde_config(cfg["proveedores"].get("consulta")))
                if ajustes.openclaw_token else None)
    # Si el router duda: ChatGPT → Haiku (OpenClaw); sin OpenClaw, qwen local si está activo.
    # Con un tope corto (llm_timeout_s): si tarda, mejor los botones que esperar.
    if openclaw:
        llm = OpinionIA(OpenClaw(openclaw.url, openclaw.token, openclaw.cadena,
                                 timeout=float(cfg_router.get("llm_timeout_s", 15))),
                        list(cfg_router.get("acciones", [])))
    elif llm_activo:
        llm = LLMLocal(Ollama(ajustes.ollama_url, cfg_llm["modelo"],
                              timeout=float(cfg_router.get("llm_timeout_s", 15))),
                       list(cfg_router.get("acciones", [])))
    else:
        llm = None
    router = Router(cfg, ajustes.datos / "router", llm=llm)
    ollama_prompts = Ollama(ajustes.ollama_url, cfg_llm["modelo"], timeout=30) if llm_activo else None
    imagenes = GeneradorImagenes(boveda, crear_cadena(cfg, estado=estado), ollama_prompts)
    # Intérprete con GPT (prioridad en los mensajes libres); el router local queda de respaldo.
    cfg_int = cfg_router.get("interprete") or {}
    cadena_int = ((Nivel(str(cfg_int["modelo"]), str(cfg_int.get("razonamiento", "low"))),)
                  if cfg_int.get("modelo") else openclaw.cadena if openclaw else ())
    interprete = (Interprete(OpenClaw(openclaw.url, openclaw.token, cadena_int,
                                      timeout=float(cfg_int.get("timeout_s", 20))),
                             max_tokens=int(cfg_int.get("max_tokens", 400)))
                  if openclaw and cfg_int.get("activo", True) else None)
    # Redactor (2026-09-30): decide qué escribir y dónde con el contenido real del proyecto.
    cfg_red = cfg["proveedores"].get("redactor") or {}
    redactor = (Redactor(OpenClaw(openclaw.url, openclaw.token, openclaw.cadena),
                         Nivel(str(cfg_red["modelo"]), str(cfg_red.get("razonamiento", "low"))),
                         max_tokens=int(cfg_red.get("max_tokens", 3000)),
                         tope_contexto_tokens=int(cfg_red.get("tope_contexto_tokens", 12000)),
                         tiempo_max_s=float(cfg_red.get("timeout_s", 90)))
                if openclaw and cfg_red.get("activo", True) and cfg_red.get("modelo") else None)
    ctx = telegram_bot.Contexto(ajustes, cfg, boveda, estado, router, imagenes,
                                ClienteVoz(ajustes.voz_url, vocabulario=cfg["voz"].get("vocabulario") or ""),
                                openclaw, interprete, redactor)
    bot, dp = telegram_bot.crear_bot(ctx)

    error = await telegram_bot.preparar(bot)
    if error:
        log.error(error)
        await bot.session.close()
        return 3

    latido.escribir(boveda.interna, ajustes.servidor_nombre)
    web_srv = web.servidor(web.crear_app(ajustes.servidor_nombre))
    tareas = [
        asyncio.create_task(latido.bucle(boveda.interna, ajustes.servidor_nombre,
                                         int(cfg["latido"].get("intervalo_s", 60)))),
        asyncio.create_task(limpieza.bucle(ajustes.datos, boveda.raiz, cfg["limpieza"], ajustes.zona)),
        asyncio.create_task(web_srv.serve()),
    ]
    if ollama_prompts:
        tareas.append(asyncio.create_task(ollama_prompts.precargar()))
    log.info("Hub activo en '%s'. Bóveda: %s. Router: %s", ajustes.servidor_nombre,
             ajustes.boveda, router.motor)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        web_srv.should_exit = True
        for t in tareas:
            t.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)
        await bot.session.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
