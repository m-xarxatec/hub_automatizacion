"""Router local del día 3: ejemplos, cascada con LLM, cliente de Ollama y reentrenamiento.

Todo corre sin modelos ni internet: el clasificador y el LLM se sustituyen por
dobles de prueba y Ollama por httpx.MockTransport. La única prueba que entrena
SetFit de verdad está marcada como lenta.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.config import cargar
from app.proveedores.ollama import Ollama
from app.router import clasificador, ejemplos
from app.router.cascada import Router
from app.router.llm_local import LLMLocal
from app.router.reglas import Decision


class ClasificadorFalso:
    def __init__(self, accion, confianza):
        self.decision = Decision(accion, confianza, motor="clasificador")
        self.metadatos = {"ejemplos": 10, "correcciones": 0}

    def predecir(self, texto):
        return self.decision


class LLMFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = 0

    async def opinar(self, texto):
        self.llamadas += 1
        return self.respuesta


def _router(cfg, tmp_path, clf=None, llm=None):
    r = Router(cfg, tmp_path / "router", llm=llm)
    r.clasificador = clf
    return r


def _decidir(router, texto):
    return asyncio.run(router.decidir(texto))


# --- ejemplos y correcciones -------------------------------------------------------
def test_ejemplos_base_cubren_las_acciones_de_texto(cfg):
    base = ejemplos.leer_ejemplos()
    for accion in ejemplos.acciones_de_texto(cfg["router"]["acciones"]):
        assert len(base.get(accion, [])) >= 20, accion
    assert "referencia" not in base


def test_correcciones_se_agregan_y_ganan_al_unir(tmp_path, cfg):
    carpeta = tmp_path / "router"
    ejemplos.guardar_correccion(carpeta, "Hay que: colorear la portada", "tarea")
    ejemplos.guardar_correccion(carpeta, "el templo es una nave", "nota")
    assert [c["accion"] for c in ejemplos.leer_correcciones(carpeta)] == ["tarea", "nota"]

    base = {"consulta": ["El templo es una nave"], "referencia": ["guarda esto"], "inventada": ["x"]}
    textos, etiquetas = ejemplos.unir(base, ejemplos.leer_correcciones(carpeta), cfg["router"]["acciones"])
    pares = dict(zip(textos, etiquetas))
    assert pares["el templo es una nave"] == "nota"  # la corrección pisa al ejemplo
    assert "guarda esto" not in pares and "x" not in pares
    assert len(textos) == 2


def test_registrar_ignora_acciones_de_imagen(cfg, tmp_path):
    r = _router(cfg, tmp_path)
    assert r.registrar("una frase", "tarea")
    assert not r.registrar("una frase", "referencia")
    assert not r.registrar("   ", "nota")
    assert len(ejemplos.leer_correcciones(tmp_path / "router")) == 1


# --- cascada -----------------------------------------------------------------------
def test_sin_modelo_ni_llm_usa_reglas(cfg, tmp_path):
    r = _router(cfg, tmp_path)
    assert r.clasificador is None
    assert _decidir(r, "tengo que entintar").accion == "tarea"
    assert "reglas" in r.motor


def test_clasificador_seguro_no_consulta_al_llm(cfg, tmp_path):
    llm = LLMFalso(Decision("nota", 0.9, motor="llm local"))
    r = _router(cfg, tmp_path, ClasificadorFalso("imagen", 0.92), llm)
    d = _decidir(r, "dibuja a Kira")
    assert (d.accion, d.motor, llm.llamadas) == ("imagen", "clasificador", 0)


def test_llm_de_acuerdo_sube_la_confianza(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("tarea", 0.6), LLMFalso(Decision("tarea", 0.7, motor="llm local")))
    d = _decidir(r, "falta el layout")
    assert d.accion == "tarea" and d.confianza == pytest.approx(0.8)
    assert r.nivel(d) == "ejecutar" and "llm" in d.motor


def test_llm_en_desacuerdo_con_base_media_pregunta(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("tarea", 0.6), LLMFalso(Decision("nota", 0.9)))
    d = _decidir(r, "el mentor tiene una cicatriz")
    assert d.accion == "tarea" and r.nivel(d) == "preguntar"
    assert d.extra["alternativa"] == "nota"


def test_llm_con_base_debil_propone_pero_nunca_ejecuta(cfg, tmp_path):
    # Las reglas no reconocen nada (nota 0.45); el LLM dice consulta muy seguro.
    r = _router(cfg, tmp_path, llm=LLMFalso(Decision("consulta", 0.99)))
    d = _decidir(r, "la regla de los tercios en viñetas")
    assert d.accion == "consulta" and r.nivel(d) == "confirmar"


def test_llm_caido_devuelve_la_base(cfg, tmp_path):
    r = _router(cfg, tmp_path, llm=LLMFalso(None))
    d = _decidir(r, "la villana usa una máscara de zorro")
    assert d.accion == "nota" and d.confianza == 0.45


def test_clasificador_ignorado_si_duda_mucho(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("imagen", 0.3))
    assert _decidir(r, "tengo que entintar").accion == "tarea"


def test_segunda_opinion_desactivable(cfg, tmp_path):
    cfg["router"]["segunda_opinion"] = False
    r = Router(cfg, tmp_path / "router", llm=LLMFalso(Decision("consulta", 0.9)))
    assert r.llm is None and "LLM" not in r.motor


# --- LLM local por Ollama --------------------------------------------------------
def _ollama(respuesta=None, error=None, capturas=None):
    def manejar(request):
        if capturas is not None:
            capturas.append(json.loads(request.content))
        if error:
            raise httpx.ConnectError(error)
        return httpx.Response(200, json={"message": {"content": respuesta}})
    return Ollama("http://ollama:11434", "qwen", transport=httpx.MockTransport(manejar))


def test_llm_local_pide_json_restringido(cfg):
    capturas = []
    llm = LLMLocal(_ollama('{"accion": "tarea", "confianza": 0.7}', capturas=capturas),
                   cfg["router"]["acciones"])
    d = asyncio.run(llm.opinar("me falta colorear la portada"))
    assert (d.accion, d.confianza, d.motor) == ("tarea", 0.7, "llm local")
    cuerpo = capturas[0]
    enum = cuerpo["format"]["properties"]["accion"]["enum"]
    assert "referencia" not in enum and "tarea" in enum
    assert cuerpo["options"]["temperature"] == 0 and cuerpo["stream"] is False


@pytest.mark.parametrize("respuesta", [
    '{"accion": "borrar_todo", "confianza": 0.9}',   # acción fuera de la lista
    '{"accion": "nota", "confianza": "mucha"}',      # confianza no numérica
    "esto no es json",
    "[1, 2]",
])
def test_llm_local_descarta_respuestas_invalidas(cfg, respuesta):
    llm = LLMLocal(_ollama(respuesta), cfg["router"]["acciones"])
    assert asyncio.run(llm.opinar("hola")) is None


def test_llm_local_acota_confianza_y_tolera_ollama_caido(cfg):
    llm = LLMLocal(_ollama('{"accion": "nota", "confianza": 7}'), cfg["router"]["acciones"])
    assert asyncio.run(llm.opinar("hola")).confianza == 1.0
    caido = LLMLocal(_ollama(error="sin conexión"), cfg["router"]["acciones"])
    assert asyncio.run(caido.opinar("hola")) is None


# --- reentrenamiento -----------------------------------------------------------------
def test_reentrenar_une_fuentes_y_recarga(cfg, tmp_path, monkeypatch):
    llamadas = {}

    def entrenar_falso(textos, etiquetas, destino, extra=None, control=None, liberar=None, **opciones):
        llamadas.update(textos=textos, etiquetas=etiquetas, destino=destino, opciones=opciones,
                        liberar=liberar)
        return {"ejemplos": len(textos), **(extra or {})}

    monkeypatch.setattr(clasificador, "entrenar", entrenar_falso)
    monkeypatch.setattr(clasificador, "cargar", lambda carpeta: ClasificadorFalso("nota", 0.9))
    r = _router(cfg, tmp_path)
    r.registrar("pintar fondos el domingo", "tarea")
    ejemplos.guardar_aprendido(tmp_path / "router", "falta el layout", "tarea")
    meta = r.reentrenar()
    assert meta["correcciones"] == 1 and meta["aprendidos"] == 1
    assert "pintar fondos el domingo" in llamadas["textos"] and "falta el layout" in llamadas["textos"]
    assert llamadas["destino"] == tmp_path / "router" / "modelo"
    assert llamadas["opciones"] == cfg["router"]["entrenamiento"]   # base, iteraciones… de config.yaml
    assert r.clasificador is not None
    assert llamadas["liberar"] is not None


# --- reemplazo del modelo (servidor en Windows) -----------------------------------------
def _modelos(tmp_path):
    destino, nuevo = tmp_path / "modelo", tmp_path / ".modelo.nuevo"
    for carpeta, texto in ((destino, "viejo"), (nuevo, "nuevo")):
        carpeta.mkdir()
        (carpeta / "cual.txt").write_text(texto, encoding="utf-8")
    return destino, nuevo


def _bloquear_mientras(monkeypatch, destino, en_uso):
    """Como Windows: la carpeta del modelo no se puede renombrar mientras en_uso[0] sea True."""
    original = Path.rename

    def rename(self, objetivo):
        if self == destino and en_uso[0]:
            raise PermissionError(13, "Permission denied")
        return original(self, objetivo)
    monkeypatch.setattr(Path, "rename", rename)


def test_instalar_en_linux_no_suelta_el_modelo(tmp_path):
    destino, nuevo = _modelos(tmp_path)
    soltado = []
    clasificador.instalar(nuevo, destino, liberar=lambda: soltado.append(1))
    assert (destino / "cual.txt").read_text(encoding="utf-8") == "nuevo"
    assert soltado == [] and not nuevo.exists() and not (tmp_path / ".modelo.viejo").exists()


def test_instalar_en_windows_suelta_el_modelo_y_reintenta(tmp_path, monkeypatch):
    destino, nuevo = _modelos(tmp_path)
    en_uso = [True]
    _bloquear_mientras(monkeypatch, destino, en_uso)
    clasificador.instalar(nuevo, destino, liberar=lambda: en_uso.__setitem__(0, False), espera_s=0)
    assert (destino / "cual.txt").read_text(encoding="utf-8") == "nuevo"
    assert not (tmp_path / ".modelo.viejo").exists()


def test_instalar_bloqueado_sin_remedio_conserva_el_modelo_viejo(tmp_path, monkeypatch):
    destino, nuevo = _modelos(tmp_path)
    _bloquear_mientras(monkeypatch, destino, [True])
    with pytest.raises(PermissionError):
        clasificador.instalar(nuevo, destino, liberar=lambda: None, intentos=2, espera_s=0)
    assert (destino / "cual.txt").read_text(encoding="utf-8") == "viejo"


def test_reentrenar_fallido_tras_soltar_recarga_el_modelo_viejo(cfg, tmp_path, monkeypatch):
    def entrenar_falso(textos, etiquetas, destino, extra=None, control=None, liberar=None, **opciones):
        liberar()
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(clasificador, "cargar", lambda carpeta: ClasificadorFalso("nota", 0.9))
    r = _router(cfg, tmp_path, clf=ClasificadorFalso("tarea", 0.9))
    monkeypatch.setattr(clasificador, "entrenar", entrenar_falso)
    with pytest.raises(PermissionError):
        r.reentrenar()
    assert r.clasificador is not None


def test_entrenar_exige_dos_acciones(tmp_path):
    with pytest.raises(ValueError):
        clasificador.entrenar(["a", "b"], ["nota", "nota"], tmp_path / "modelo")


def test_cargar_modelo_danado_devuelve_none(tmp_path):
    carpeta = tmp_path / "modelo"
    carpeta.mkdir()
    (carpeta / clasificador.MARCA_MODELO).write_bytes(b"basura")
    assert clasificador.cargar(carpeta) is None


@pytest.mark.lenta
def test_setfit_real_entrena_y_predice(cfg, tmp_path):
    """Descarga MiniLM la primera vez (unos 470 MB). HUB_PRUEBAS_LENTAS=1 para ejecutarla."""
    r = _router(cfg, tmp_path)
    meta = r.reentrenar()
    assert meta["ejemplos"] >= 100 and r.clasificador is not None
    assert r.clasificador.predecir("me falta entintar la página 20").accion == "tarea"
    assert r.clasificador.predecir("genera una ilustración de Leo en la playa").accion == "imagen"


def test_precargar_ollama():
    pedidos = []

    def manejar(request):
        pedidos.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"done": True})
    ok = Ollama("http://ollama:11434", "qwen", transport=httpx.MockTransport(manejar))
    assert asyncio.run(ok.precargar()) is True
    ruta, cuerpo = pedidos[0]
    assert ruta == "/api/chat" and cuerpo["model"] == "qwen" and "format" in cuerpo
    caido = Ollama("http://ollama:11434", "qwen",
                   transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert asyncio.run(caido.precargar()) is False


# --- lo que la IA le enseña al clasificador -----------------------------------------------
def test_aprendidos_sin_duplicados_y_la_correccion_del_usuario_gana(tmp_path, cfg):
    carpeta = tmp_path / "router"
    assert ejemplos.guardar_aprendido(carpeta, "falta el layout", "tarea")
    assert not ejemplos.guardar_aprendido(carpeta, "Falta el layout.", "tarea")   # misma frase
    ejemplos.guardar_correccion(carpeta, "el templo es una nave", "nota")
    assert not ejemplos.guardar_aprendido(carpeta, "el templo es una nave", "consulta")  # ya corregida
    ejemplos.guardar_correccion(carpeta, "falta el layout", "nota")    # el usuario contradice a la IA
    textos, etiquetas = ejemplos.unir({}, ejemplos.leer_correcciones(carpeta), cfg["router"]["acciones"],
                                      ejemplos.leer_aprendidos(carpeta))
    assert dict(zip(textos, etiquetas))["falta el layout"] == "nota"


def test_aprende_solo_cuando_la_ia_resuelve_la_duda_y_se_ejecuta(cfg, tmp_path):
    carpeta = tmp_path / "router"
    ayudado = _router(cfg, tmp_path, ClasificadorFalso("tarea", 0.6), LLMFalso(Decision("tarea", 0.7, motor="llm local")))
    d = _decidir(ayudado, "falta el layout")
    assert ayudado.aprender("falta el layout", d)
    assert ejemplos.leer_aprendidos(carpeta) == [{"texto": "falta el layout", "accion": "tarea"}]
    assert "1 aprendidos de la IA" in ayudado.motor
    # El clasificador solo, seguro: no hay nada que aprender.
    solo = _router(cfg, tmp_path, ClasificadorFalso("imagen", 0.92))
    assert not solo.aprender("dibuja a Kira", _decidir(solo, "dibuja a Kira"))
    # La IA en desacuerdo: se pregunta al usuario (y su botón será la corrección), no se aprende.
    duda = _router(cfg, tmp_path, ClasificadorFalso("tarea", 0.6), LLMFalso(Decision("nota", 0.9, motor="llm local")))
    assert not duda.aprender("el mercado del puerto", _decidir(duda, "el mercado del puerto"))
    assert len(ejemplos.leer_aprendidos(carpeta)) == 1


def test_qwen_dormido_si_la_config_no_dice_nada(tmp_path):
    # qwen no debe competir por recursos: sin la clave en config.yaml, queda apagado.
    ruta = tmp_path / "config.yaml"
    ruta.write_text("router: {umbral_ejecutar: 0.8}\n", encoding="utf-8")
    assert cargar(ruta)["proveedores"]["llm_local"]["activo"] is False
    assert cargar(None)["proveedores"]["llm_local"]["activo"] is False


def test_ordenes_concretas_nuevas_y_frases_que_no_lo_son():
    """Lo concreto va al router local (2026-09-30); frases parecidas no deben dispararlo."""
    from app.router.reglas import orden_hablada
    casos = {
        "Anota en mi diario que hoy entinté tres páginas": ("diario", "hoy entinté tres páginas"),
        "Anota esto en el diario: salió bien": ("diario", "salió bien"),
        "diario: terminé el boceto": ("diario", "terminé el boceto"),
        "Querido diario, hoy no dibujé": ("diario", "hoy no dibujé"),
        "limpia los temporales": ("limpiar", ""),
        "haz el diagnóstico de imágenes": ("diagnostico", ""),
        "cambia el modelo": ("modelo", ""),
        "qué puedes hacer": ("ayuda", ""),
        "nueva conversación": ("nuevo", ""),
        "dime mis tareas": ("tareas", ""),
        "anota la tarea comprar tinta": ("tarea", "comprar tinta"),
    }
    for frase, esperado in casos.items():
        assert orden_hablada(frase) == esperado, frase
    for frase in ("la tarea de hoy fue difícil", "el diario de Kael dice que miente",
                  "el modelo del personaje es raro", "hay que limpiar la escena del bosque"):
        assert orden_hablada(frase) is None, frase
