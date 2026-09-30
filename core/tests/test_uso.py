"""Tokens gastados: registro en OpenClaw, /tokens y /estado (sin internet)."""

import asyncio
import json
from datetime import date

import httpx

from app.acciones import analisis, uso
from app.estado.db import Estado, contador_de_uso
from app.proveedores.cadena import CadenaImagenes, Cortacircuitos
from app.proveedores.openclaw import Nivel, OpenClaw
from app.router.interprete import Interpretacion
from test_bot import SendPhoto, _boton_con, _con_imagenes, _con_proyecto, _montar, _msg, _run, _textos, _voz
from test_interprete import InterpreteFalso

HOY = date(2026, 9, 30)


def _gateway(textos, uso_informado=None):
    """Cada respuesta con el uso informado (o 900/80) y el modelo pedido."""
    cola = list(textos)

    def manejar(req):
        cuerpo = json.loads(req.content)
        return httpx.Response(200, json={"texto": cola.pop(0), "modelo": cuerpo["modelo"].split("/")[-1],
                                         "uso": uso_informado or {"inputTokens": 900, "outputTokens": 80}})
    return httpx.MockTransport(manejar)


# --- registro en el cliente de OpenClaw -----------------------------------------------------
def test_cada_respuesta_se_registra_con_su_funcion():
    vistas = []
    cli = OpenClaw("http://openclaw:18789", "s", transport=_gateway(["hola", "análisis"]),
                   funcion="interprete", contador=lambda f, r: vistas.append((f, r.modelo, r.tokens_entrada,
                                                                              r.tokens_salida)))
    asyncio.run(cli.completar("hola"))
    asyncio.run(cli.completar_con(Nivel("openai/gpt-6-sol", "low"), "x", funcion="analisis"))
    assert vistas == [("interprete", "gpt-6-luna", 900, 80), ("analisis", "gpt-6-sol", 900, 80)]


def test_salida_absurda_se_estima_por_el_largo():
    """Claude por Claude Code informó "2" de salida en un análisis largo (registros del 2026-09-29)."""
    largo = "palabra " * 500                                    # 4.000 caracteres: ~1.143 tokens
    cli = OpenClaw("http://openclaw:18789", "s", transport=_gateway([largo, "ok"], {"inputTokens": 542,
                                                                                    "outputTokens": 2}))
    r = asyncio.run(cli.completar("x"))
    assert r.salida_estimada and r.tokens_salida == 1143 and r.tokens_entrada == 542
    corto = asyncio.run(cli.completar("x"))                     # "ok" con 2 de salida es creíble
    assert not corto.salida_estimada and corto.tokens_salida == 2


def test_un_contador_que_falla_no_rompe_la_respuesta():
    def roto(funcion, r):
        raise OSError("disco lleno")
    cli = OpenClaw("http://openclaw:18789", "s", transport=_gateway(["hola"]), contador=roto)
    assert asyncio.run(cli.completar("x")).texto == "hola"


def test_contador_de_uso_suma_en_sqlite_con_la_fecha_local(tmp_path):
    e = Estado(tmp_path / "hub.sqlite3")
    cli = OpenClaw("http://openclaw:18789", "s", transport=_gateway(["a", "b"]), funcion="redactor",
                   contador=contador_de_uso(e, "Europe/Madrid"))
    asyncio.run(cli.completar("x"))
    asyncio.run(cli.completar("y"))
    (fila,) = e.uso()
    assert fila == ("redactor", "gpt-6-luna", 2, 1800, 160, 0)


# --- formato ---------------------------------------------------------------------------
def test_numeros_para_leer_y_para_decir():
    assert uso.miles(41230) == "41.230" and uso.miles(850) == "850"
    assert uso.para_decir(850) == "850" and uso.para_decir(41230) == "41 mil"
    assert uso.para_decir(1_250_000) == "1,2 millones" and uso.para_decir(2_000_000) == "2 millones"


