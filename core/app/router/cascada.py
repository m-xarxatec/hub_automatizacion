"""Cascada del router: comando -> reglas y clasificador local -> IA si duda -> botones.

Los comandos (/nota, /tarea...) los resuelve directamente el bot.
Aquí solo llega texto libre o imágenes con pie de foto.

La IA (ChatGPT → Haiku por OpenClaw; o el LLM local si no hay OpenClaw) solo se consulta
cuando hay duda: confianza por debajo de umbral_ejecutar, o una contradicción (una
pregunta que el clasificador toma por nota o tarea). Cada nivel es más caro que el
anterior y solo se sube si hace falta.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from . import clasificador, ejemplos, evaluacion, reglas
from .reglas import Decision


class SegundaOpinion(Protocol):
    # True si una opinión segura puede ejecutarse sin confirmar (ChatGPT sí, qwen no).
    confiable: bool

    async def opinar(self, texto: str) -> Decision | None: ...


# "…vamos a crear una elfa albina llamada Aeli": el clasificador lo toma por nota con toda
# seguridad, pero puede ser un personaje nuevo.
_CREAR_PERSONAJE = re.compile(r"\bcre(?:a|ar|es|emos|ame)\b.*\b(?:personajes?|llamad[oa]s?)\b")


def contradice(texto: str, decision: Decision) -> bool:
    """Casos en que el clasificador puede estar seguro y equivocado: mejor que opine la IA.

    - Una pregunta ("¿y se hace por viñeta?") no suele ser nota ni tarea.
    - "Crear" junto a "personaje" o "llamado/a" puede ser un personaje nuevo.
    """
    if decision.accion not in ("nota", "tarea"):
        return False
    if texto.strip().rstrip(" .!").endswith("?"):
        return True
    return decision.accion == "nota" and bool(_CREAR_PERSONAJE.search(reglas.normalizar(texto)))


class Router:
    def __init__(self, config: dict, carpeta: Path, llm: SegundaOpinion | None = None):
        cfg = config.get("router", {})
        self.umbral_ejecutar = float(cfg.get("umbral_ejecutar", 0.80))
        self.umbral_confirmar = float(cfg.get("umbral_confirmar", 0.50))
        self.umbral_ia = float(cfg.get("umbral_ia_ejecutar", 0.85))
        self.acciones = list(cfg.get("acciones", []))
        self.acciones_texto = ejemplos.acciones_de_texto(self.acciones)
        self.llm = llm if cfg.get("segunda_opinion", True) else None
        # Cómo se entrena (base, iteraciones, épocas, vocabulario congelado): config.yaml.
        self.entrenamiento = dict(cfg.get("entrenamiento") or {})
        # carpeta = /datos/router: el modelo va en modelo/ y las correcciones al lado.
        self.carpeta = carpeta
        self.carpeta_modelo = carpeta / "modelo"
        self.clasificador = clasificador.cargar(self.carpeta_modelo)

    @property
    def motor(self) -> str:
        if self.clasificador:
            meta = self.clasificador.metadatos
            correcciones = max(len(ejemplos.leer_correcciones(self.carpeta)) - int(meta.get("correcciones", 0)), 0)
            aprendidos = max(len(ejemplos.leer_aprendidos(self.carpeta)) - int(meta.get("aprendidos", 0)), 0)
            texto = (f"clasificador local ({meta.get('ejemplos', '?')} ejemplos; sin entrenar: "
                     f"{correcciones} correcciones, {aprendidos} aprendidos de la IA)")
        else:
            texto = "reglas (sin modelo entrenado: usa /reentrenar)"
        if self.llm is None:
            return texto
        return texto + (" + IA si duda (OpenClaw)" if getattr(self.llm, "confiable", False) else " + LLM local")

    async def decidir(self, texto: str, tiene_imagen: bool = False, sin_ia: bool = False) -> Decision:
        """`sin_ia`: solo reglas y SetFit (el intérprete con GPT ya falló; no se reintenta)."""
        # Las imágenes con pie de foto siempre pasan por reglas: son patrones fijos.
        if tiene_imagen:
            return reglas.decidir(texto, tiene_imagen=True)
        decision = reglas.decidir(texto)
        modelo = self.clasificador
        if modelo:
            propuesta = await asyncio.to_thread(modelo.predecir, texto)
            if propuesta.accion in self.acciones_texto and propuesta.confianza >= self.umbral_confirmar:
                decision = propuesta
        if sin_ia or self.llm is None or (self.nivel(decision) == "ejecutar" and not contradice(texto, decision)):
            return decision
        if contradice(texto, decision):
            # Mientras la IA no opine, que no se guarde sola: como mucho, con confirmación.
            decision = replace(decision, confianza=min(decision.confianza, self.umbral_ejecutar - 0.01))
        return self.combinar(decision, await self.llm.opinar(texto))

    def combinar(self, base: Decision, opinion: Decision | None) -> Decision:
        """Une la decisión local con la opinión de la IA.

        - Coinciden: la confianza sube la mitad de lo que le falta para 1 (y se ejecuta si
          la IA es confiable y está segura).
        - IA confiable (ChatGPT) y segura (>= umbral_ia_ejecutar): gana la IA y se ejecuta
          directo (decisión del usuario, 2026-09-27).
        - No coinciden y la base era débil: se propone lo de la IA, pero como
          mucho con confirmación.
        - No coinciden y la base era media: se pregunta, guardando la alternativa.
        """
        if opinion is None:
            return base
        motor = f"{base.motor}+{opinion.motor}"
        # Si la IA eligió el tipo de nota, se usa el suyo: entiende mejor la frase completa.
        tipo = opinion.tipo if opinion.extra.get("tipo_ia") else base.tipo
        segura = getattr(self.llm, "confiable", False) and opinion.confianza >= self.umbral_ia
        if opinion.accion == base.accion:
            confianza = base.confianza + (1 - base.confianza) / 2
            if segura:
                confianza = max(confianza, self.umbral_ejecutar)
            return replace(base, confianza=confianza, motor=motor, tipo=tipo)
        if segura:
            return replace(opinion, confianza=max(opinion.confianza, self.umbral_ejecutar), motor=motor,
                           extra={**opinion.extra, "alternativa": base.accion})
        tope_confirmar = self.umbral_ejecutar - 0.01
        if base.confianza < self.umbral_confirmar:
            return replace(opinion, confianza=min(opinion.confianza, tope_confirmar), motor=motor,
                           extra={**opinion.extra, "alternativa": base.accion})
        return replace(base, confianza=min(base.confianza, self.umbral_confirmar - 0.01), motor=motor,
                       extra={**base.extra, "alternativa": opinion.accion})

    def nivel(self, decision: Decision) -> str:
        """'ejecutar', 'confirmar' o 'preguntar' según la confianza."""
        if decision.confianza >= self.umbral_ejecutar:
            return "ejecutar"
        if decision.confianza >= self.umbral_confirmar:
            return "confirmar"
        return "preguntar"

    # --- aprendizaje ---------------------------------------------------------------
    def registrar(self, texto: str, accion: str) -> bool:
        """Guarda lo que el usuario eligió con los botones como ejemplo nuevo."""
        if accion not in self.acciones_texto or not texto.strip():
            return False
        ejemplos.guardar_correccion(self.carpeta, texto, accion)
        return True

    def aprender(self, texto: str, decision: Decision) -> bool:
        """Si el clasificador dudó y la IA confirmó la acción (motor "clasificador+…"),
        la frase queda como ejemplo para el próximo /reentrenar."""
        if "+" not in decision.motor or decision.accion not in self.acciones_texto:
            return False
        if self.nivel(decision) != "ejecutar" or not texto.strip():
            return False
        return ejemplos.guardar_aprendido(self.carpeta, texto, decision.accion)

    def aprender_de(self, texto: str, accion: str) -> bool:
        """Lo que decidió el intérprete (GPT) donde SetFit fallaba o dudaba: ejemplo para /reentrenar."""
        if accion not in self.acciones_texto or not texto.strip():
            return False
        return ejemplos.guardar_aprendido(self.carpeta, texto, accion)

    def reentrenar(self, ruta_ejemplos: Path = ejemplos.EJEMPLOS_BASE) -> dict:
        """Entrena con ejemplos + aprendidos + correcciones y recarga el modelo. Tarda: llamar en un hilo.

        Antes de reemplazar el modelo se mide con las frases de prueba: si sale claramente peor que
        el actual, se descarta (clasificador.ModeloRechazado) y el bot sigue con el anterior.
        """
        correcciones = ejemplos.leer_correcciones(self.carpeta)
        aprendidos = ejemplos.leer_aprendidos(self.carpeta)
        textos, etiquetas = ejemplos.unir(ejemplos.leer_ejemplos(ruta_ejemplos), correcciones,
                                          self.acciones, aprendidos)
        # Una frase de prueba corregida con los botones se entrenaría: se saca de la medición.
        prueba = evaluacion.leer_pruebas()
        repetidas = set(evaluacion.solapadas(prueba, textos))
        prueba = [(t, a) for t, a in prueba if t not in repetidas]
        actual = self.clasificador
        medida_actual = evaluacion.medir(actual.predecir, prueba, self.umbral_ejecutar) if actual and prueba else None

        def control(nuevo: clasificador.Clasificador) -> tuple[str | None, dict]:
            if not prueba:
                return None, {}
            medida = evaluacion.medir(nuevo.predecir, prueba, self.umbral_ejecutar)
            datos = {"evaluacion": medida.como_dict()}
            if medida_actual:
                datos["evaluacion_anterior"] = medida_actual.como_dict()
            return evaluacion.aceptable(medida, medida_actual), datos

        opciones = {k: self.entrenamiento[k] for k in ("base", "iteraciones", "epocas", "congelar_vocabulario")
                    if k in self.entrenamiento}
        metadatos = clasificador.entrenar(textos, etiquetas, self.carpeta_modelo, **opciones,
                                          extra={"correcciones": len(correcciones),
                                                 "aprendidos": len(aprendidos)},
                                          control=control)
        self.clasificador = clasificador.cargar(self.carpeta_modelo)
        return metadatos
