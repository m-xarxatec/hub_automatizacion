# Servicio de voz 100 % local: faster-whisper (transcripción) y Kokoro (respuesta hablada).
# Solo CPU: imagen liviana y portable. Whisper se descarga en modelos/whisper la primera vez;
# Kokoro (modelo y voz) ya está en modelos/kokoro.
FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# espeak-ng convierte el texto en fonemas para Kokoro. Los enlaces dan rutas fijas en cualquier
# arquitectura (x86 o ARM) para KOKORO_ESPEAK_LIB y KOKORO_ESPEAK_DATOS.
RUN apt-get update && apt-get install -y --no-install-recommends libespeak-ng1 espeak-ng-data \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/lib/*/libespeak-ng.so.1 /usr/local/lib/libespeak-ng.so.1 \
    && ln -s /usr/lib/*/espeak-ng-data /usr/local/share/espeak-ng-data
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY servidor.py .
COPY tests ./tests
CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8090"]