def _con_uso(tmp_path):
    e = Estado(tmp_path / "hub.sqlite3")
    e.sumar_uso("2026-09-29", "consulta", "gpt-6-luna", 3000, 1000)
    e.sumar_uso("2026-09-30", "redactor", "gpt-6-sol", 2000, 400)
    e.sumar_uso("2026-09-30", "redactor", "gpt-6-sol", 1800, 300)
    e.sumar_uso("2026-09-30", "interprete", "gpt-6-sol", 700, 70)
    e.sumar_uso("2026-09-30", "analisis", "claude-opus-5-5", 540, 1143, estimada=True)
    e.sumar_uso("2026-09-30", "imagen", "gpt-image-2")
    return e


def test_texto_de_tokens_hoy_total_y_notas(tmp_path):
    texto = uso.texto_tokens(_con_uso(tmp_path), HOY)
    assert "Hoy (30/09): 6.953 tokens en 4 llamadas (5.040 de entrada y 1.913 de salida)" in texto
    assert "• Redactor · gpt-6-sol: 4.500 en 2 llamadas\n" in texto
    assert "• Análisis · claude-opus-5-5: 1.683 en 1 llamada ~" in texto
    assert "• Imágenes · gpt-image-2: 1 generada (sin datos de tokens)" in texto
    assert "Desde el 29/09: 10.953 tokens en 5 llamadas y 1 imágenes" in texto
    assert "• gpt-6-sol: 5.270\n• gpt-6-luna: 4.000\n• claude-opus-5-5: 1.683 ~" in texto
    assert uso.NOTA_ESTIMADA in texto and texto.endswith(uso.NOTA_LOCAL)
    assert uso.linea_estado(_con_uso(tmp_path / "b"), HOY) == (
        "Uso de hoy: 4 llamadas, 6.953 tokens, 1 imagen (detalle: /tokens)")


def test_texto_de_tokens_sin_datos_o_solo_hoy(tmp_path):
    e = Estado(tmp_path / "hub.sqlite3")
    assert uso.texto_tokens(e, HOY).startswith("Todavía no hay llamadas a modelos registradas.")
    assert uso.linea_estado(e, HOY) == "Uso de hoy: sin llamadas a modelos todavía"
    e.sumar_uso("2026-09-30", "interprete", "gpt-6-sol", 700, 70)
    texto = uso.texto_tokens(e, HOY)
    assert "Desde el" not in texto and uso.NOTA_ESTIMADA not in texto   # solo hoy y sin estimaciones


def test_tokens_hablados_cortos_y_sin_tablas(tmp_path):
    assert uso.hablado_tokens(_con_uso(tmp_path), HOY) == (
        "Hoy llevas 7 mil tokens en 4 llamadas. Desde el 29 de septiembre, 11 mil. "
        "Para el detalle, escribe barra tokens.")


