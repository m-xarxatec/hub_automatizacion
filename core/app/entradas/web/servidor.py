"""App web local (FASE 2). Por ahora solo expone /salud para comprobar que core corre.

Las pantallas (captura, imagen, referencias, proyectos, tareas, estado) se
agregarán con plantillas HTMX y acceso con WEB_PIN.
"""

from __future__ import annotations

import contextlib
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def crear_app(servidor: str) -> FastAPI:
    app = FastAPI(title="Hub creativo", docs_url=None, redoc_url=None)
    inicio = time.time()

    @app.get("/salud")
    def salud() -> dict:
        return {"ok": True, "servidor": servidor, "activo_s": int(time.time() - inicio)}

    @app.get("/", response_class=HTMLResponse)
    def inicio_pagina() -> str:
        return (
            "<!doctype html><meta charset='utf-8'><title>Hub creativo</title>"
            "<body style='font-family:system-ui;max-width:40rem;margin:3rem auto;padding:0 1rem'>"
            f"<h1>Hub creativo</h1><p>Servidor activo: <b>{servidor}</b>.</p>"
            "<p>La app web local llega en la fase 2.</p></body>"
        )

    return app


class ServidorSinSenales(uvicorn.Server):
    """Uvicorn sin manejar señales: de eso se encarga el bucle principal."""

    def install_signal_handlers(self) -> None:  # uvicorn < 0.29
        pass

    @contextlib.contextmanager
    def capture_signals(self):  # uvicorn >= 0.29
        yield


def servidor(app: FastAPI, puerto: int = 8080) -> ServidorSinSenales:
    config = uvicorn.Config(app, host="0.0.0.0", port=puerto, log_level="warning", access_log=False)
    return ServidorSinSenales(config)
