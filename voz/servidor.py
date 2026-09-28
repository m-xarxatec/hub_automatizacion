"""Servicio de voz 100 % local (sin APIs externas).

POST /transcribir   cuerpo = audio (OGG/Opus de Telegram u otro formato) -> {"texto", "duracion", "segundos"}
POST /hablar        {"texto"} -> audio OGG/Opus 48 kHz mono, listo para sendVoice de Telegram
GET  /salud         estado de los modelos

Respuesta hablada (paso C, decisión 9): Kokoro con la voz japonesa jf_tebukuro hablando
español latinoamericano (espeak "es-419") y el tono subido ×1,15. El truco del tono: se genera
más lento (speed = 1/1,15) y se declara una frecuencia de muestreo 1,15 veces mayor; al
reproducirlo, suena más agudo y a velocidad normal.
Modelo fp16: en esta CPU es 6 veces más rápido que el int8 (2,9 s contra 17,5 s para 14 s de audio).

El audio se escribe en un temporal y se borra siempre al terminar, aunque haya error:
solo sobrevive el texto. El modelo se carga en segundo plano al arrancar para que la
primera nota no espere la descarga ni la carga.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response

# Se usa el logger de uvicorn para que los mensajes salgan en `docker compose logs voz`.
log = logging.getLogger("uvicorn.error")

MODELO = os.environ.get("WHISPER_MODELO", "small")
DISPOSITIVO = os.environ.get("WHISPER_DEVICE", "cpu")
PRECISION = os.environ.get("WHISPER_COMPUTE", "int8" if DISPOSITIVO == "cpu" else "float16")
CARPETA_MODELOS = os.environ.get("WHISPER_DIR", "/modelos/whisper")
MAX_SEGUNDOS = float(os.environ.get("VOZ_MAX_SEGUNDOS", "120"))

KOKORO_MODELO = os.environ.get("KOKORO_MODELO", "/modelos/kokoro/kokoro-v1.0.fp16.onnx")
KOKORO_VOCES = os.environ.get("KOKORO_VOCES", "/modelos/kokoro/voces_jf_tebukuro.npz")
KOKORO_VOZ = os.environ.get("KOKORO_VOZ", "jf_tebukuro")
KOKORO_IDIOMA = os.environ.get("KOKORO_IDIOMA", "es-419")
KOKORO_TONO = float(os.environ.get("KOKORO_TONO", "1.15"))
MAX_CARACTERES_HABLA = int(os.environ.get("VOZ_MAX_CARACTERES", "600"))
ESPEAK_LIB = os.environ.get("KOKORO_ESPEAK_LIB", "/usr/local/lib/libespeak-ng.so.1")
ESPEAK_DATOS = os.environ.get("KOKORO_ESPEAK_DATOS", "/usr/local/share/espeak-ng-data")

_modelo = None
_candado = threading.Lock()
_kokoro = None
_candado_kokoro = threading.Lock()


def obtener_modelo():
    """Carga Whisper una sola vez (las pruebas reemplazan esta función)."""
    global _modelo
    with _candado:
        if _modelo is None:
            from faster_whisper import WhisperModel

            inicio = time.time()
            _modelo = WhisperModel(MODELO, device=DISPOSITIVO, compute_type=PRECISION,
                                   download_root=CARPETA_MODELOS)
            log.info("Whisper %s cargado en %s (%s) en %.1f s", MODELO, DISPOSITIVO, PRECISION,
                        time.time() - inicio)
    return _modelo


def obtener_kokoro():
    """Carga Kokoro una sola vez (las pruebas reemplazan esta función)."""
    global _kokoro
    with _candado_kokoro:
        if _kokoro is None:
            from kokoro_onnx import EspeakConfig, Kokoro

            inicio = time.time()
            _kokoro = Kokoro(KOKORO_MODELO, KOKORO_VOCES,
                             espeak_config=EspeakConfig(lib_path=ESPEAK_LIB, data_path=ESPEAK_DATOS))
            log.info("Kokoro cargado (%s) en %.1f s", Path(KOKORO_MODELO).name, time.time() - inicio)
    return _kokoro


def _cargar_todo() -> None:
    obtener_modelo()
    try:
        obtener_kokoro()
    except Exception:  # noqa: BLE001 - sin Kokoro la transcripción sigue funcionando
        log.exception("No se pudo cargar Kokoro: el bot responderá con texto")


@asynccontextmanager
async def ciclo(app: FastAPI):
    tarea = asyncio.create_task(asyncio.to_thread(_cargar_todo))
    yield
    tarea.cancel()


app = FastAPI(title="voz", lifespan=ciclo)


@app.get("/salud")
def salud() -> dict:
    return {"ok": True, "modelo": MODELO, "dispositivo": DISPOSITIVO, "cargado": _modelo is not None,
            "voz": KOKORO_VOZ, "voz_cargada": _kokoro is not None}


class AudioDemasiadoLargo(Exception):
    pass


MAX_PISTA = 400  # Whisper solo usa ~224 tokens de contexto previo


def transcribir_archivo(ruta: Path, idioma: str, pista: str = "") -> tuple[str, float]:
    modelo = obtener_modelo()
    # initial_prompt: texto "previo" que orienta la ortografía (nombres propios, z/s con seseo).
    segmentos, info = modelo.transcribe(str(ruta), language=idioma, vad_filter=True, beam_size=5,
                                        initial_prompt=pista.strip()[:MAX_PISTA] or None)
    if info.duration > MAX_SEGUNDOS:  # se revisa antes de recorrer los segmentos (lo caro)
        raise AudioDemasiadoLargo(info.duration)
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    return texto, float(info.duration)


def _transcribir(datos: bytes, idioma: str, pista: str) -> tuple[str, float]:
    fd, nombre = tempfile.mkstemp(suffix=".audio")
    ruta = Path(nombre)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        return transcribir_archivo(ruta, idioma, pista)
    finally:
        ruta.unlink(missing_ok=True)


@app.post("/transcribir")
async def transcribir(request: Request, idioma: str = "es", pista: str = "") -> dict:
    datos = await request.body()
    if not datos:
        raise HTTPException(status_code=400, detail="No llegó audio")
    inicio = time.time()
    try:
        texto, duracion = await asyncio.to_thread(_transcribir, datos, idioma, pista)
    except AudioDemasiadoLargo as e:
        raise HTTPException(status_code=413,
                            detail=f"El audio dura {e.args[0]:.0f} s; el máximo es {MAX_SEGUNDOS:.0f} s") from e
    except Exception as e:  # noqa: BLE001 - audio dañado o formato no soportado
        log.exception("Error al transcribir")
        raise HTTPException(status_code=422, detail=f"No se pudo leer el audio: {type(e).__name__}") from e
    segundos = time.time() - inicio
    log.info("Transcritos %.1f s de audio en %.2f s (%s, %s)", duracion, segundos, MODELO, DISPOSITIVO)
    return {"texto": texto, "duracion": round(duracion, 1), "segundos": round(segundos, 2)}


# --- respuesta hablada ------------------------------------------------------------------
def a_opus(muestras, frecuencia: int) -> bytes:
    """Audio float32 mono -> OGG/Opus 48 kHz mono (lo que Telegram muestra como nota de voz)."""
    import io

    import av
    import numpy as np

    salida = io.BytesIO()
    with av.open(salida, "w", format="ogg") as contenedor:
        pista = contenedor.add_stream("libopus", rate=48000, layout="mono")
        # Opus trabaja con bloques fijos de 20 ms (960 muestras a 48 kHz).
        remuestreo = av.AudioResampler(format="s16", layout="mono", rate=48000, frame_size=960)
        cuadro = av.AudioFrame.from_ndarray(np.asarray(muestras, dtype=np.float32).reshape(1, -1),
                                            format="flt", layout="mono")
        cuadro.sample_rate = frecuencia
        for bloque in [*remuestreo.resample(cuadro), *remuestreo.resample(None)]:
            for paquete in pista.encode(bloque):
                contenedor.mux(paquete)
        for paquete in pista.encode(None):
            contenedor.mux(paquete)
    return salida.getvalue()


def sintetizar(texto: str) -> tuple[bytes, float]:
    """Texto -> (OGG/Opus, segundos de audio)."""
    muestras, frecuencia = obtener_kokoro().create(texto, voice=KOKORO_VOZ, speed=1 / KOKORO_TONO,
                                                   lang=KOKORO_IDIOMA)
    frecuencia_final = int(frecuencia * KOKORO_TONO)
    return a_opus(muestras, frecuencia_final), len(muestras) / frecuencia_final


@app.post("/hablar")
async def hablar(cuerpo: dict) -> Response:
    texto = str(cuerpo.get("texto") or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="Falta el texto")
    if len(texto) > MAX_CARACTERES_HABLA:
        raise HTTPException(status_code=413, detail=f"Texto de más de {MAX_CARACTERES_HABLA} caracteres")
    inicio = time.time()
    try:
        audio, duracion = await asyncio.to_thread(sintetizar, texto)
    except Exception as e:  # noqa: BLE001 - modelo ausente, espeak, codificación…
        log.exception("Error al sintetizar la voz")
        raise HTTPException(status_code=503, detail=f"No se pudo generar la voz: {type(e).__name__}") from e
    log.info("Hablados %.1f s de audio en %.2f s (%d caracteres)", duracion, time.time() - inicio, len(texto))
    return Response(content=audio, media_type="audio/ogg")
