"""Servidores y relevo: quién atiende el bot, quién espera y quién está apagado (latidos en _hub/).

Uso (hub.sh / hub.ps1 lo corren dentro del contenedor):
  python -m scripts.relevo            tabla de servidores            (./hub.sh servidores)
  python -m scripts.relevo esperar    tras parar este equipo, espera a que el de guardia retome el bot
                                      (lo hace ./hub.sh parar)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

from app import config as config_mod
from app.ajustes import Ajustes
from app.estado import latido
from app.estado.latido import ACTIVO, APAGADO, ESPERA
from app.estado.relevo import Observador, hace

ESPERA_MAX_S = 150


def tabla(latidos: dict[str, dict], yo: str, guardias: set[str], vigencia_s: float, ahora: float) -> str:
    if not latidos:
        return "Todavía ningún equipo escribió su latido en _hub/."
    filas = []
    for nombre in sorted(latidos):
        d = latidos[nombre]
        edad, estado = ahora - float(d.get("epoch", 0)), latido.estado_de(d)
        if estado == APAGADO:
            texto = f"apagado desde hace {hace(ahora - float(d.get('desde', d.get('epoch', 0))))}"
        elif edad >= vigencia_s:
            texto = f"sin latir desde hace {hace(edad)}"
        elif estado == ESPERA:
            texto = f"en espera (latido hace {hace(edad)})"
        else:
            texto = f"atendiendo el bot (latido hace {hace(edad)})"
        marcas = [m for m, si in (("de guardia", nombre in guardias or d.get("cede")), ("este equipo", nombre == yo))
                  if si]
        filas.append(f"  {nombre:<14} {texto}" + (f"  [{', '.join(marcas)}]" if marcas else ""))
    return "Servidores (latidos en _hub/):\n" + "\n".join(filas)


def esperar(interna: Path, yo: str, guardias: set[str], vigencia_s: float, max_s: float = ESPERA_MAX_S,
            reloj: Callable[[], float] = time.time, dormir: Callable[[float], None] = time.sleep,
            escribir: Callable[[str], None] = lambda t: print(t, flush=True)) -> int:
    """Tras parar este equipo, espera a que uno de guardia retome el bot. 0 si lo retomó (o no hay a
    quién esperar); 1 si no llegó a tiempo."""
    otros = sorted(g for g in guardias if g != yo)
    if not otros:
        escribir("Este equipo es el de guardia: nadie más retoma el bot.")
        return 0
    obs, inicio = Observador(), reloj()
    todos = latido.por_servidor(interna)
    vivos = [g for g in otros if g in todos and latido.estado_de(todos[g]) != APAGADO
             and obs.edad(todos[g], inicio) < vigencia_s]
    if not vivos:
        escribir(f"{', '.join(otros)} no está latiendo (apagado o sin Syncthing): nadie retomará el bot.")
        return 1
    if any(latido.estado_de(todos[g]) == ACTIVO for g in vivos):
        escribir(f"{vivos[0]} ya atiende el bot.")
        return 0
    escribir(f"Esperando a que {vivos[0]} retome el bot (Syncthing tarda ~10-30 s en cada sentido). "
             "No apagues este equipo todavía…")
    ultimo_aviso = inicio
    while reloj() - inicio < max_s:
        dormir(2)
        ahora = reloj()
        todos = latido.por_servidor(interna)
        for g in vivos:
            d = todos.get(g)
            # Solo cuenta un latido "activo" escrito después de parar este equipo.
            if d and latido.estado_de(d) == ACTIVO and obs.edad(d, ahora) < ahora - inicio:
                escribir(f"✓ {g} retomó el bot ({int(ahora - inicio)} s). Ya puedes apagar este equipo.")
                return 0
        if ahora - ultimo_aviso >= 15:
            ultimo_aviso = ahora
            escribir(f"  … sigo esperando ({int(ahora - inicio)} s)")
    escribir(f"{vivos[0]} aún no retoma el bot. Si apagas este equipo ahora, lo retomará solo en unos "
             f"{hace(vigencia_s)} (cuando deje de ver su latido).")
    return 1


def main(argv: list[str]) -> int:
    a = Ajustes.desde_entorno()
    cfg = config_mod.cargar(a.config_path)
    interna = a.boveda / cfg["boveda"]["interna"]
    relevo = cfg.get("relevo") or {}
    guardias = {str(n) for n in relevo.get("ceden") or []}
    vigencia = float(cfg["latido"].get("vigencia_s", 180))
    if argv[:1] == ["esperar"]:
        if not relevo.get("activo"):
            return 0
        return esperar(interna, a.servidor_nombre, guardias, vigencia)
    print(tabla(latido.por_servidor(interna), a.servidor_nombre, guardias, vigencia, time.time()))
    if not relevo.get("activo"):
        print("Relevo apagado (relevo.activo: false): el segundo equipo no arranca mientras otro atiende.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
