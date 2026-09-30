"""Control de calidad del clasificador: mide un modelo con frases que nunca se entrenan.

Lo usa /reentrenar antes de reemplazar el modelo del bot: si el nuevo es claramente peor que el
actual (menos aciertos o más errores graves), se descarta y el bot sigue con el anterior. Así un
reentrenamiento con correcciones raras nunca deja al router peor de lo que estaba.

Las frases están en datos/prueba.yaml y datos/prueba_ciega.yaml (en el repo). Nunca deben estar
en ejemplos.yaml: una prueba lo vigila. Medir las ~270 frases tarda unos segundos en CPU.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import yaml

from .reglas import Decision, normalizar

DATOS = Path(__file__).parent / "datos"
PRUEBAS = (DATOS / "prueba.yaml", DATOS / "prueba_ciega.yaml")

# Cuánto peor puede salir un modelo nuevo y aun así aceptarse (el azar del entrenamiento
# mueve una o dos frases entre un entrenamiento y otro).
TOLERANCIA_ACIERTOS = 0.02      # 2 puntos porcentuales
TOLERANCIA_EJECUTA_MAL = 2      # frases
MINIMO_SIN_MODELO = 0.80        # si no hay modelo con qué comparar


@dataclass
class Medida:
    frases: int
    acierta: int
    ejecuta_mal: int   # seguro (>= umbral de ejecutar), equivocado y sin preguntar

    @property
    def porcentaje(self) -> float:
        return self.acierta / self.frases if self.frases else 0.0

    def resumen(self) -> str:
        return f"acierta el {self.porcentaje:.0%} ({self.acierta}/{self.frases}), {self.ejecuta_mal} errores graves"

    def como_dict(self) -> dict:
        return {**asdict(self), "porcentaje": round(self.porcentaje, 4)}


def leer_prueba(ruta: Path) -> list[tuple[str, str]]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return [(str(t), accion) for accion, textos in datos.items() for t in textos]


def leer_pruebas(rutas: tuple[Path, ...] = PRUEBAS) -> list[tuple[str, str]]:
    return [par for ruta in rutas if ruta.exists() for par in leer_prueba(ruta)]


def solapadas(prueba: list[tuple[str, str]], textos_entrenamiento: list[str]) -> list[str]:
    """Frases de prueba que también se entrenan (inflarían la medición)."""
    vistas = {normalizar(t) for t in textos_entrenamiento}
    return [t for t, _ in prueba if normalizar(t) in vistas]


def medir(predecir: Callable[[str], Decision], prueba: list[tuple[str, str]], umbral_ejecutar: float) -> Medida:
    acierta = ejecuta_mal = 0
    for texto, esperada in prueba:
        d = predecir(texto)
        if d.accion == esperada:
            acierta += 1
        elif d.confianza >= umbral_ejecutar:
            ejecuta_mal += 1
    return Medida(len(prueba), acierta, ejecuta_mal)


def aceptable(nueva: Medida, actual: Medida | None) -> str | None:
    """None si el modelo nuevo puede reemplazar al actual; si no, el motivo."""
    if actual is None:
        if nueva.porcentaje < MINIMO_SIN_MODELO:
            return f"el modelo nuevo {nueva.resumen()} (mínimo {MINIMO_SIN_MODELO:.0%})"
        return None
    if nueva.porcentaje < actual.porcentaje - TOLERANCIA_ACIERTOS:
        return f"el nuevo {nueva.resumen()}; el actual {actual.resumen()}"
    if nueva.ejecuta_mal > actual.ejecuta_mal + TOLERANCIA_EJECUTA_MAL:
        return f"el nuevo tiene más errores graves ({nueva.ejecuta_mal} contra {actual.ejecuta_mal})"
    return None
