"""Cliente de OpenClaw (plugin hub-puente), sin red: el gateway se simula con MockTransport."""

import asyncio
import json

import httpx

from app.config import POR_DEFECTO
from app.proveedores.openclaw import (CADENA_POR_DEFECTO, Nivel, OpenClaw, aplanar,
                                      cadena_desde_config, quitar_cercas)


def _correr(coro):
    return asyncio.run(coro)


def _cliente(manejar, token="secreto", cadena=CADENA_POR_DEFECTO):
    return OpenClaw("http://openclaw:18789/", token, cadena,
                    transport=httpx.MockTransport(manejar))


def _ok(texto, entrada=134, salida=17, cache=0):
    return httpx.Response(200, json={
        "texto": texto, "proveedor": "openai", "modelo": "gpt-6-luna", "ms": 1500,
        "uso": {"inputTokens": entrada, "outputTokens": salida, "cacheReadTokens": cache}})


def test_primer_modelo_responde_con_token_y_razonamiento_minimo():
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return _ok("Hola.")
    r = _correr(_cliente(manejar).completar("hola", sistema="Breve."))
    assert r.texto == "Hola." and r.tokens_entrada == 134 and r.tokens_salida == 17
    req = pedidos[0]
    assert req.url.path == "/hub/completar"
    assert req.headers["authorization"] == "Bearer secreto"
    cuerpo = json.loads(req.content)
    assert cuerpo == {"modelo": "openai/gpt-6-luna", "razonamiento": "low", "sistema": "Breve.",
                      "mensajes": [{"rol": "user", "texto": "hola"}]}


def test_si_chatgpt_falla_usa_haiku_aislado_con_historial_aplanado():
    cuerpos = []

    def manejar(req):
        cuerpos.append(json.loads(req.content))
        if len(cuerpos) == 1:
            return httpx.Response(502, json={"error": "cuota agotada"})
        return _ok("Aeli tiene 17.")
    historial = [("user", "Aeli tiene 17 años."), ("assistant", "Anotado."),
                 ("user", "¿Qué edad tiene Aeli?")]
    r = _correr(_cliente(manejar).completar(historial))
    assert r.texto == "Aeli tiene 17."
    haiku = cuerpos[1]
    assert haiku["modelo"] == "claude-cli/claude-haiku-4-5" and haiku["razonamiento"] == "off"
    assert haiku["aislado"] is True and "mensajes" not in haiku
    assert "Usuario: Aeli tiene 17 años." in haiku["mensaje"]
    assert haiku["mensaje"].endswith("¿Qué edad tiene Aeli?")


def test_ninguno_responde_devuelve_none_sin_lanzar():
    def manejar(req):
        raise httpx.ConnectError("sin red")
    assert _correr(_cliente(manejar).completar("hola")) is None


def test_respuesta_vacia_pasa_al_siguiente():
    llamadas = []

    def manejar(req):
        llamadas.append(1)
        return _ok("" if len(llamadas) == 1 else "listo")
    assert _correr(_cliente(manejar).completar("hola")).texto == "listo"


def test_sin_token_no_llama():
    def manejar(req):
        raise AssertionError("no debía llamar")
    cliente = _cliente(manejar, token="")
    assert cliente.falta_configurar()
    assert _correr(cliente.completar("hola")) is None


def test_completar_json_quita_cercas_y_salta_respuestas_no_json():
    respuestas = iter(["no sé", '```json\n{"accion": "tarea", "confianza": 0.95}\n```'])

    def manejar(req):
        return _ok(next(respuestas))
    datos = _correr(_cliente(manejar).completar_json("Clasifica.", "pasarle bocetos a Lucía"))
    assert datos == {"accion": "tarea", "confianza": 0.95}


def test_tokens_incluyen_la_cache():
    r = _correr(_cliente(lambda req: _ok("x", entrada=1043, cache=1792)).completar("hola"))
    assert r.tokens_entrada == 2835


def test_ultimo_mensaje_debe_ser_del_usuario():
    def manejar(req):
        raise AssertionError("no debía llamar")
    assert _correr(_cliente(manejar).completar([("assistant", "hola")])) is None


def test_utilidades():
    assert quitar_cercas('```\n{"a": 1}\n```') == '{"a": 1}'
    assert quitar_cercas('{"a": 1}') == '{"a": 1}'
    assert aplanar([("user", "solo esto")]) == "solo esto"


def test_cadena_desde_config():
    assert cadena_desde_config(POR_DEFECTO["proveedores"]["consulta"]) == CADENA_POR_DEFECTO
    assert cadena_desde_config([{"modelo": "x/y", "razonamiento": "low"}, {"id": "viejo"}]) == (
        Nivel("x/y", "low"),)
    assert cadena_desde_config(None) == CADENA_POR_DEFECTO


def test_completar_con_un_solo_modelo_y_tiempo_propio():
    cuerpos = []

    def manejar(req):
        cuerpos.append(json.loads(req.content))
        return _ok("Análisis.")
    cliente = _cliente(manejar)
    r = _correr(cliente.completar_con(Nivel("openai/gpt-6-sol", "low"), "revisa", "Sistema.", 2500, 300))
    assert r.texto == "Análisis." and cliente.ultimo_error is None
    assert cuerpos == [{"modelo": "openai/gpt-6-sol", "razonamiento": "low", "sistema": "Sistema.",
                        "mensajes": [{"rol": "user", "texto": "revisa"}], "max_tokens": 2500,
                        "tiempo_max_s": 300}]


def test_completar_con_explica_el_fallo_sin_probar_otro():
    llamadas = []

    def manejar(req):
        llamadas.append(req)
        raise httpx.ReadTimeout("lento", request=req)
    cliente = _cliente(manejar)
    assert _correr(cliente.completar_con(Nivel("claude-cli/claude-opus-5-5", "off", True), "x",
                                         tiempo_max_s=30)) is None
    assert len(llamadas) == 1 and cliente.ultimo_error == "no respondió en 45 s"
    sin_token = OpenClaw("http://openclaw:18789", "", transport=httpx.MockTransport(manejar))
    assert _correr(sin_token.completar_con(Nivel("a/b", "off"), "x")) is None
    assert "OPENCLAW_GATEWAY_TOKEN" in sin_token.ultimo_error
