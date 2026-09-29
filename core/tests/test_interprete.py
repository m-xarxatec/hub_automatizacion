"""Intérprete con GPT: validación, contexto, llamada al gateway y su uso en el bot.

GPT no se llama de verdad: el gateway de OpenClaw se simula con httpx.MockTransport y, en las
pruebas del bot, el intérprete se reemplaza por uno que devuelve interpretaciones fijas.
"""

import asyncio
import json

import httpx

from app.proveedores.openclaw import CADENA_POR_DEFECTO, OpenClaw
from app.router import ejemplos
from app.router import interprete as interp
from app.router.interprete import Interpretacion, Interprete
from app.router.reglas import Decision
from test_bot import _con_imagenes, _fotos, _montar, _msg, _run, _textos


# --- validación -------------------------------------------------------------------------
def test_validar_rechaza_acciones_desconocidas():
    assert interp.validar({"accion": "borrar_todo", "confianza": 1}, {}, {}) is None


def test_validar_solo_acepta_destinos_de_la_lista(tmp_path):
    archivos = {"Referencia elfa": tmp_path / "Referencia elfa.md"}
    i = interp.validar({"accion": "nota", "confianza": 0.9, "destino": "referencia ELFA"}, archivos, {})
    assert i.destino_archivo == tmp_path / "Referencia elfa.md"      # sin mayúsculas ni tildes
    inventado = interp.validar({"accion": "nota", "confianza": 0.9, "destino": "../../etc/passwd"}, archivos, {})
    assert inventado.destino_archivo is None                             # nunca una ruta del modelo


def test_validar_ficha_de_personaje_y_archivo_nuevo():
    fichas = {"Karito": "villana de 200 años"}
    i = interp.validar({"accion": "nota", "confianza": 0.9, "destino": "personaje:karito"}, {}, fichas)
    assert i.destino_personaje == "Karito"
    otro = interp.validar({"accion": "nota", "confianza": 0.9, "destino": "personaje:Nadie"}, {}, fichas)
    assert otro.destino_personaje is None
    nuevo = interp.validar({"accion": "nota", "confianza": 0.9, "destino": "nuevo:Mapa del reino"}, {}, {})
    assert nuevo.destino_nuevo == "Mapa del reino"


def test_validar_acota_confianza_y_tipo():
    i = interp.validar({"accion": "nota", "confianza": "7", "tipo": "poesia"}, {}, {})
    assert (i.confianza, i.tipo) == (1.0, "general")


# --- contexto ---------------------------------------------------------------------------
def test_archivos_de_incluye_proyecto_y_raiz_sin_imagenes(tmp_path):
    raiz = tmp_path / "Boveda"
    proyecto = raiz / "Proyectos" / "Webtoon"
    for rel in ("Ideas.md", "Historia/Personajes/Karito.md", "Imagenes/karito1.md", "Analisis/a.md",
                "_proyecto.md", "tareas.md"):
        (proyecto / rel).parent.mkdir(parents=True, exist_ok=True)
        (proyecto / rel).write_text("x", encoding="utf-8")
    (raiz / "Referencia elfa.md").write_text("x", encoding="utf-8")
    archivos = interp.archivos_de(raiz, proyecto)
    assert set(archivos) == {"Ideas", "Historia/Personajes/Karito", "Referencia elfa"}


def test_resumen_ficha_omite_encabezados_vacios(tmp_path):
    ficha = tmp_path / "Karito.md"
    ficha.write_text("---\ntipo: personaje\n---\n# Karito\n\n## Descripción\n\nVillana de 200 años.\n\n"
                     "## Notas\n\n- 2026-09-29 18:08 (voz): Tiene seis colas.\n", encoding="utf-8")
    assert interp.resumen_ficha(ficha) == "Villana de 200 años. 2026-09-29 18:08 (voz): Tiene seis colas."


# --- llamada al gateway -------------------------------------------------------------------
def _gateway(respuesta, cuerpos, estado=200):
    def manejar(req):
        cuerpos.append(json.loads(req.content))
        if estado != 200:
            return httpx.Response(estado, json={"error": "sin cuota"})
        return httpx.Response(200, json={"texto": respuesta, "modelo": "gpt-6-luna",
                                         "uso": {"inputTokens": 480, "outputTokens": 60}})
    return OpenClaw("http://openclaw:18789", "secreto", CADENA_POR_DEFECTO, transport=httpx.MockTransport(manejar))


def test_interpretar_usa_solo_chatgpt_y_manda_el_mensaje_como_dato(tmp_path):
    cuerpos = []
    cliente = _gateway('```json\n{"accion": "nota", "confianza": 0.95, "contenido": "tiene 200 años",'
                       ' "destino": "personaje:Karito"}\n```', cuerpos)
    ctx = interp.contexto("Webtoon", {}, {}, {"accion": "imagen", "imagen": "karito1"})
    ctx["personajes"] = {"Karito": ""}
    i = asyncio.run(Interprete(cliente).interpretar("anota en la ficha de Carito que tiene 200 años", ctx))
    assert (i.accion, i.contenido, i.destino_personaje) == ("nota", "tiene 200 años", "Karito")
    assert len(cuerpos) == 1 and cuerpos[0]["modelo"] == "openai/gpt-6-luna"
    enviado = json.loads(cuerpos[0]["mensajes"][-1]["texto"])
    assert enviado["mensaje"] == "anota en la ficha de Carito que tiene 200 años"
    assert enviado["ultima_accion"]["imagen"] == "karito1" and "_rutas" not in enviado


