"""Servicio de voz sin descargar Whisper: se reemplaza el modelo por uno falso."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import servidor


class ModeloFalso:
    def __init__(self, duracion=3.0, error=None):
        self.duracion, self.error = duracion, error
        self.rutas = []

    def transcribe(self, ruta, language, vad_filter, beam_size, initial_prompt=None):
        self.rutas.append(Path(ruta))
        self.pista = initial_prompt
        assert Path(ruta).read_bytes() == b"OggS-audio" and language == "es" and vad_filter
        if self.error:
            raise self.error
        segmentos = (SimpleNamespace(text=t) for t in [" Nota idea:", " la villana usa una máscara. "])
        return segmentos, SimpleNamespace(duration=self.duracion)


@pytest.fixture
def cliente(monkeypatch):
    def usar(modelo):
        monkeypatch.setattr(servidor, "obtener_modelo", lambda: modelo)
        return TestClient(servidor.app)
    return usar


def test_transcribe_y_borra_el_audio(cliente):
    modelo = ModeloFalso()
    resp = cliente(modelo).post("/transcribir", content=b"OggS-audio")
    assert resp.status_code == 200
    assert resp.json()["texto"] == "Nota idea: la villana usa una máscara."
    assert resp.json()["duracion"] == 3.0
    assert not modelo.rutas[0].exists()  # el audio crudo no sobrevive


def test_audio_largo_se_rechaza_y_tambien_se_borra(cliente):
    modelo = ModeloFalso(duracion=500)
    resp = cliente(modelo).post("/transcribir", content=b"OggS-audio")
    assert resp.status_code == 413 and "máximo" in resp.json()["detail"]
    assert not modelo.rutas[0].exists()


def test_audio_danado_y_vacio(cliente):
    modelo = ModeloFalso(error=ValueError("formato"))
    assert cliente(modelo).post("/transcribir", content=b"OggS-audio").status_code == 422
    assert not modelo.rutas[0].exists()
    assert cliente(modelo).post("/transcribir", content=b"").status_code == 400


def test_la_pista_llega_a_whisper_recortada(cliente):
    modelo = ModeloFalso()
    c = cliente(modelo)
    c.post("/transcribir", content=b"OggS-audio")
    assert modelo.pista is None  # sin pista, Whisper no recibe texto previo
    c.post("/transcribir", params={"pista": "zorro, Zamael " + "x" * 1000}, content=b"OggS-audio")
    assert modelo.pista.startswith("zorro, Zamael") and len(modelo.pista) == servidor.MAX_PISTA


# --- respuesta hablada (paso C) -------------------------------------------------------
class KokoroFalso:
    def __init__(self, error=None):
        self.error = error
        self.llamadas = []

    def create(self, texto, voice, speed, lang):
        import numpy as np
        self.llamadas.append((texto, voice, speed, lang))
        if self.error:
            raise self.error
        return np.zeros(24000, dtype=np.float32), 24000   # 1 s de silencio


@pytest.fixture
def con_kokoro(monkeypatch):
    def usar(kokoro, opus=b"OggS-voz"):
        monkeypatch.setattr(servidor, "obtener_kokoro", lambda: kokoro)
        monkeypatch.setattr(servidor, "a_opus", lambda muestras, frecuencia: opus)
        return TestClient(servidor.app)
    return usar


def test_hablar_devuelve_ogg_con_voz_idioma_y_tono(con_kokoro):
    kokoro = KokoroFalso()
    resp = con_kokoro(kokoro).post("/hablar", json={"texto": "Listo, guardé la nota."})
    assert resp.status_code == 200 and resp.content == b"OggS-voz"
    assert resp.headers["content-type"] == "audio/ogg"
    texto, voz, velocidad, idioma = kokoro.llamadas[0]
    assert (texto, voz, idioma) == ("Listo, guardé la nota.", "jf_tebukuro", "es-419")
    assert velocidad == pytest.approx(1 / 1.15)


@pytest.mark.parametrize("cuerpo, estado", [({"texto": " "}, 400), ({"texto": "a" * 601}, 413)])
def test_hablar_rechaza_texto_vacio_o_largo(con_kokoro, cuerpo, estado):
    assert con_kokoro(KokoroFalso()).post("/hablar", json=cuerpo).status_code == estado


def test_hablar_fallo_de_kokoro_da_503(con_kokoro):
    resp = con_kokoro(KokoroFalso(error=RuntimeError("espeak"))).post("/hablar", json={"texto": "hola"})
    assert resp.status_code == 503


def test_a_opus_codifica_ogg_opus_de_verdad():
    import io

    import av
    import numpy as np
    muestras = np.sin(np.linspace(0, 440 * 2 * np.pi, 27600)).astype(np.float32) * 0.3
    datos = servidor.a_opus(muestras, 27600)   # 1 s a la frecuencia "subida" de 24 kHz × 1,15
    assert datos[:4] == b"OggS"
    with av.open(io.BytesIO(datos)) as cont:
        pista = cont.streams.audio[0]
        assert pista.codec_context.name == "opus" and pista.codec_context.sample_rate == 48000
        assert pista.codec_context.channels == 1


# --- descarga de Kokoro en un equipo nuevo (sin red: URLs file://) --------------------
def _publicacion(tmp_path, monkeypatch, modelo=b"modelo-onnx", huella_modelo=None):
    """Simula la publicación de kokoro-onnx en una carpeta local."""
    import hashlib
    import io

    import numpy as np
    origen = tmp_path / "publicacion"
    origen.mkdir()
    (origen / "kokoro-v1.0.fp16.onnx").write_bytes(modelo)
    paquete = io.BytesIO()
    np.savez(paquete, jf_tebukuro=np.ones((2, 1, 4), np.float32), af_otra=np.zeros((2, 1, 4), np.float32))
    (origen / "voices-v1.0.bin").write_bytes(paquete.getvalue())
    sha = lambda p: hashlib.sha256((origen / p).read_bytes()).hexdigest()  # noqa: E731
    destino = tmp_path / "modelos" / "kokoro"
    monkeypatch.setattr(servidor, "KOKORO_URL", origen.as_uri())
    monkeypatch.setattr(servidor, "HUELLAS", {"kokoro-v1.0.fp16.onnx": huella_modelo or sha("kokoro-v1.0.fp16.onnx"),
                                              "voices-v1.0.bin": sha("voices-v1.0.bin")})
    monkeypatch.setattr(servidor, "KOKORO_MODELO", str(destino / "kokoro-v1.0.fp16.onnx"))
    monkeypatch.setattr(servidor, "KOKORO_VOCES", str(destino / "voces_jf_tebukuro.npz"))
    return destino


def test_descarga_kokoro_y_guarda_solo_la_voz_elegida(tmp_path, monkeypatch):
    import numpy as np
    destino = _publicacion(tmp_path, monkeypatch)
    servidor.asegurar_kokoro()
    assert (destino / "kokoro-v1.0.fp16.onnx").read_bytes() == b"modelo-onnx"
    with np.load(destino / "voces_jf_tebukuro.npz") as voces:
        assert voces.files == ["jf_tebukuro"] and voces["jf_tebukuro"].shape == (2, 1, 4)
    assert sorted(p.name for p in destino.iterdir()) == ["kokoro-v1.0.fp16.onnx", "voces_jf_tebukuro.npz"]
    # Ya están: no se vuelve a descargar (la publicación podría no existir).
    monkeypatch.setattr(servidor, "KOKORO_URL", (tmp_path / "no-existe").as_uri())
    servidor.asegurar_kokoro()


def test_descarga_con_huella_distinta_se_descarta(tmp_path, monkeypatch):
    destino = _publicacion(tmp_path, monkeypatch, huella_modelo="0" * 64)
    with pytest.raises(servidor.ErrorDescarga, match="huella SHA-256"):
        servidor.asegurar_kokoro()
    assert list(destino.iterdir()) == []   # ni el archivo ni restos temporales


def test_archivo_sin_huella_conocida_no_se_descarga(tmp_path, monkeypatch):
    _publicacion(tmp_path, monkeypatch)
    monkeypatch.setattr(servidor, "KOKORO_MODELO", str(tmp_path / "otro-modelo.onnx"))
    with pytest.raises(servidor.ErrorDescarga, match="colócalo a mano"):
        servidor.asegurar_kokoro()