# --- en el bot -----------------------------------------------------------------------------
def test_tokens_por_comando_y_por_frase_sin_gastar_tokens(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.interprete = InterpreteFalso()
    ctx.estado.sumar_uso(boveda.ahora().date().isoformat(), "interprete", "gpt-6-sol", 700, 70)
    _run(dp, bot, _msg("/tokens"), _msg("cuántos tokens llevo"))
    textos = _textos(sesion)
    assert textos[0] == textos[1] and "770 tokens en 1 llamada" in textos[0]
    assert ctx.interprete.contextos == []                       # la frase la resolvió el router local
    _run(dp, bot, _voz(ctx, "cuántos tokens hemos gastado hoy"))
    assert ctx.voz.hablados[-1].startswith("Hoy llevas 770 tokens en 1 llamada.")


def test_estado_muestra_modelos_imagenes_en_pausa_y_uso_de_hoy(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _con_imagenes(ctx, boveda)
    corta = Cortacircuitos(ctx.estado, fallos=1, espera_min=10)
    ctx.imagenes.cadena = CadenaImagenes(ctx.imagenes.cadena.proveedores, corta)
    corta.fallo("cloudflare", "HTTP 429 sin cuota")
    ctx.estado.sumar_uso(boveda.ahora().date().isoformat(), "redactor", "gpt-6-sol", 2000, 400)
    _run(dp, bot, _msg("/estado"))
    texto = _textos(sesion)[-1]
    assert "Imágenes: cloudflare: en pausa hasta las " in texto and "(último: HTTP 429 sin cuota)" in texto
    assert "Redactor: apagado: notas por tipo" in texto and "Intérprete: apagado" in texto
    assert texto.endswith("Uso de hoy: 1 llamada, 2.400 tokens (detalle: /tokens)")
    assert "Pendientes en cola" not in texto and "fase 2" not in texto
    _run(dp, bot, _voz(ctx, "estado"))                          # por voz: una frase, lo que falla primero
    hablado = ctx.voz.hablados[-1]
    assert hablado.startswith("El servidor test está activo. Ojo: las imágenes con cloudflare están en pausa "
                              "hasta las ")
    assert hablado.endswith("Hoy llevas 2 mil tokens en 1 llamada.")


def test_estado_con_todo_activo_nombra_modelos_y_razonamiento(tmp_path, cfg, boveda):
    from app.acciones.redactor import Redactor
    from test_interprete import ClienteFalso
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.interprete = InterpreteFalso()
    ctx.interprete.cliente = ClienteFalso()
    ctx.interprete.cliente.cadena = (Nivel("openai/gpt-6-sol", "low"),)
    ctx.redactor = Redactor(OpenClaw("http://x", "s"), Nivel("openai/gpt-6-sol", "medium"))
    _run(dp, bot, _msg("/estado"))
    texto = _textos(sesion)[-1]
    assert "Intérprete: gpt-6-sol (razonamiento bajo); respaldo local: reglas" in texto
    assert "Redactor: gpt-6-sol (razonamiento medio)" in texto


def test_el_analisis_y_las_imagenes_quedan_registrados(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _con_proyecto(tmp_path, cfg, boveda, ["## Conclusión\nEs viable."])
    ctx.openclaw.contador = contador_de_uso(ctx.estado, "Europe/Madrid")
    _run(dp, bot, _msg("/analisis ¿es viable?"))
    _run(dp, bot, _boton(_boton_con(sesion, "an:0:")))
    _run(dp, bot, _boton(_boton_con(sesion, "ef:low:")))
    assert [f[0] for f in ctx.estado.uso()] == ["analisis"]
    _con_imagenes(ctx, boveda)
    ctx.interprete = InterpreteFalso(Interpretacion("imagen", 0.95, prompt="una elfa"))
    _run(dp, bot, _msg("crea una elfa albina"))
    assert any(isinstance(m, SendPhoto) for m in sesion.enviados)
    assert ("imagen", "flux", 1, 0, 0, 0) in ctx.estado.uso()


def _boton(data):
    from test_bot import _boton as boton
    return boton(data)


def test_analisis_marca_su_funcion():
    vistas = []
    cli = OpenClaw("http://openclaw:18789", "s", transport=_gateway(["## Informe"]),
                   contador=lambda f, r: vistas.append(f))
    prep = analisis.Preparado("W", "p", [], [], "contexto", 10)
    opcion = analisis.Opcion("openai/gpt-6-sol", "GPT-6 Sol", razonamiento="low")
    asyncio.run(analisis.analizar(cli, opcion, prep, {}))
    assert vistas == ["analisis"]


def test_nombres_de_modelos_y_plurales_en_estado():
    from app.entradas import telegram_bot
    assert telegram_bot._modelo(Nivel("openai/gpt-6-sol", "low")) == "gpt-6-sol (razonamiento bajo)"
    assert telegram_bot._modelo(Nivel("claude-cli/claude-haiku-4-5", "off")) == "claude-haiku-4-5 (sin razonamiento)"
    assert telegram_bot._cuantos(1, "proyecto") == "1 proyecto" and telegram_bot._cuantos(3, "proyecto") == "3 proyectos"