def test_interpretar_sin_respuesta_no_pasa_a_haiku():
    cuerpos = []
    cliente = _gateway("", cuerpos, estado=502)
    assert asyncio.run(Interprete(cliente).interpretar("hola", interp.contexto(None, {}, {}, None))) is None
    assert len(cuerpos) == 1   # Haiku por Claude Code cuesta ~3.600 tokens: el respaldo es SetFit


# --- en el bot ----------------------------------------------------------------------------
class ClienteFalso:
    cadena = CADENA_POR_DEFECTO


class InterpreteFalso:
    """Devuelve interpretaciones fijas y guarda el contexto recibido."""

    cliente = ClienteFalso()

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.contextos = []

    async def interpretar(self, texto, contexto):
        self.contextos.append(contexto)
        return self.respuestas.pop(0) if self.respuestas else None


def _con_interprete(tmp_path, cfg, boveda, *respuestas):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ctx.interprete = InterpreteFalso(*respuestas)
    return ctx, dp, bot, sesion


def _proyecto_con_karito(ctx, dp, bot):
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"))
    ficha = ctx.boveda.carpeta_proyectos / "Webtoon" / "Historia" / "Personajes" / "Karito.md"
    ficha.write_text("---\ntipo: personaje\nnombre: Karito\n---\n# Karito\n\n## Descripción\n\nVillana.\n\n"
                     "## Notas\n\n## Referencias visuales\n", encoding="utf-8")
    return ficha


def test_nota_va_a_la_ficha_sin_la_orden(tmp_path, cfg, boveda):
    nota = Interpretacion("nota", 0.95, contenido="Tiene 200 años y se enamora del protagonista.",
                          destino_personaje="Karito")
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda, nota)
    ficha = _proyecto_con_karito(ctx, dp, bot)
    _run(dp, bot, _msg("Muy bien, dentro de la ficha de Carito vas a colocar que tiene 200 años…"))
    texto = ficha.read_text(encoding="utf-8")
    assert "Tiene 200 años y se enamora del protagonista." in texto and "vas a colocar" not in texto
    assert "Nota agregada a la ficha de Karito" in _textos(sesion)[-1]
    assert "Karito" in ctx.interprete.contextos[0]["personajes"]


def test_nota_va_a_un_archivo_existente_de_la_raiz(tmp_path, cfg, boveda):
    ref = boveda.raiz / "Referencia elfa.md"
    ref.write_text("![[elfa.jpg]]\n\nLa elfa será así\n", encoding="utf-8")
    nota = Interpretacion("nota", 0.9, contenido="Ella es una elfa de 20 años.", destino_archivo=ref)
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda, nota)
    _run(dp, bot, _msg("Quiero que anotes en el archivo referencia elfa lo siguiente: ella es una elfa de 20 años"))
    texto = ref.read_text(encoding="utf-8")
    assert texto.startswith("![[elfa.jpg]]\n\nLa elfa será así\n")   # lo del usuario queda intacto
    assert texto.rstrip().endswith("Ella es una elfa de 20 años.")
    assert "Nota agregada a Referencia elfa.md" in _textos(sesion)[-1]


def test_imagen_usa_prompt_y_nombre_de_gpt_y_se_puede_rehacer(tmp_path, cfg, boveda):
    primera = Interpretacion("imagen", 0.95, prompt="Karito, villana zorro de seis colas, armadura corta",
                             nombre_imagen="Karito")
    rehacer = Interpretacion("rehacer_imagen", 0.9, prompt="Karito, seis colas, armadura corta, anime simple",
                             nombre_imagen="Karito")
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda, primera, rehacer)
    _con_imagenes(ctx, boveda)
    _proyecto_con_karito(ctx, dp, bot)
    _run(dp, bot, _msg("enséñame cómo sería la villana con armadura corta"),
         _msg("no me gusta, que sea estilo anime y no tan detallada"))
    imagenes = ctx.boveda.carpeta_proyectos / "Webtoon" / "Imagenes"
    assert sorted(p.name for p in imagenes.glob("*.md")) == ["karito1.md", "karito2.md"]
    assert "anime simple" in (imagenes / "karito2.md").read_text(encoding="utf-8")
    assert len(_fotos(sesion)) == 2
    # La segunda vez, GPT recibió cuál fue la última imagen y su prompt.
    assert ctx.interprete.contextos[1]["ultima_accion"]["imagen"] == "karito1"


