"""Variables de entorno de cada equipo (vienen de .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _ids(valor: str) -> frozenset[int]:
    ids = set()
    for parte in valor.replace(";", ",").split(","):
        parte = parte.strip()
        if parte.lstrip("-").isdigit():
            ids.add(int(parte))
    return frozenset(ids)


def _bool(valor: str | None) -> bool:
    return (valor or "").strip().lower() in {"1", "true", "si", "sí", "yes"}


@dataclass(frozen=True)
class Ajustes:
    telegram_token: str
    usuarios: frozenset[int]
    boveda: Path
    datos: Path
    config_path: Path
    servidor_nombre: str
    zona: str
    ollama_url: str
    openclaw_url: str
    openclaw_token: str
    lan_ip: str
    web_port: int
    forzar_arranque: bool
    voz_url: str = "http://voz:8090"

    @classmethod
    def desde_entorno(cls) -> "Ajustes":
        e = os.environ
        return cls(
            telegram_token=e.get("TELEGRAM_TOKEN", "").strip(),
            usuarios=_ids(e.get("TELEGRAM_USUARIOS", "")),
            boveda=Path(e.get("BOVEDA_DIR", "/boveda")),
            datos=Path(e.get("DATOS_DIR", "/datos")),
            config_path=Path(e.get("CONFIG_PATH", "/app/config.yaml")),
            servidor_nombre=e.get("SERVIDOR_NOMBRE", "sin-nombre").strip() or "sin-nombre",
            zona=e.get("TZ", "Europe/Madrid"),
            ollama_url=e.get("OLLAMA_URL", "http://ollama:11434"),
            openclaw_url=e.get("OPENCLAW_URL", "http://openclaw:18789"),
            openclaw_token=e.get("OPENCLAW_GATEWAY_TOKEN", "").strip(),
            lan_ip=e.get("LAN_IP", "127.0.0.1"),
            web_port=int(e.get("WEB_PORT", "8080") or 8080),
            forzar_arranque=_bool(e.get("FORZAR_ARRANQUE")),
            voz_url=e.get("VOZ_URL", "http://voz:8090"),
        )
