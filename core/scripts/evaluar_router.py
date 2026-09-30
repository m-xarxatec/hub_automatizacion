"""Mide el router local (reglas + SetFit, sin IA) con frases que nunca vio al entrenar.

Uso en Docker:  docker compose run --rm --no-deps core python -m scripts.evaluar_router [opciones]
Uso en .venv:   cd core && HF_HOME=../modelos/hf ../.venv/bin/python -m scripts.evaluar_router \
                    --carpeta ../datos/router --config ../config.yaml [opciones]

Sin opciones evalúa el modelo que usa el bot (/datos/router/modelo). Con --entrenar NOMBRE entrena
un candidato en /datos/router-candidatos/NOMBRE (fuera de la carpeta que comparte Syncthing y sin
tocar el modelo del bot) y lo evalúa; --base, --iteraciones, --epocas y --ejemplos lo configuran.

Qué mide, además de los aciertos:
- "ejecuta mal": el router está seguro, se equivoca y actúa sin preguntar (el peor error).
- "duda": pediría confirmación, botones o la opinión de la IA (cuesta un clic o tokens, no un error).
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from unittest import mock

from app import config as config_mod
from app.router import clasificador, ejemplos
from app.router.evaluacion import leer_prueba, solapadas
from app.router.cascada import Router, contradice

PRUEBA = Path(__file__).resolve().parents[1] / "app" / "router" / "datos" / "prueba.yaml"
__all__ = ["leer_prueba", "solapadas", "evaluar"]


def liberar_gpu() -> None:
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def evaluar(router: Router, prueba: list[tuple[str, str]]) -> dict:
    modelo = router.clasificador
    filas, ms = [], []
    for texto, esperada in prueba:
        inicio = time.perf_counter()
        solo = modelo.predecir(texto) if modelo else None
        d = asyncio.run(router.decidir(texto))
        ms.append((time.perf_counter() - inicio) * 1000)
        nivel = router.nivel(d)
        if contradice(texto, d):
            nivel = "duda"   # con OpenClaw, el bot consulta a la IA en vez de ejecutar
        filas.append({"texto": texto, "esperada": esperada, "setfit": solo.accion if solo else None,
                      "setfit_conf": round(solo.confianza, 2) if solo else None, "decision": d.accion,
                      "conf": round(d.confianza, 2), "nivel": "ejecutar" if nivel == "ejecutar" else "duda"})
    total = len(filas)
    por_accion = {}
    for accion in sorted({f["esperada"] for f in filas}):
        suyas = [f for f in filas if f["esperada"] == accion]
        por_accion[accion] = {"n": len(suyas), "acierta": sum(f["decision"] == accion for f in suyas),
                              "ejecuta_mal": sum(f["nivel"] == "ejecutar" and f["decision"] != accion
                                                 for f in suyas)}
    ejecuta = [f for f in filas if f["nivel"] == "ejecutar"]
    return {
        "frases": total,
        "setfit_acierta": sum(f["setfit"] == f["esperada"] for f in filas),
        "acierta": sum(f["decision"] == f["esperada"] for f in filas),
        "ejecuta_bien": sum(f["decision"] == f["esperada"] for f in ejecuta),
        "ejecuta_mal": sum(f["decision"] != f["esperada"] for f in ejecuta),
        "duda": total - len(ejecuta),
        "duda_bien_propuesta": sum(f["decision"] == f["esperada"] for f in filas if f["nivel"] == "duda"),
        "ms_medio": round(sum(ms) / max(total, 1), 1),
        "por_accion": por_accion,
        "confusiones": dict(Counter(f"{f['esperada']}->{f['decision']}" for f in filas
                                    if f["decision"] != f["esperada"]).most_common()),
        "filas": filas,
    }


def imprimir(r: dict, meta: dict, ver_errores: bool) -> None:
    n = r["frases"]
    pct = lambda x: f"{x:3d} ({100 * x / max(n, 1):4.1f} %)"  # noqa: E731
    print(f"\nModelo: {meta.get('base', '?')} · {meta.get('ejemplos', '?')} ejemplos · "
          f"iteraciones {meta.get('iteraciones', '?')} · épocas {meta.get('epocas', '?')} · "
          f"{meta.get('dispositivo', '?')} · entrenado en {meta.get('segundos', '?')} s")
    print(f"Frases de prueba: {n}   (tiempo medio por frase: {r['ms_medio']} ms)")
    print(f"  SetFit solo acierta:         {pct(r['setfit_acierta'])}")
    print(f"  Router (reglas+SetFit):      {pct(r['acierta'])}")
    print(f"  Ejecuta sin preguntar, bien: {pct(r['ejecuta_bien'])}")
    print(f"  Ejecuta sin preguntar, MAL:  {pct(r['ejecuta_mal'])}   <- el error que más molesta")
    print(f"  Duda (botones o IA):         {pct(r['duda'])}   de ellas, propuesta correcta: "
          f"{r['duda_bien_propuesta']}")
    print("  Por acción (acierta / ejecuta mal):")
    for accion, v in r["por_accion"].items():
        print(f"    {accion:9} {v['acierta']:2d}/{v['n']:<2d}  mal sin preguntar: {v['ejecuta_mal']}")
    if r["confusiones"]:
        print("  Confusiones:", ", ".join(f"{k} ×{v}" for k, v in r["confusiones"].items()))
    if ver_errores:
        print("  Errores:")
        for f in r["filas"]:
            if f["decision"] != f["esperada"]:
                marca = "MAL" if f["nivel"] == "ejecutar" else "duda"
                print(f"    [{marca:4}] {f['esperada']:>9} -> {f['decision']:<9} {f['conf']:.2f}  {f['texto'][:90]}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--carpeta", type=Path, default=Path(os.environ.get("DATOS_DIR", "/datos")) / "router")
    p.add_argument("--config", type=Path, default=Path(os.environ.get("CONFIG_PATH", "/app/config.yaml")))
    p.add_argument("--prueba", type=Path, default=PRUEBA)
    p.add_argument("--modelo", type=Path, help="carpeta de un modelo ya entrenado (por defecto, el del bot)")
    p.add_argument("--entrenar", metavar="NOMBRE", help="entrena un candidato con ese nombre y lo evalúa")
    p.add_argument("--base", help="modelo base (por defecto, router.entrenamiento de config.yaml)")
    p.add_argument("--iteraciones", type=int)
    p.add_argument("--epocas", type=int)
    p.add_argument("--congelar", action=argparse.BooleanOptionalAction,
                   help="no ajusta la tabla de palabras (modelos grandes en 4 GB)")
    p.add_argument("--ejemplos", type=Path, default=ejemplos.EJEMPLOS_BASE)
    p.add_argument("--errores", action="store_true", help="lista cada frase mal clasificada")
    a = p.parse_args()

    cfg = config_mod.cargar(a.config)
    cfg["router"]["segunda_opinion"] = False   # se mide solo lo local: sin IA ni tokens
    ent = cfg["router"].get("entrenamiento", {})
    a.base = a.base or ent.get("base", clasificador.MODELO_BASE)
    a.iteraciones = a.iteraciones or int(ent.get("iteraciones", 20))
    a.epocas = a.epocas or int(ent.get("epocas", 1))
    a.congelar = bool(ent.get("congelar_vocabulario", False)) if a.congelar is None else a.congelar
    if a.entrenar or a.modelo:
        # No cargar el modelo del bot: no se usa y en una GPU de 4 GB le quita memoria al candidato.
        with mock.patch.object(clasificador, "cargar", return_value=None):
            router = Router(cfg, a.carpeta)
    else:
        router = Router(cfg, a.carpeta)
    prueba = leer_prueba(a.prueba)
    textos, etiquetas = ejemplos.unir(ejemplos.leer_ejemplos(a.ejemplos), ejemplos.leer_correcciones(a.carpeta),
                                      router.acciones, ejemplos.leer_aprendidos(a.carpeta))
    repetidas = solapadas(prueba, textos)
    if repetidas:
        print(f"AVISO: {len(repetidas)} frases de prueba también están en el entrenamiento (inflan el resultado):")
        for t in repetidas:
            print("   ", t)

    if a.entrenar:
        destino = a.carpeta.parent / "router-candidatos" / a.entrenar
        print(f"Entrenando '{a.entrenar}' con {len(textos)} ejemplos ({a.base}, iteraciones {a.iteraciones}, "
              f"épocas {a.epocas}{', vocabulario congelado' if a.congelar else ''})...", flush=True)
        clasificador.entrenar(textos, etiquetas, destino, base=a.base, iteraciones=a.iteraciones,
                              epocas=a.epocas, congelar_vocabulario=a.congelar,
                              extra={"ejemplos_archivo": a.ejemplos.name})
        a.modelo = destino
        liberar_gpu()   # lo que dejó el entrenamiento, antes de cargar el candidato para evaluarlo
    if a.modelo:
        router.clasificador = clasificador.cargar(a.modelo)
        if router.clasificador is None:
            print(f"No hay un modelo válido en {a.modelo}")
            return 1
    if router.clasificador is None:
        print("Sin modelo entrenado: solo se evalúan las reglas.")

    resultado = evaluar(router, prueba)
    meta = router.clasificador.metadatos if router.clasificador else {}
    imprimir(resultado, meta, a.errores)
    if a.entrenar:
        salida = a.modelo / "evaluacion.json"
        salida.write_text(json.dumps({"entrenamiento": meta, **resultado}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"\nResultado guardado en {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