def test_mover_nota_copia_y_no_borra(tmp_path, cfg, boveda):
    nota = Interpretacion("nota", 0.9, contenido="Pelea con dos hachas.", tipo="historia")
    mover = Interpretacion("mover_nota", 0.9, destino_personaje="Karito")
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda, nota, mover)
    ficha = _proyecto_con_karito(ctx, dp, bot)
    _run(dp, bot, _msg("pelea con dos hachas"), _msg("no ahí, ponla en la ficha de Karito"))
    historia = ctx.boveda.carpeta_proyectos / "Webtoon" / "Historia.md"
    assert "Pelea con dos hachas." in historia.read_text(encoding="utf-8")   # la original no se borra
    assert "Pelea con dos hachas." in ficha.read_text(encoding="utf-8")
    assert "sigue en Proyectos/Webtoon/Historia.md" in _textos(sesion)[-1]


def test_crear_proyecto_hablado(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda,
                                           Interpretacion("proyecto", 0.95, proyecto="Webtoon", crear=True))
    _run(dp, bot, _msg("Vamos a crear un proyecto nuevo llamado webtoon."))
    assert ctx.boveda.buscar_proyecto("webtoon") == "Webtoon"
    assert ctx.estado.proyecto_activo(1111) == "Webtoon"


def test_confianza_baja_pregunta_con_botones(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda, Interpretacion("tarea", 0.4, contenido="x"))
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("lo del capítulo tres"))
    assert "¿Qué hago con esto?" in _textos(sesion)[-1]
    assert not ctx.boveda.tareas_abiertas("Webtoon")


def test_sin_respuesta_de_gpt_decide_el_router_local_sin_ia(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda)   # el intérprete devuelve None
    llamadas = []

    async def decidir(texto, tiene_imagen=False, sin_ia=False):
        llamadas.append(sin_ia)
        return Decision("tarea", 0.9, motor="clasificador")
    ctx.router.decidir = decidir
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("comprar tinta"))
    assert llamadas == [True]   # GPT ya falló: no se vuelve a intentar
    assert "Tarea agregada" in _textos(sesion)[-1]


def test_gpt_ensena_a_setfit_solo_donde_fallaba(tmp_path, cfg, boveda):
    class SetFitFalso:
        metadatos = {}

        def __init__(self, accion, confianza):
            self.d = Decision(accion, confianza, motor="clasificador")

        def predecir(self, texto):
            return self.d
    tarea = Interpretacion("tarea", 0.95, contenido="Comprar tinta")
    ctx, dp, bot, sesion = _con_interprete(tmp_path, cfg, boveda, tarea, tarea)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"))
    ctx.router.clasificador = SetFitFalso("tarea", 0.99)      # acertaba: no aprende nada
    _run(dp, bot, _msg("no se me puede olvidar comprar tinta"))
    assert ejemplos.leer_aprendidos(ctx.router.carpeta) == []
    ctx.router.clasificador = SetFitFalso("nota", 0.95)       # se equivocaba: aprende
    _run(dp, bot, _msg("ojo con la tinta"))
    assert ejemplos.leer_aprendidos(ctx.router.carpeta) == [{"texto": "ojo con la tinta", "accion": "tarea"}]


def test_extraer_json_con_texto_alrededor():
    assert interp.extraer_json('Aquí va: {"accion": "nota"} listo') == {"accion": "nota"}
    assert interp.extraer_json("no hay nada") is None


def test_respuesta_sin_json_se_reintenta_una_vez():
    cuerpos = []
    cliente = _gateway("perdón, no entendí", cuerpos)
    assert asyncio.run(Interprete(cliente).interpretar("hola", interp.contexto(None, {}, {}, None))) is None
    assert len(cuerpos) == 2


def test_ficha_elegida_como_archivo_va_a_sus_notas(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    ficha = _proyecto_con_karito(ctx, dp, bot)
    ctx.interprete = InterpreteFalso(Interpretacion("nota", 0.95, contenido="Dibujarla con seis colas.",
                                                    destino_archivo=ficha))
    _run(dp, bot, _msg("no se me puede olvidar dibujarla con seis colas"))
    texto = ficha.read_text(encoding="utf-8")
    notas = texto.split("## Notas")[1].split("## Referencias visuales")[0]
    assert "Dibujarla con seis colas." in notas


def test_personaje_existente_con_descripcion_vacia_la_completa(tmp_path, cfg, boveda):
    from app.acciones import personajes
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"))
    ficha, creada = personajes.crear_o_anotar(boveda, "Webtoon", "Kael", "", "voz")
    assert creada and personajes.descripcion_vacia(ficha)
    personajes.crear_o_anotar(boveda, "Webtoon", "Kael", "Mide 1,90 m y tiene ojos plata.", "voz")
    texto = ficha.read_text(encoding="utf-8")
    assert texto.split("## Descripción")[1].split("## Personalidad")[0].strip() == "Mide 1,90 m y tiene ojos plata."
    personajes.crear_o_anotar(boveda, "Webtoon", "Kael", "Usa una espada gigante.", "voz")
    texto = ficha.read_text(encoding="utf-8")
    assert "Usa una espada gigante." in texto.split("## Notas")[1]       # ya tenía descripción: va a notas
    assert "Mide 1,90 m" in texto.split("## Descripción")[1].split("## Personalidad")[0]
