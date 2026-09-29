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
import tempfile
import time
from pathlib import Path
from typing import Callable

from .reglas import Decision, tipo_nota

log = logging.getLogger(__name__)

MODELO_BASE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Archivo que setfit escribe junto al modelo; si está, hay un modelo entrenado.
MARCA_MODELO = "model_head.pkl"
METADATOS = "entrenamiento.json"


class ModeloRechazado(Exception):
    """El modelo nuevo salió peor que el actual en las pruebas: se descartó y sigue el anterior."""

    def __init__(self, motivo: str, metadatos: dict):
        self.motivo, self.metadatos = motivo, metadatos
        super().__init__(motivo)


class Clasificador:
    def __init__(self, carpeta: Path, modelo=None):
        from setfit import SetFitModel

        self.carpeta = carpeta
        self.modelo = modelo if modelo is not None else SetFitModel.from_pretrained(str(carpeta))
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
             base: str = MODELO_BASE, iteraciones: int = 20, epocas: int = 1,
             congelar_vocabulario: bool = False, extra: dict | None = None,
             control: Callable[["Clasificador"], tuple[str | None, dict]] | None = None) -> dict:
    """Entrena y guarda el modelo en `destino`. Devuelve los metadatos del entrenamiento.

    Se entrena en una carpeta temporal y solo al final se reemplaza la anterior:
    si algo falla a mitad, el bot sigue con el modelo viejo.
    `iteraciones`: pares de frases por ejemplo (más pares, más fino y más lento).
    `epocas`: pasadas sobre esos pares. Usa la GPU si torch la ve (si no, CPU).
    `congelar_vocabulario`: no ajusta la tabla de palabras (en estos modelos multilingües es la
    mayor parte de los parámetros). Con pocos ejemplos no hay nada que aprenderle, y así un modelo
    base grande cabe en una GPU de 4 GB.
    `control`: recibe el modelo nuevo antes de reemplazar al actual y devuelve (motivo, datos). Con
    un motivo, el nuevo se descarta y se lanza ModeloRechazado; los datos van a los metadatos.
    """
    if len(set(etiquetas)) < 2:
        raise ValueError("Hacen falta ejemplos de al menos dos acciones para entrenar.")

    import torch
    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments

    inicio = time.time()
    modelo = SetFitModel.from_pretrained(base, labels=sorted(set(etiquetas)))
    if congelar_vocabulario:
        modelo.model_body[0].auto_model.embeddings.word_embeddings.requires_grad_(False)
    datos = Dataset.from_dict({"text": textos, "label": etiquetas})
    # Sin checkpoints (por defecto SetFit guarda GB en ./checkpoints, y /app no es escribible
    # porque core corre con el usuario del equipo): solo una carpeta de trabajo temporal.
    destino.parent.mkdir(parents=True, exist_ok=True)
    trabajo = Path(tempfile.mkdtemp(prefix=".entrenando-", dir=destino.parent))
    try:
        args = TrainingArguments(output_dir=str(trabajo), save_strategy="no", batch_size=16, num_epochs=epocas,
                                 num_iterations=iteraciones, report_to="none", show_progress_bar=False)
        Trainer(model=modelo, args=args, train_dataset=datos).train()
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)

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
        "iteraciones": iteraciones,
        "epocas": epocas,
        "congelar_vocabulario": congelar_vocabulario,
        "dispositivo": "gpu" if torch.cuda.is_available() else "cpu",
        **(extra or {}),
    }
    if control is not None:
        motivo, datos_control = control(Clasificador(nuevo, modelo))
        metadatos.update(datos_control)
        if motivo:
            shutil.rmtree(nuevo, ignore_errors=True)
            raise ModeloRechazado(motivo, metadatos)
    (nuevo / METADATOS).write_text(json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8")
    if destino.exists():
        destino.rename(viejo)
    nuevo.rename(destino)
    shutil.rmtree(viejo, ignore_errors=True)
    return metadatos
