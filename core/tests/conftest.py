import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config as config_mod  # noqa: E402
from app.boveda.proyectos import Boveda  # noqa: E402


@pytest.fixture
def cfg():
    # En el contenedor config.yaml está en /app; en el repo, dos carpetas arriba.
    ruta = os.environ.get("CONFIG_PATH") or Path(__file__).resolve().parents[2] / "config.yaml"
    return config_mod.cargar(Path(ruta))


@pytest.fixture
def boveda(tmp_path, cfg):
    b = Boveda(tmp_path / "Boveda", cfg, "Europe/Madrid")
    b.raiz.mkdir()
    b.asegurar_base()
    return b


def pytest_configure(config):
    config.addinivalue_line("markers", "lenta: entrena modelos reales; se activa con HUB_PRUEBAS_LENTAS=1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("HUB_PRUEBAS_LENTAS") == "1":
        return
    saltar = pytest.mark.skip(reason="prueba lenta: define HUB_PRUEBAS_LENTAS=1 para ejecutarla")
    for item in items:
        if "lenta" in item.keywords:
            item.add_marker(saltar)
