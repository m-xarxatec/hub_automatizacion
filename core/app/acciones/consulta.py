"""Consultas por OpenClaw (DÍA 5).

Usa proveedores/openclaw.py (plugin hub-puente), no el agente de OpenClaw: core guarda las
últimas vueltas de la conversación en SQLite (estado operativo, por estado.sesion(chat_id);
/nuevo empieza otra) y las manda con cada pregunta.
Cadena: ChatGPT mini (razonamiento low) → Haiku (aislado, sin pensamiento). Si ninguno
responde, se avisa al usuario (después del MVP: OpenRouter :free y qwen local).

Con proyecto activo, la consulta lleva sus notas (las más relacionadas con la pregunta primero,
hasta proveedores.consulta_notas_tokens): "¿y la historia?" se responde con lo que ya escribió.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from ..boveda.proyectos import Boveda
from ..estado.db import Estado
from ..proveedores.openclaw import OpenClaw
from . import analisis

log = logging.getLogger(__name__)

SISTEMA = (
    "Eres el asistente de un autor de webtoon. Respondes en español latinoamericano, "
    "claro y breve (unas 150 palabras como máximo, salvo que pida más detalle). "
    "Si no sabes algo, dilo. Texto plano, sin tablas."
)
# Por voz (paso C): se lee en voz alta, así que corto y sin formato.
SISTEMA_VOZ = (
    "Eres el asistente de un autor de webtoon. Tu respuesta se leerá en voz alta: responde en "
    "español latinoamericano en dos o tres frases cortas, sin listas, símbolos ni formato."
)
# Últimos mensajes que se mandan como contexto: 3 preguntas con sus respuestas.
MENSAJES_HISTORIAL = 6
MAX_TOKENS = 600
# Telegram corta los mensajes a 4096 caracteres.
MAX_CARACTERES = 4000

NOTAS = ("\n\nNotas del proyecto activo «{proyecto}» del autor (úsalas si la pregunta trata de su "
         "historia, personajes o proyecto; no digas que no las tienes):\n{notas}")

SIN_RESPUESTA = ("No pude consultar ahora: ni ChatGPT ni Claude responden. "
                 "Prueba en un rato; el detalle queda en los registros.")


def notas_del_proyecto(boveda: Boveda, proyecto: str | None, pregunta: str, tope_tokens: int) -> str:
    """Notas del proyecto para la consulta ("" sin proyecto, sin notas o con tope 0)."""
    if not proyecto or tope_tokens <= 0:
        return ""
    try:
        prep = analisis.preparar(boveda, proyecto, pregunta, tope_tokens)
    except OSError:
        log.exception("No se pudieron leer las notas para la consulta")
        return ""
    if not prep.notas:
        return ""
    return prep.contexto.split(f"Notas del proyecto {proyecto}:\n", 1)[-1].strip()


async def responder(cliente: OpenClaw, estado: Estado, chat_id: int, pregunta: str,
                    zona: str = "Europe/Madrid", breve: bool = False, notas: str = "",
                    proyecto: str | None = None) -> str:
    """Respuesta para el usuario (o el aviso de que no se pudo). `breve`: para leerla en voz alta.
    `notas`: las del proyecto activo (notas_del_proyecto)."""
    sesion = estado.sesion(chat_id)
    historial = estado.historial(sesion)[-MENSAJES_HISTORIAL:]
    sistema = SISTEMA_VOZ if breve else SISTEMA
    if notas:
        sistema += NOTAS.format(proyecto=proyecto or "", notas=notas)
    r = await cliente.completar(historial + [("user", pregunta)], sistema,
                                MAX_TOKENS // 3 if breve else MAX_TOKENS)
    if r is None:
        return SIN_RESPUESTA
    estado.agregar_vuelta(sesion, pregunta, r.texto, guardar=MENSAJES_HISTORIAL)
    estado.sumar_gasto(datetime.now(ZoneInfo(zona)).date().isoformat(), r.modelo)
    texto = r.texto
    if len(texto) > MAX_CARACTERES:
        texto = texto[:MAX_CARACTERES].rstrip() + "…"
    return texto
