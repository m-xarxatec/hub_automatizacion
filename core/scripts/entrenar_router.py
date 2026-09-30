"""Entrena el clasificador local del router con SetFit (DÍA 3).

Uso:  docker compose run --rm --no-deps core python -m scripts.entrenar_router
Une app/router/datos/ejemplos.yaml con /datos/router/aprendidos.yaml y /datos/router/correcciones.yaml
y guarda el modelo en /datos/router/modelo/ solo si no sale peor que el actual en las
pruebas. Tarda unos 15 minutos en CPU (config.yaml, router.entrenamiento).
Desde Telegram hace lo mismo el comando /reentrenar.
"""

from __future__ import annotations

import sys

from app import config as config_mod
from app.ajustes import Ajustes
from app.router.cascada import Router
from app.router.clasificador import ModeloRechazado


def main() -> int:
    a = Ajustes.desde_entorno()
    cfg = config_mod.cargar(a.config_path)
    router = Router(cfg, a.datos / "router")
    print("Entrenando el router (unos minutos en CPU)...", flush=True)
    try:
        meta = router.reentrenar()
    except ModeloRechazado as e:
        print(f"Modelo nuevo descartado: {e.motivo}. Sigue el anterior.")
        return 1
    except ValueError as e:
        print(f"No se pudo entrenar: {e}")
        return 1
    print(f"Listo en {meta['segundos']} s con {meta['ejemplos']} ejemplos "
          f"({meta['correcciones']} correcciones, {meta.get('aprendidos', 0)} aprendidos de la IA).")
    if meta.get("evaluacion"):
        antes = meta.get("evaluacion_anterior")
        print(f"Pruebas: acierta el {meta['evaluacion']['porcentaje']:.1%}"
              + (f" (antes {antes['porcentaje']:.1%})" if antes else "") + ".")
    for accion, n in meta["por_accion"].items():
        print(f"  {accion}: {n}")
    print("Reinicia core para que lo cargue: ./hub.sh reiniciar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
