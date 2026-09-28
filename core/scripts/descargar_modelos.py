"""Descarga los modelos locales. Se ejecuta una vez por equipo.

Uso:  docker compose run --rm core python -m scripts.descargar_modelos

- Modelo base del clasificador del router (unos 470 MB, en modelos/hf).
- qwen2.5 3B en Ollama (unos 2 GB) solo si proveedores.llm_local.activo: dormido en el MVP
  para no competir por recursos; con él, levantar antes Ollama (COMPOSE_PROFILES=llm-local).
Whisper y Kokoro los maneja el contenedor voz. Sin Stable Diffusion: las imágenes van por APIs.
Todo queda en modelos/ o datos/, fuera del repositorio y de la bóveda.
"""

from __future__ import annotations

import json
import sys

import httpx

from app import config as config_mod
from app.ajustes import Ajustes


def descargar_ollama(url: str, modelo: str) -> bool:
    print(f"Descargando {modelo} en Ollama (puede tardar varios minutos)...")
    ultimo = ""
    try:
        with httpx.stream("POST", f"{url}/api/pull", json={"model": modelo, "stream": True},
                          timeout=None) as r:
            r.raise_for_status()
            for linea in r.iter_lines():
                if not linea:
                    continue
                datos = json.loads(linea)
                if "error" in datos:
                    print(f"Error de Ollama: {datos['error']}")
                    return False
                estado = datos.get("status", "")
                total, hecho = datos.get("total"), datos.get("completed")
                if total and hecho:
                    estado = f"{estado} {hecho * 100 // total}%"
                if estado != ultimo:
                    print(f"  {estado}", flush=True)
                    ultimo = estado
    except httpx.HTTPError as e:
        print(f"No se pudo hablar con Ollama en {url}: {e}")
        print("Levántalo primero: docker compose up -d ollama")
        return False
    print(f"{modelo} listo.")
    return True


def descargar_base_router() -> bool:
    from huggingface_hub import snapshot_download

    from app.router.clasificador import MODELO_BASE

    print(f"Descargando {MODELO_BASE} (modelo base del router)...", flush=True)
    try:
        snapshot_download(MODELO_BASE)
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo descargar el modelo base del router: {e}")
        return False
    print("Modelo base del router listo. Entrénalo con: python -m scripts.entrenar_router")
    return True


def main() -> int:
    a = Ajustes.desde_entorno()
    cfg = config_mod.cargar(a.config_path)
    cfg_llm = cfg["proveedores"]["llm_local"]
    ok = True
    if cfg_llm.get("activo", False):
        ok = descargar_ollama(a.ollama_url, cfg_llm["modelo"])
    else:
        print("qwen no se descarga: llm_local.activo es false (dormido en el MVP).")
    ok = descargar_base_router() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
