"""Carga de config.yaml con valores por defecto."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

POR_DEFECTO: dict[str, Any] = {
    "boveda": {
        "bandeja": "00-Bandeja",
        "diario": "Diario",
        "proyectos": "Proyectos",
        "interna": "_hub",
        # Carpeta de las fichas nuevas; si el proyecto ya tiene Historia/Personajes, se usa esa.
        "personajes": "Personajes",
        "revisar_conflictos_s": 60,
        "destino_por_tipo": {
            "idea": "Ideas", "general": "Ideas", "historia": "Historia",
            "dialogo": "Historia", "produccion": "Produccion", "analisis": "Analisis",
        },
    },
    "router": {
        "motor": "local", "umbral_ejecutar": 0.80, "umbral_confirmar": 0.50,
        "acciones": ["nota", "tarea", "imagen", "referencia", "referencia_personaje",
                     "consulta", "analisis", "busqueda"],
        "segunda_opinion": True, "llm_timeout_s": 15,
        "interprete": {"activo": True, "modelo": "openai/gpt-6-luna", "razonamiento": "low",
                       "timeout_s": 20, "max_tokens": 400},
        "entrenamiento": {"base": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                          "iteraciones": 10, "epocas": 1, "congelar_vocabulario": True},
    },
    "proveedores": {
        "llm_local": {"activo": False, "modelo": "qwen2.5:3b-instruct-q4_K_M"},
        "consulta": [
            {"modelo": "openai/gpt-6-luna", "razonamiento": "low"},
            {"modelo": "claude-cli/claude-haiku-4-5", "razonamiento": "off", "aislado": True},
        ],
        # Redactor: decide qué escribir y dónde (acciones/redactor.py).
        "redactor": {"activo": True, "modelo": "openai/gpt-6-sol", "razonamiento": "low",
                     "timeout_s": 90, "max_tokens": 3000, "tope_contexto_tokens": 12000},
        "consulta_notas_tokens": 6000,
        "analisis": {
            "recomendado": "claude-cli/claude-opus-5-5",
            "opciones": [{"modelo": "claude-cli/claude-opus-5-5", "nombre": "Opus 5.5", "aislado": True,
                          "extra_tokens": 3700, "esfuerzos": ["low", "medium", "high", "xhigh", "max"]}],
            "tope_tokens_entrada": 20000, "max_tokens_salida": 2500, "tiempo_max_s": 300,
            "espera_confirmacion_min": 10,
        },
    },
    "limpieza": {
        "hora": "04:00",
        "temp_dir_horas": 24,
        "logs_dias": 14,
        "imagenes_descartadas_dias": 7,
        "temporales_boveda_horas": 1,
    },
    "latido": {"intervalo_s": 60, "vigencia_s": 180},
    "voz": {"vocabulario": ""},
}


def _fusionar(base: dict, extra: dict) -> dict:
    resultado = copy.deepcopy(base)
    for clave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = _fusionar(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


def cargar(ruta: Path | None) -> dict[str, Any]:
    if ruta is None or not Path(ruta).exists():
        return copy.deepcopy(POR_DEFECTO)
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta} debe contener un mapa YAML")
    return _fusionar(POR_DEFECTO, datos)
