"""Clasificador local con SetFit (DÍA 3).

SetFit ajusta un modelo de frases pequeño ('paraphrase-multilingual-MiniLM-L12-v2')
con pocos ejemplos por acción: primero aprende a acercar frases de la misma acción
y alejar las de acciones distintas, y luego entrena encima una regresión logística.
Corre en CPU en milisegundos, así que la GPU queda libre para Ollama.

El modelo entrenado vive en /datos/router/modelo/ (fuera del repo y de la bóveda).
Mientras no exista, cargar() devuelve None y la cascada usa las reglas.

setfit (y con él torch) se importa dentro de las funciones: importar este módulo
no carga nada pesado.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from .reglas import Decision, tipo_nota

log = logging.getLogger(__name__)

MODELO_BASE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Archivo que setfit escribe junto al modelo; si está, hay un modelo entrenado.
MARCA_MODELO = "model_head.pkl"
METADATOS = "entrenamiento.json"


class Clasificador:
    def __init__(self, carpeta: Path):
        from setfit import SetFitModel

        self.carpeta = carpeta
        self.modelo = SetFitModel.from_pretrained(str(carpeta))
        self.acciones: list[str] = [str(a) for a in self.modelo.labels]
        ruta_meta = carpeta / METADATOS
        self.metadatos: dict = json.loads(ruta_meta.read_text(encoding="utf-8")) if ruta_meta.exists() else {}

    def predecir(self, texto: str) -> Decision:
        probabilidades = self.modelo.predict_proba([texto])[0].tolist()
        indice = max(range(len(probabilidades)), key=probabilidades.__getitem__)
        return Decision(self.acciones[indice], float(probabilidades[indice]),
                        tipo=tipo_nota(texto), motor="clasificador")


def cargar(carpeta: Path) -> Clasificador | None:
    if not (carpeta / MARCA_MODELO).exists():
        return None
    try:
        return Clasificador(carpeta)
    except Exception:  # noqa: BLE001 - un modelo dañado no debe tumbar el bot
        log.exception("No se pudo cargar el clasificador en %s; se usan las reglas", carpeta)
        return None


def entrenar(textos: list[str], etiquetas: list[str], destino: Path, *,
             base: str = MODELO_BASE, iteraciones: int = 20, extra: dict | None = None) -> dict:
    """Entrena y guarda el modelo en `destino`. Devuelve los metadatos del entrenamiento.

    Se entrena en una carpeta temporal y solo al final se reemplaza la anterior:
    si algo falla a mitad, el bot sigue con el modelo viejo.
    """
    if len(set(etiquetas)) < 2:
        raise ValueError("Hacen falta ejemplos de al menos dos acciones para entrenar.")

    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments

    inicio = time.time()
    modelo = SetFitModel.from_pretrained(base, labels=sorted(set(etiquetas)))
    datos = Dataset.from_dict({"text": textos, "label": etiquetas})
    args = TrainingArguments(batch_size=16, num_epochs=1, num_iterations=iteraciones,
                             report_to="none", show_progress_bar=False)
    Trainer(model=modelo, args=args, train_dataset=datos).train()

    nuevo = destino.parent / f".{destino.name}.nuevo"
    viejo = destino.parent / f".{destino.name}.viejo"
    for carpeta in (nuevo, viejo):
        shutil.rmtree(carpeta, ignore_errors=True)
    modelo.save_pretrained(str(nuevo))
    metadatos = {
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ejemplos": len(textos),
        "por_accion": {a: etiquetas.count(a) for a in sorted(set(etiquetas))},
        "segundos": round(time.time() - inicio, 1),
        "base": base,
        **(extra or {}),
    }
    (nuevo / METADATOS).write_text(json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8")
    if destino.exists():
        destino.rename(viejo)
    nuevo.rename(destino)
    shutil.rmtree(viejo, ignore_errors=True)
    return metadatos
