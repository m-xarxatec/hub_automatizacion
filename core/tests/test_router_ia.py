"""Router con la IA por OpenClaw (día 5): contradicciones, ejecución directa y personajes.

Sin red: el gateway se simula con httpx.MockTransport y el clasificador con un doble.
"""

import asyncio
import json

import httpx
import pytest

from app.proveedores.openclaw import OpenClaw
from app.router.llm_openclaw import OpinionIA
from app.router.reglas import Decision, pedido_personaje
from tests.test_router_local import ClasificadorFalso, LLMFalso, _decidir, _router


class IAFalsa(LLMFalso):
    confiable = True


def _opinion_ia(respuesta, capturas=None):
    def manejar(req):
        if capturas is not None:
            capturas.append(json.loads(req.content))
        texto = respuesta if isinstance(respuesta, str) else json.dumps(respuesta)
        return httpx.Response(200, json={"texto": texto, "modelo": "gpt-6-luna", "uso": {}})
    cliente = OpenClaw("http://openclaw:18789", "secreto", transport=httpx.MockTransport(manejar))
    return OpinionIA(cliente, ["nota", "tarea", "imagen", "consulta", "referencia"])


# --- contradicciones y ejecución directa -------------------------------------------
def test_pregunta_tomada_por_nota_consulta_a_la_ia(cfg, tmp_path):
    ia = IAFalsa(Decision("consulta", 0.95, motor="ia"))
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.95), ia)
    d = _decidir(r, "Y se hace por viñeta?")
    assert ia.llamadas == 1
    assert d.accion == "consulta" and r.nivel(d) == "ejecutar"


def test_pregunta_tomada_por_nota_sin_ia_no_se_guarda_sola(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.95), IAFalsa(None))
    d = _decidir(r, "Y se hace por viñeta?")
    assert d.accion == "nota" and r.nivel(d) == "confirmar"


def test_nota_segura_sin_pregunta_no_consulta_a_la_ia(cfg, tmp_path):
    ia = IAFalsa(Decision("consulta", 0.95, motor="ia"))
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.95), ia)
    assert _decidir(r, "la villana usa una máscara").accion == "nota"
    assert ia.llamadas == 0


def test_ia_confiable_y_segura_se_ejecuta(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.6), IAFalsa(Decision("tarea", 0.9, motor="ia")))
    d = _decidir(r, "mañana le paso los bocetos a Lucía")
    assert d.accion == "tarea" and r.nivel(d) == "ejecutar" and d.motor == "clasificador+ia"


def test_ia_poco_segura_solo_propone(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.3), IAFalsa(Decision("tarea", 0.7, motor="ia")))
    d = _decidir(r, "mañana le paso los bocetos a Lucía")
    assert d.accion == "tarea" and r.nivel(d) == "confirmar"


def test_llm_local_seguro_nunca_se_ejecuta_solo(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.3), LLMFalso(Decision("tarea", 0.99, motor="llm")))
    assert r.nivel(_decidir(r, "mañana le paso los bocetos a Lucía")) == "confirmar"


def test_tipo_de_la_ia_gana_cuando_coinciden(cfg, tmp_path):
    ia = IAFalsa(Decision("nota", 0.9, tipo="historia", motor="ia", extra={"tipo_ia": True}))
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.6), ia)
    d = _decidir(r, "en la ficha de la niña anota que tiene poderes")
    assert d.tipo == "historia" and r.nivel(d) == "ejecutar"


def test_la_ia_aprendida_entra_en_aprendidos(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("nota", 0.95), IAFalsa(Decision("consulta", 0.95, motor="ia")))
    d = _decidir(r, "Y se hace por viñeta?")
    assert r.aprender("Y se hace por viñeta?", d)


# --- OpinionIA -------------------------------------------------------------------------
def test_opinion_ia_personaje_con_nombre_y_descripcion():
    capturas = []
    op = _opinion_ia({"accion": "personaje", "confianza": 0.93, "tipo": "historia",
                      "nombre": "Aeli", "descripcion": "elfa albina de ojos rojos"}, capturas)
    d = asyncio.run(op.opinar("vamos a crear una elfa albina de ojos rojos llamada Aeli"))
    assert d.accion == "personaje" and d.confianza == 0.93 and d.motor == "ia"
    assert d.extra["personaje"] == "Aeli" and d.extra["descripcion"] == "Elfa albina de ojos rojos."
    enviado = capturas[0]
    assert enviado["modelo"] == "openai/gpt-6-luna" and enviado["razonamiento"] == "low"
    assert "personaje" in enviado["sistema"]
    assert json.loads(enviado["mensajes"][0]["texto"]) == {
        "mensaje": "vamos a crear una elfa albina de ojos rojos llamada Aeli"}


def test_opinion_ia_nota_con_tipo():
    d = asyncio.run(_opinion_ia({"accion": "nota", "confianza": 0.9, "tipo": "produccion"}).opinar("paleta cobre"))
    assert d.tipo == "produccion" and d.extra["tipo_ia"] is True


@pytest.mark.parametrize("respuesta", [
    {"accion": "borrar_todo", "confianza": 1},
    {"accion": "nota", "confianza": "mucha"},
    "no sé qué es esto",
])
def test_opinion_ia_descarta_respuestas_invalidas(respuesta):
    assert asyncio.run(_opinion_ia(respuesta).opinar("hola")) is None


def test_intro_con_ahora():
    assert pedido_personaje("Bueno, ahora vamos a crear un personaje llamado Kira, es una espadachina.") == (
        "Kira", "Es una espadachina.")


@pytest.mark.parametrize("frase, consulta_ia", [
    ("Dentro de personajes vamos a crear una elfo albina de ojos rojos llamada a Ellie.", True),
    ("Crea un archivo llamado escenas con la del mercado", True),
    ("la villana usa una máscara de zorro", False),
    ("En la ficha de personajes anota que la niña tiene poderes", False),
])
def test_crear_con_nombre_consulta_a_la_ia(cfg, tmp_path, frase, consulta_ia):
    ia = IAFalsa(None)
    _decidir(_router(cfg, tmp_path, ClasificadorFalso("nota", 1.0), ia), frase)
    assert ia.llamadas == int(consulta_ia)


def test_ia_segura_que_coincide_se_ejecuta(cfg, tmp_path):
    r = _router(cfg, tmp_path, ClasificadorFalso("tarea", 0.5), IAFalsa(Decision("tarea", 0.9, motor="ia")))
    d = _decidir(r, "mañana le tengo que mandar los bocetos a Lucía")
    assert d.accion == "tarea" and r.nivel(d) == "ejecutar"
