"""Verifica que el equipo esté listo para ser servidor.

Uso:  docker compose run --rm core python -m scripts.chequeo
Sale con código 1 si falla algo imprescindible.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

from app import config as config_mod
from app.ajustes import Ajustes
from app.estado import latido

OK, AVISO, FALLO = "[ OK ]", "[AVISO]", "[FALLO]"


def main() -> int:
    a = Ajustes.desde_entorno()
    fallos = 0

    def linea(estado: str, texto: str) -> None:
        nonlocal fallos
        fallos += estado == FALLO
        print(f"{estado} {texto}")

    print(f"Chequeo del equipo '{a.servidor_nombre}'\n")

    # --- configuración ---------------------------------------------------------
    try:
        cfg = config_mod.cargar(a.config_path)
        linea(OK, f"config.yaml válido ({a.config_path})")
    except Exception as e:  # noqa: BLE001
        linea(FALLO, f"config.yaml no se puede leer: {e}")
        cfg = config_mod.POR_DEFECTO
    if a.servidor_nombre == "sin-nombre":
        linea(AVISO, "SERVIDOR_NOMBRE vacío: ponle un nombre distinto a cada equipo")

    # --- Telegram ----------------------------------------------------------------
    if not a.telegram_token:
        linea(FALLO, "Falta TELEGRAM_TOKEN")
    else:
        try:
            r = httpx.get(f"https://api.telegram.org/bot{a.telegram_token}/getMe", timeout=10)
            datos = r.json()
            if datos.get("ok"):
                linea(OK, f"Token de Telegram válido: @{datos['result']['username']}")
            else:
                linea(FALLO, f"Telegram rechazó el token: {datos.get('description')}")
        except httpx.HTTPError as e:
            linea(FALLO, f"Sin conexión con Telegram: {e}")
    if a.usuarios:
        linea(OK, f"Usuarios autorizados: {len(a.usuarios)}")
    else:
        linea(AVISO, "TELEGRAM_USUARIOS vacío: arranca el bot, envía /start y copia tu ID")

    # --- bóveda ------------------------------------------------------------------
    b = a.boveda
    if not b.exists():
        linea(FALLO, f"La bóveda no está montada en {b}: revisa VAULT_PATH")
    else:
        prueba = b / ".chequeo.tmp"
        try:
            prueba.write_text("ok")
            prueba.unlink()
            linea(OK, f"Bóveda montada y con permiso de escritura ({b})")
        except OSError as e:
            linea(FALLO, f"No se puede escribir en la bóveda: {e}")
        if (b / ".stfolder").exists():
            linea(OK, "La bóveda es una carpeta compartida de Syncthing (.stfolder presente)")
        else:
            linea(AVISO, "No se ve .stfolder: ¿la carpeta está compartida en Syncthing?")
        if (b / ".obsidian").exists():
            linea(OK, "Obsidian ya abrió esta bóveda (.obsidian presente)")
        else:
            linea(AVISO, "No hay .obsidian: abre la carpeta como bóveda en Obsidian al menos una vez")
        vivo = latido.leer(b / cfg["boveda"]["interna"])
        if vivo:
            edad = int(time.time() - float(vivo.get("epoch", 0)))
            estado = OK if vivo.get("servidor") == a.servidor_nombre or edad > 180 else AVISO
            linea(estado, f"Último latido: '{vivo.get('servidor')}' hace {edad} s")

    # --- Ollama ------------------------------------------------------------------
    cfg_llm = cfg.get("proveedores", {}).get("llm_local", {})
    modelo = cfg_llm.get("modelo", "")
    if not cfg_llm.get("activo", False):
        linea(OK, "Ollama apagado a propósito (llm_local.activo: false)")
    else:
        try:
            r = httpx.get(f"{a.ollama_url}/api/tags", timeout=5)
            nombres = [m["name"] for m in r.json().get("models", [])]
            if any(n == modelo or n.startswith(modelo + ":") for n in nombres):
                linea(OK, f"Ollama responde y tiene {modelo}")
            else:
                linea(AVISO, f"Ollama responde pero falta {modelo}: python -m scripts.descargar_modelos")
        except (httpx.HTTPError, ValueError):
            linea(AVISO, "Ollama no responde (¿COMPOSE_PROFILES incluye llm-local?)")

    # --- OpenClaw (día 5) --------------------------------------------------------
    if "consulta" in os.environ.get("COMPOSE_PROFILES", "") or a.openclaw_token:
        # Petición vacía al plugin hub-puente: no llega al modelo (no gasta tokens).
        # 400 = token válido y plugin cargado; 401 = token distinto; 404 = plugin sin cargar.
        motivos = {400: "OpenClaw y el plugin hub-puente responden",
                   401: "OpenClaw rechaza el token (OPENCLAW_GATEWAY_TOKEN no coincide)",
                   404: "OpenClaw responde pero falta el plugin hub-puente (ver openclaw/README.md)"}
        try:
            r = httpx.post(f"{a.openclaw_url}/hub/completar", json={}, timeout=5,
                           headers={"Authorization": f"Bearer {a.openclaw_token}"})
            linea(OK if r.status_code == 400 else AVISO,
                  motivos.get(r.status_code, f"OpenClaw responde con HTTP {r.status_code}"))
        except httpx.HTTPError:
            linea(AVISO, "OpenClaw no responde (ver openclaw/README.md)")
    else:
        print("[ -- ] OpenClaw sin activar (día 5)")

    print("\nResultado:", "listo" if fallos == 0 else f"{fallos} problema(s) por resolver")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
