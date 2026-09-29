"""Evaluación del router: conjuntos de prueba separados del entrenamiento y métricas."""

from pathlib import Path

import pytest

from app.router import ejemplos
from app.router.reglas import Decision
from scripts import evaluar_router as ev

DATOS = Path(ev.PRUEBA).parent


@pytest.mark.parametrize("archivo", ["prueba.yaml", "prueba_ciega.yaml"])
def test_las_pruebas_no_estan_en_los_ejemplos(archivo):
    # Si una frase de prueba se usa para entrenar, el modelo "se sabe el examen" y la medición miente.
    prueba = ev.leer_prueba(DATOS / archivo)
    textos = [t for lista in ejemplos.leer_ejemplos().values() for t in lista]
    assert ev.solapadas(prueba, textos) == []


@pytest.mark.parametrize("archivo", ["prueba.yaml", "prueba_ciega.yaml"])
def test_las_pruebas_cubren_todas_las_acciones_de_texto(archivo):
    acciones = {a for _, a in ev.leer_prueba(DATOS / archivo)}
    assert acciones == set(ejemplos.leer_ejemplos())


def test_solapadas_ignora_mayusculas_y_tildes():
    prueba = [("Qué es un Storyboard", "consulta"), ("otra frase", "nota")]
    assert ev.solapadas(prueba, ["que es un storyboard"]) == ["Qué es un Storyboard"]


class RouterFalso:
    """Devuelve una decisión fija por frase; ejecuta desde 0,80 como el router real."""

    clasificador = None

    def __init__(self, respuestas):
        self.respuestas = respuestas

    async def decidir(self, texto):
        accion, confianza = self.respuestas[texto]
        return Decision(accion, confianza)

    def nivel(self, d):
        return "ejecutar" if d.confianza >= 0.80 else "confirmar"


def test_evaluar_distingue_ejecutar_mal_de_dudar():
    router = RouterFalso({
        "comprar tinta": ("tarea", 0.95),            # ejecuta bien
        "máscaras de zorro": ("imagen", 0.90),       # ejecuta mal: el peor error
        "el templo": ("consulta", 0.55),             # duda con propuesta equivocada
        "cómo se entinta": ("consulta", 0.60),       # duda con propuesta correcta
        "y se hace por viñeta?": ("nota", 0.97),     # pregunta tomada por nota: iría a la IA
    })
    prueba = [("comprar tinta", "tarea"), ("máscaras de zorro", "nota"), ("el templo", "nota"),
              ("cómo se entinta", "consulta"), ("y se hace por viñeta?", "consulta")]
    r = ev.evaluar(router, prueba)
    assert (r["frases"], r["acierta"], r["ejecuta_bien"], r["ejecuta_mal"]) == (5, 2, 1, 1)
    assert (r["duda"], r["duda_bien_propuesta"]) == (3, 1)
    assert r["por_accion"]["nota"] == {"n": 2, "acierta": 0, "ejecuta_mal": 1}
    assert r["confusiones"]["nota->imagen"] == 1


# --- control de calidad del reentrenamiento --------------------------------------------
from app.router import clasificador, evaluacion  # noqa: E402
from app.router.cascada import Router  # noqa: E402
from app.router.evaluacion import Medida  # noqa: E402


class Oraculo:
    """Clasificador que acierta todas las frases de prueba (o responde siempre `fija`)."""

    def __init__(self, fija=None):
        self.respuestas = dict(evaluacion.leer_pruebas())
        self.fija = fija
        self.metadatos = {}

    def predecir(self, texto):
        return Decision(self.fija or self.respuestas.get(texto, "nota"), 0.95)


def test_medir_cuenta_aciertos_y_errores_graves():
    prueba = [("a", "nota"), ("b", "tarea"), ("c", "imagen")]
    respuestas = {"a": Decision("nota", 0.9), "b": Decision("nota", 0.95), "c": Decision("nota", 0.6)}
    m = evaluacion.medir(respuestas.__getitem__, prueba, umbral_ejecutar=0.8)
    assert (m.frases, m.acierta, m.ejecuta_mal) == (3, 1, 1)   # "c" duda: no es error grave


def test_aceptable_con_tolerancia():
    actual = Medida(100, 90, 5)
    assert evaluacion.aceptable(Medida(100, 89, 6), actual) is None      # azar del entrenamiento
    assert "el actual" in evaluacion.aceptable(Medida(100, 85, 5), actual)
    assert "errores graves" in evaluacion.aceptable(Medida(100, 92, 9), actual)
    assert evaluacion.aceptable(Medida(100, 85, 5), None) is None        # sin modelo: mínimo 80 %
    assert "mínimo" in evaluacion.aceptable(Medida(100, 70, 5), None)


def _entrenar_con_control(nuevo, llamadas):
    """Imita a clasificador.entrenar: pasa el modelo nuevo por el control antes de reemplazar."""
    def entrenar(textos, etiquetas, destino, extra=None, control=None, **opciones):
        motivo, datos = control(nuevo)
        meta = {"ejemplos": len(textos), **(extra or {}), **datos}
        if motivo:
            raise clasificador.ModeloRechazado(motivo, meta)
        llamadas.append(meta)
        return meta
    return entrenar


def test_reentrenar_descarta_un_modelo_peor(cfg, tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(clasificador, "entrenar", _entrenar_con_control(Oraculo(fija="nota"), llamadas))
    monkeypatch.setattr(clasificador, "cargar", lambda carpeta: None)
    r = Router(cfg, tmp_path / "router")
    actual = r.clasificador = Oraculo()
    with pytest.raises(clasificador.ModeloRechazado) as e:
        r.reentrenar()
    assert "el actual acierta el 100 %" in e.value.motivo.replace("100%", "100 %")
    assert r.clasificador is actual and llamadas == []   # el bot sigue con el anterior


def test_reentrenar_acepta_y_guarda_la_medicion(cfg, tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(clasificador, "entrenar", _entrenar_con_control(Oraculo(), llamadas))
    monkeypatch.setattr(clasificador, "cargar", lambda carpeta: Oraculo())
    r = Router(cfg, tmp_path / "router")
    r.clasificador = Oraculo(fija="nota")        # el actual es malo
    meta = r.reentrenar()
    assert meta["evaluacion"]["porcentaje"] == 1.0
    assert meta["evaluacion_anterior"]["porcentaje"] < 0.3


def test_reentrenar_no_mide_frases_de_prueba_corregidas(cfg, tmp_path, monkeypatch):
    # Si el usuario corrige con botones una frase que está en la prueba, se entrena: sale de la medición.
    llamadas = []
    monkeypatch.setattr(clasificador, "entrenar", _entrenar_con_control(Oraculo(), llamadas))
    monkeypatch.setattr(clasificador, "cargar", lambda carpeta: None)
    r = Router(cfg, tmp_path / "router")
    frase, accion = evaluacion.leer_pruebas()[0]
    r.registrar(frase, accion)
    meta = r.reentrenar()
    assert meta["evaluacion"]["frases"] == len(evaluacion.leer_pruebas()) - 1
