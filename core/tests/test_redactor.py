"""Redactor: el LLM decide qué escribir y dónde; el código valida y solo agrega (sin internet)."""

import asyncio
import json

import httpx
import pytest

from app.acciones import redactor
from app.acciones.redactor import Plan, Redactor
from app.boveda import escritor
from app.proveedores.openclaw import Nivel, OpenClaw
from app.router.interprete import Interpretacion
from test_bot import SendChatAction, _montar, _msg, _run, _textos
from test_interprete import InterpreteFalso


def _proyecto(boveda):
    boveda.crear_proyecto("Webtoon")
    return boveda.carpeta_proyectos / "Webtoon"


def _ficha(carpeta, nombre, cuerpo="", alias=()):
    ruta = carpeta / "Personajes" / f"{nombre}.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(escritor.con_frontmatter({"tipo": "personaje", "nombre": nombre, "aliases": list(alias)},
                                             f"# {nombre}\n\n{cuerpo}"), encoding="utf-8")
    return ruta


def _op(archivo, texto="algo", **extra):
    return {"op": "agregar", "archivo": archivo, "texto": texto, **extra}


# --- validación ----------------------------------------------------------------------------
def test_validar_no_sale_del_proyecto_ni_toca_lo_del_bot(boveda):
    _proyecto(boveda)
    plan = redactor.validar({"operaciones": [
        _op("../../fuera.md"), _op("/etc/passwd"), _op("Imagenes/elfa1.md"), _op("analisis/x.md"),
        _op("tareas.md"), _op("Historia.md", texto="   "), "no es un dict", _op("Historia.md")]},
        boveda, "Webtoon")
    assert plan.descartadas == 6
    carpeta = boveda.carpeta_proyectos / "Webtoon"
    # La barra inicial es la raíz del proyecto: todo queda dentro de él.
    assert [op.ruta for op in plan.operaciones] == [carpeta / "etc" / "passwd.md", carpeta / "Historia.md"]


def test_validar_crear_sobre_existente_agrega_y_agregar_sobre_inexistente_crea(boveda):
    carpeta = _proyecto(boveda)
    (carpeta / "Historia.md").write_text("# Historia\n\nKael caza monstruos.\n", encoding="utf-8")
    plan = redactor.validar({"operaciones": [
        {"op": "crear", "archivo": "historia", "texto": "Otra escena."},       # sin .md y en minúsculas
        _op("Mundo.md", texto="El reino de Vel."),
    ]}, boveda, "Webtoon")
    historia, mundo = plan.operaciones
    assert (historia.op, historia.ruta) == ("agregar", carpeta / "Historia.md")   # nunca se pisa
    assert (mundo.op, mundo.ruta) == ("crear", carpeta / "Mundo.md")


def test_validar_ficha_nueva_va_a_la_carpeta_de_personajes_y_la_existente_por_alias(boveda):
    carpeta = _proyecto(boveda)
    aely = _ficha(carpeta, "Aely", "Elfa albina.", alias=["Aeli"])
    plan = redactor.validar({"operaciones": [
        {"op": "crear", "archivo": "Kael.md", "personaje": True, "texto": "Cazador de monstruos."},
        {"op": "crear", "archivo": "Personajes/Aeli.md", "personaje": True, "seccion": "Combate",
         "texto": "Pelea con dos hachas."},
    ]}, boveda, "Webtoon")
    kael, aeli = plan.operaciones
    assert (kael.op, kael.ruta, kael.personaje) == ("crear", carpeta / "Personajes" / "Kael.md", True)
    assert (aeli.op, aeli.ruta, aeli.seccion) == ("agregar", aely, "## Combate")


def test_validar_respeta_la_carpeta_de_personajes_de_proyectos_anteriores(boveda):
    carpeta = _proyecto(boveda)
    (carpeta / "Historia" / "Personajes").mkdir(parents=True)
    plan = redactor.validar({"operaciones": [
        {"op": "crear", "archivo": "Personajes/Kael.md", "personaje": True, "texto": "Cazador."}]},
        boveda, "Webtoon")
    assert plan.operaciones[0].ruta == carpeta / "Historia" / "Personajes" / "Kael.md"


def test_validar_sin_proyecto_escribe_en_la_bandeja_y_sin_fichas(boveda):
    plan = redactor.validar({"operaciones": [
        {"op": "crear", "archivo": "Kael.md", "personaje": True, "texto": "Cazador."}]}, boveda, None)
    op = plan.operaciones[0]
    assert op.ruta == boveda.bandeja / "Kael.md" and not op.personaje


# --- aplicar -------------------------------------------------------------------------------
def test_aplicar_crea_con_contenido_agrega_en_secciones_y_al_final(boveda):
    carpeta = _proyecto(boveda)
    aely = _ficha(carpeta, "Aely", "Elfa albina.")
    (carpeta / "Historia.md").write_text("# Historia\n\nKael caza monstruos.\n", encoding="utf-8")
    plan = redactor.validar({"operaciones": [
        {"op": "crear", "archivo": "Kael.md", "personaje": True, "texto": "Cazador de monstruos."},
        {"op": "agregar", "archivo": "Personajes/Aely.md", "seccion": "## Combate", "texto": "Pelea con dos hachas."},
        {"op": "agregar", "archivo": "Personajes/Aely.md", "seccion": "Combate", "texto": "Zurda."},
        {"op": "agregar", "archivo": "Personajes/Aely.md", "seccion": "Combate", "texto": "- Hacha doble"},
        {"op": "agregar", "archivo": "Historia.md", "titulo": "El perdón", "texto": "[[Kael]] perdona a [[Aely]]."},
        {"op": "crear", "archivo": "Mundo.md", "texto": "El reino de Vel."},
        {"op": "crear", "archivo": "Mundo.md", "texto": "Tiene dos lunas."},   # el mismo plan lo creó antes
    ]}, boveda, "Webtoon")
    rutas = redactor.aplicar(boveda, plan, "Webtoon", "voz")
    assert [r.name for r in rutas] == ["Kael.md", "Aely.md", "Historia.md", "Mundo.md"]
    kael = (carpeta / "Personajes" / "Kael.md").read_text(encoding="utf-8")
    assert escritor.leer_frontmatter(carpeta / "Personajes" / "Kael.md")["tipo"] == "personaje"
    assert kael.endswith("---\n# Kael\n\nCazador de monstruos.\n")          # sin secciones vacías
    # Párrafos separados por una línea en blanco; las viñetas, seguidas.
    assert aely.read_text(encoding="utf-8").endswith(
        "Elfa albina.\n\n## Combate\n\nPelea con dos hachas.\n\nZurda.\n- Hacha doble\n")
    historia = (carpeta / "Historia.md").read_text(encoding="utf-8")
    assert historia.startswith("# Historia\n\nKael caza monstruos.\n")      # lo anterior intacto
    assert "\n## El perdón\n\n_" in historia and "· voz_\n\n[[Kael]] perdona a [[Aely]].\n" in historia
    mundo = (carpeta / "Mundo.md").read_text(encoding="utf-8")
    assert "# Mundo\n\nEl reino de Vel.\n" in mundo and mundo.endswith("Tiene dos lunas.\n")
    diario = next((boveda.raiz / "Diario").glob("*.md")).read_text(encoding="utf-8")
    assert "Personaje nuevo [[Proyectos/Webtoon/Personajes/Kael|Kael]]" in diario
    assert "[[Proyectos/Webtoon/Historia#El perdón|Historia]]" in diario


# --- cobertura -----------------------------------------------------------------------------
def test_cobertura_ignora_la_orden_y_detecta_lo_que_falta(boveda):
    base = _proyecto(boveda)
    mensaje = "Crea un personaje llamado Kael que es un cazador de monstruos y odia la lluvia"
    completo = redactor.validar({"operaciones": [
        {"op": "crear", "archivo": "Kael.md", "personaje": True,
         "texto": "Cazador de monstruos. Odia la lluvia."}]}, boveda, "Webtoon")
    assert redactor.cobertura(mensaje, completo, base) == 1.0
    recortado = redactor.validar({"operaciones": [
        {"op": "crear", "archivo": "Notas.md", "texto": "Un cazador."}]}, boveda, "Webtoon")
    assert redactor.cobertura(mensaje, recortado, base) < redactor.UMBRAL_COBERTURA["texto"]
    assert redactor.cobertura("anota esto", recortado, base) == 1.0   # sin palabras de contenido


# --- contexto ------------------------------------------------------------------------------
def test_contexto_manda_contenido_sin_lo_del_bot_y_respeta_el_tope(boveda):
    carpeta = _proyecto(boveda)
    _ficha(carpeta, "Aely", "Elfa albina de ojos rojos.")
    (carpeta / "Historia.md").write_text("---\ntipo: notas\n---\n# Historia\n\nKael caza monstruos.\n",
                                         encoding="utf-8")
    (carpeta / "Relleno.md").write_text("palabra " * 4000, encoding="utf-8")   # ~9.000 tokens
    for reservado in ("Imagenes/elfa1.md", "Analisis/a.md"):
        (carpeta / reservado).parent.mkdir()
        (carpeta / reservado).write_text("del bot", encoding="utf-8")
    boveda.agregar_tarea("entintar", "Webtoon")
    c = redactor.contexto(boveda, "Webtoon", "Aely pelea con hachas", 2000)
    assert c["fichas"] == ["Personajes/Aely.md"] and c["carpeta_personajes"] == "Personajes"
    assert list(c["archivos"])[0] == "Personajes/Aely.md"                    # lo más relacionado primero
    assert c["archivos"]["Historia.md"] == "# Historia\n\nKael caza monstruos."   # sin frontmatter
    todos = set(c["archivos"]) | set(c["otros_archivos"])
    assert "Imagenes/elfa1.md" not in todos and "Analisis/a.md" not in todos and "tareas.md" not in todos
    assert c["archivos"]["Relleno.md"].startswith("(recortado") or "Relleno.md" in c["otros_archivos"]
    assert sum(redactor.estimar_tokens(t) for t in c["archivos"].values()) <= 2000


# --- modelo --------------------------------------------------------------------------------
def _gateway(respuestas, cuerpos, estado=200):
    textos = iter(respuestas)

    def manejar(req):
        cuerpos.append(json.loads(req.content))
        if estado != 200:
            return httpx.Response(estado, json={"error": "sin cuota"})
        texto = next(textos)
        return httpx.Response(200, json={"texto": texto if isinstance(texto, str) else json.dumps(texto),
                                         "modelo": "gpt-6-sol", "uso": {"inputTokens": 900, "outputTokens": 120}})
    return OpenClaw("http://openclaw:18789", "secreto", transport=httpx.MockTransport(manejar))


def _redactor(respuestas, cuerpos, estado=200):
    return Redactor(_gateway(respuestas, cuerpos, estado), Nivel("openai/gpt-6-sol", "medium"),
                    max_tokens=2000, tope_contexto_tokens=5000)


def test_planear_manda_mensaje_y_contexto_como_datos(boveda):
    _proyecto(boveda)
    cuerpos = []
    r = _redactor([{"operaciones": [_op("Historia.md", "Kael odia la lluvia.", titulo="Kael y la lluvia")],
                    "respuesta": "Lo anoté en Historia."}], cuerpos)
    plan = asyncio.run(r.planear(boveda, "Kael odia la lluvia", "Webtoon", "voz",
                                 ultima={"accion": "imagen", "imagen": "kael1"}, pista={"accion": "nota"}))
    assert plan.respuesta == "Lo anoté en Historia." and plan.operaciones[0].op == "crear"
    assert (cuerpos[0]["modelo"], cuerpos[0]["razonamiento"]) == ("openai/gpt-6-sol", "medium")
    enviado = json.loads(cuerpos[0]["mensajes"][-1]["texto"])
    assert enviado["mensaje"] == "Kael odia la lluvia" and enviado["origen"] == "voz"
    assert enviado["ultima_accion"]["imagen"] == "kael1" and enviado["pista_del_interprete"] == {"accion": "nota"}
    assert "Solo agrega" not in cuerpos[0]["sistema"] and "Solo JSON" in cuerpos[0]["sistema"]


def test_planear_sin_respuesta_o_sin_json_devuelve_none(boveda):
    _proyecto(boveda)
    assert asyncio.run(_redactor([], [], estado=502).planear(boveda, "hola", "Webtoon", "texto")) is None
    assert asyncio.run(_redactor(["no es json"], []).planear(boveda, "hola", "Webtoon", "texto")) is None
    vacio = {"operaciones": [], "respuesta": "", "pregunta": ""}
    assert asyncio.run(_redactor([vacio], []).planear(boveda, "hola", "Webtoon", "texto")) is None


def test_planear_pregunta_o_marca_el_original_si_pierde_palabras(boveda):
    _proyecto(boveda)
    pregunta = {"operaciones": [], "pregunta": "¿Cómo se llama el personaje?"}
    plan = asyncio.run(_redactor([pregunta], []).planear(boveda, "crea un personaje carnicero", "Webtoon", "texto"))
    assert plan.pregunta == "¿Cómo se llama el personaje?" and not plan.operaciones
    mensaje = "Kael es un cazador de monstruos que perdona a una kitsune hermosa"
    pobre = {"operaciones": [_op("Historia.md", "Un cazador.")]}
    plan = asyncio.run(_redactor([pobre], []).planear(boveda, mensaje, "Webtoon", "texto"))
    assert plan.operaciones and plan.original == mensaje and plan.cobertura < 0.6   # no se descarta
    completo = {"operaciones": [_op("Historia.md", "Kael, cazador de monstruos, perdona a una kitsune hermosa.")]}
    plan = asyncio.run(_redactor([completo], []).planear(boveda, mensaje, "Webtoon", "texto"))
    assert plan.original == "" and plan.cobertura == 1.0


def test_la_voz_tolera_futuros_y_relleno(boveda):
    """Audio real del 2026-09-30: el redactor pasa "medirá, estará, será" a presente."""
    base = _proyecto(boveda)
    _ficha(base, "Deacon")
    mensaje = ("Deacon será un tipo de piel bronceada, medirá 1,85 m, estará totalmente tatuado excepto "
               "la cara y manejará una moto.")
    plan = redactor.validar({"operaciones": [
        {"op": "agregar", "archivo": "Personajes/Deacon.md", "seccion": "Apariencia",
         "texto": "Piel bronceada, mide 1,85 m y tiene todo el cuerpo tatuado salvo la cara. Maneja una moto."}]},
        boveda, "Webtoon")
    assert redactor.cobertura(mensaje, plan, base) >= redactor.UMBRAL_COBERTURA["voz"]
    # "Se va a llamar Días del futuro pasado": el nombre del proyecto ya está en la carpeta.
    boveda.crear_proyecto("Días del futuro pasado")
    otra = boveda.carpeta_proyectos / "Días del futuro pasado"
    premisa = redactor.validar({"operaciones": [_op("_proyecto.md", "Un hombre viaja en el tiempo…",
                                                    titulo="Premisa de la historia")]},
                               boveda, "Días del futuro pasado")
    frase = ("Vale, vas a crear un nuevo proyecto que se va a llamar Días del futuro pasado y esta será "
             "la premisa de la historia, esta que me acabas de dar.")
    assert redactor.cobertura(frase, premisa, otra) == 1.0


def test_con_cobertura_baja_el_original_va_plegado_junto_a_lo_primero(boveda):
    carpeta = _proyecto(boveda)
    aely = _ficha(carpeta, "Aely", "Elfa albina.")
    plan = redactor.validar({"operaciones": [
        {"op": "agregar", "archivo": "Personajes/Aely.md", "seccion": "Combate", "texto": "Pelea con hachas."},
        {"op": "crear", "archivo": "Mundo.md", "texto": "El reino de Vel."}]}, boveda, "Webtoon")
    plan.original = "ella pelea con dos hachas\ny el reino se llama Vel"
    redactor.aplicar(boveda, plan, "Webtoon", "voz")
    ficha = aely.read_text(encoding="utf-8")
    assert "## Combate\n\nPelea con hachas.\n\n> [!quote]- Tu audio transcrito original (" in ficha
    assert ficha.endswith("> ella pelea con dos hachas\n> y el reino se llama Vel\n")
    assert "[!quote]" not in (carpeta / "Mundo.md").read_text(encoding="utf-8")   # solo una vez


# --- en el bot -----------------------------------------------------------------------------
def _bot_con_redactor(tmp_path, cfg, boveda, respuestas, *interpretaciones, estado=200):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    cuerpos = []
    ctx.redactor = _redactor(respuestas, cuerpos, estado)
    ctx.interprete = InterpreteFalso(*interpretaciones)
    return ctx, dp, bot, sesion, cuerpos


KAEL = ("Kael es un cazador de monstruos que un día decide perdonar a Aely, una elfa. "
        "Ella se convierte en la villana y al final se enamora de él.")
PLAN_KAEL = {
    "operaciones": [
        {"op": "crear", "archivo": "Personajes/Kael.md", "personaje": True,
         "texto": "Cazador de monstruos. Perdona a [[Aely]]."},
        {"op": "agregar", "archivo": "Personajes/Aely.md", "seccion": "Historia",
         "texto": "Kael le perdona la vida; se convierte en la villana y al final se enamora de él."},
        {"op": "agregar", "archivo": "Historia.md", "titulo": "El perdón de Kael",
         "texto": "[[Kael]], cazador de monstruos, decide un día perdonar a [[Aely]], una elfa. Ella se "
                  "convierte en la villana y al final se enamora de él."}],
    "respuesta": "Creé la ficha de Kael, anoté en la de Aely y agregué la escena a Historia.",
    "avisos": ["Antes Aely era una kitsune; ahora dices que es elfa."]}


def test_nota_libre_la_reparte_el_redactor(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _bot_con_redactor(tmp_path, cfg, boveda, [PLAN_KAEL],
                                                      Interpretacion("nota", 0.95, contenido=KAEL))
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"))
    carpeta = boveda.carpeta_proyectos / "Webtoon"
    _ficha(carpeta, "Aely", "Una kitsune hermosa.")
    _run(dp, bot, _msg(KAEL))
    respuesta = _textos(sesion)[-1]
    assert respuesta.startswith("Creé la ficha de Kael")
    assert "- Proyectos/Webtoon/Personajes/Kael.md" in respuesta and "⚠ Antes Aely era una kitsune" in respuesta
    assert (carpeta / "Personajes" / "Kael.md").exists() and (carpeta / "Historia.md").exists()
    assert "## Historia\n\nKael le perdona la vida" in (carpeta / "Personajes" / "Aely.md").read_text(encoding="utf-8")
    assert not (carpeta / "Ideas.md").exists()                              # nada de archivos por tipo
    enviado = json.loads(cuerpos[0]["mensajes"][-1]["texto"])
    assert enviado["mensaje"] == KAEL and "Personajes/Aely.md" in enviado["archivos"]
    assert enviado["ultima_accion"]["accion"] == "pregunta"                  # la del proyecto nuevo
    assert ctx.ultima_de(1111)["archivos"][0] == "Proyectos/Webtoon/Personajes/Kael.md"
    assert any(isinstance(m, SendChatAction) for m in sesion.enviados)


def test_redactor_pregunta_y_la_respuesta_llega_con_contexto(tmp_path, cfg, boveda):
    pregunta = {"operaciones": [], "pregunta": "¿Cómo se llama el personaje?"}
    ficha = {"operaciones": [{"op": "crear", "archivo": "Bruno.md", "personaje": True,
                              "texto": "Carnicero que usa un gancho de carne."}], "respuesta": "Creé a Bruno."}
    ctx, dp, bot, sesion, cuerpos = _bot_con_redactor(
        tmp_path, cfg, boveda, [pregunta, ficha],
        Interpretacion("personaje", 0.95), Interpretacion("personaje", 0.95, personaje="Bruno"))
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("crea un personaje carnicero con un gancho de carne"))
    assert _textos(sesion)[-1] == "¿Cómo se llama el personaje?"
    assert not list((boveda.carpeta_proyectos / "Webtoon").glob("**/*.md"))[1:]   # solo _proyecto.md
    _run(dp, bot, _msg("Bruno"))
    # El intérprete y el redactor reciben la pregunta y el mensaje original.
    assert ctx.interprete.contextos[1]["ultima_accion"]["pregunta"] == "¿Cómo se llama el personaje?"
    ultima = json.loads(cuerpos[1]["mensajes"][-1]["texto"])["ultima_accion"]
    assert ultima["mensaje"] == "crea un personaje carnicero con un gancho de carne"
    assert (boveda.carpeta_proyectos / "Webtoon" / "Personajes" / "Bruno.md").exists()


def test_si_el_redactor_falla_la_nota_se_guarda_como_antes(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, _ = _bot_con_redactor(
        tmp_path, cfg, boveda, [], Interpretacion("nota", 0.95, contenido="El templo flota.", tipo="historia"),
        estado=502)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("anota que el templo flota"))
    assert "Nota (historia) agregada a Proyectos/Webtoon/Historia.md" in _textos(sesion)[-1]


def test_si_el_redactor_pierde_palabras_se_guarda_lo_organizado_y_el_original(tmp_path, cfg, boveda):
    pobre = {"operaciones": [_op("Historia.md", "Un templo.", titulo="El templo")], "respuesta": "Listo."}
    texto = "el templo flotante tiene raíces de cristal que cantan cuando llueve"
    ctx, dp, bot, sesion, _ = _bot_con_redactor(tmp_path, cfg, boveda, [pobre],
                                                Interpretacion("nota", 0.95, contenido=texto, tipo="historia"))
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg(texto))
    historia = (boveda.carpeta_proyectos / "Webtoon" / "Historia.md").read_text(encoding="utf-8")
    assert "# Historia\n\nUn templo.\n\n> [!quote]- Tu mensaje original (" in historia   # se crea con ambos
    assert f"> {texto}\n" in historia
    assert "Guardé también tu mensaje tal cual" in _textos(sesion)[-1]


def test_nota_con_prefijo_va_directo_al_redactor_sin_interprete(tmp_path, cfg, boveda):
    plan = {"operaciones": [_op("Ideas.md", "La villana usa una máscara de zorro.", titulo="Máscara")],
            "respuesta": "Anotado en Ideas."}
    ctx, dp, bot, sesion, cuerpos = _bot_con_redactor(tmp_path, cfg, boveda, [plan])
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("nota idea: la villana usa una máscara de zorro"))
    assert ctx.interprete.contextos == []                                    # no hizo falta el intérprete
    enviado = json.loads(cuerpos[0]["mensajes"][-1]["texto"])
    assert enviado["mensaje"] == "la villana usa una máscara de zorro"
    assert enviado["pista_del_interprete"] == {"accion": "nota", "tipo": "idea"}
    assert _textos(sesion)[-1].startswith("Anotado en Ideas.")


def test_proyecto_nuevo_con_descripcion_la_guarda_el_redactor(tmp_path, cfg, boveda):
    plan = {"operaciones": [_op("_proyecto.md", "Webtoon de fantasía oscura sobre cazadores.")],
            "respuesta": "Guardé de qué trata el proyecto."}
    texto = "crea el proyecto Sombras, un webtoon de fantasía oscura sobre cazadores"
    ctx, dp, bot, sesion, cuerpos = _bot_con_redactor(
        tmp_path, cfg, boveda, [plan],
        Interpretacion("proyecto", 0.95, proyecto="Sombras", crear=True,
                       contenido="un webtoon de fantasía oscura sobre cazadores"))
    _run(dp, bot, _msg(texto))
    indice = (boveda.carpeta_proyectos / "Sombras" / "_proyecto.md").read_text(encoding="utf-8")
    assert "fantasía oscura sobre cazadores" in indice
    assert ctx.estado.proyecto_activo(1111) == "Sombras"
    assert json.loads(cuerpos[0]["mensajes"][-1]["texto"])["proyecto"] == "Sombras"


# --- lo concreto va al router local, por texto también ------------------------------------
def test_ordenes_concretas_por_texto_no_gastan_tokens(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion, cuerpos = _bot_con_redactor(tmp_path, cfg, boveda, [])
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"), _msg("tarea: comprar tinta"), _msg("dime mis tareas"),
         _msg("Anota en mi diario que hoy entinté tres páginas"), _msg("/diario terminé el boceto"))
    textos = _textos(sesion)
    assert "Tarea agregada a Proyectos/Webtoon/tareas.md" in textos[1]
    assert "1. comprar tinta" in textos[2]
    assert textos[3].startswith("Anotado en el diario de hoy") and textos[4].startswith("Anotado en el diario")
    diario = next((boveda.raiz / "Diario").glob("*.md")).read_text(encoding="utf-8")
    assert " hoy entinté tres páginas\n" in diario and " terminé el boceto\n" in diario
    assert ctx.interprete.contextos == [] and cuerpos == []


def test_asi_sera_aely_nombra_la_imagen_y_la_pone_en_su_ficha(tmp_path, cfg, boveda):
    from test_bot import _con_imagenes
    ctx, dp, bot, sesion, _ = _bot_con_redactor(
        tmp_path, cfg, boveda, [], Interpretacion("imagen", 0.95, prompt="Una elfa albina", nombre_imagen="elfa"),
        Interpretacion("nombrar_imagen", 0.95, personaje="Aely"))
    _con_imagenes(ctx, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"))
    carpeta = boveda.carpeta_proyectos / "Webtoon"
    ficha = _ficha(carpeta, "Aely", "Elfa albina.")
    _run(dp, bot, _msg("crea una elfa albina"), _msg("así será el personaje Aely"))
    assert "ahora se llama aely1 y quedó en la ficha de Aely" in _textos(sesion)[-1]
    assert ficha.read_text(encoding="utf-8").endswith("\n\n## Referencias visuales\n\n![[aely1.jpg]]\n")


def test_consulta_lee_las_notas_del_proyecto(tmp_path, cfg, boveda):
    from test_bot import _montar_con_openclaw
    ctx, dp, bot, sesion, cuerpos = _montar_con_openclaw(tmp_path, cfg, boveda,
                                                         respuestas=("Kael caza monstruos.",))
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"))
    (boveda.carpeta_proyectos / "Webtoon" / "Historia.md").write_text(
        "# Historia\n\nKael caza monstruos y perdona a Aely.\n", encoding="utf-8")
    _run(dp, bot, _msg("/consulta ¿y la historia?"))
    assert "Kael caza monstruos y perdona a Aely." in cuerpos[0]["sistema"]
    assert "«Webtoon»" in cuerpos[0]["sistema"]
    assert [m["texto"] for m in cuerpos[0]["mensajes"]] == ["¿y la historia?"]   # las notas no van al historial


def test_resumen_hablado_sin_enlaces_ni_rutas():
    plan = Plan([], respuesta="Anoté lo de [[Kael]] y [[Proyectos/W/Aely|Aely]].", avisos=["Aely era kitsune."])
    assert redactor.resumen_hablado(plan) == "Anoté lo de Kael y Aely. Ojo: Aely era kitsune."


def test_anota_esto_tras_una_consulta_y_un_proyecto_nuevo(tmp_path, cfg, boveda):
    """Caso real del 2026-09-30: consulta → "crea el proyecto webtoon" → "anota esto dentro de la idea
    principal". El bot recuerda las últimas acciones: el redactor recibe la respuesta de la consulta."""
    from test_bot import _montar_con_openclaw
    idea = "El minuto que no existió: un archivista viaja al pasado y todo se distorsiona."
    ctx, dp, bot, sesion, _ = _montar_con_openclaw(tmp_path, cfg, boveda, respuestas=(idea,))
    cuerpos = []
    ctx.redactor = _redactor([{"operaciones": [_op("_proyecto.md", idea, titulo="Idea principal")],
                               "respuesta": "Guardé la idea en el proyecto."}], cuerpos)
    ctx.interprete = InterpreteFalso(Interpretacion("proyecto", 0.95, proyecto="webtoon", crear=True),
                                     Interpretacion("nota", 0.8))
    _run(dp, bot, _msg("/consulta dame ideas de un viajero del tiempo lovecraftiano"),
         _msg("crea un proyecto llamado webtoon"),
         _msg("Anota esto dentro de la idea principal del proyecto webtoon"))
    ultima = json.loads(cuerpos[0]["mensajes"][-1]["texto"])["ultima_accion"]
    assert ultima["accion"] == "pregunta" and ultima["proyecto_nuevo"] == "webtoon"
    assert ultima["anteriores"][0] == {"accion": "consulta", "pregunta": "dame ideas de un viajero del tiempo "
                                       "lovecraftiano", "respuesta": idea}
    assert idea in (boveda.carpeta_proyectos / "webtoon" / "_proyecto.md").read_text(encoding="utf-8")
    assert _textos(sesion)[-1].startswith("Guardé la idea en el proyecto.")


def test_recuerda_solo_las_ultimas_acciones_vigentes(tmp_path, cfg, boveda):
    from app.entradas import telegram_bot
    ctx, *_ = _montar(tmp_path, cfg, boveda)
    for n in range(5):
        ctx.recordar(1, accion="nota", n=n)
    u = ctx.ultima_de(1)
    assert u["n"] == 4 and [a["n"] for a in u["anteriores"]] == [3, 2]
    ctx.ultima[1][0]["hora"] -= telegram_bot.ULTIMA_TTL_S + 1        # la más reciente venció
    assert ctx.ultima_de(1)["n"] == 3


def test_el_audio_lleva_los_nombres_del_proyecto_a_whisper(tmp_path, cfg, boveda):
    from test_bot import _voz
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Días del futuro pasado"), _msg("/proyecto nuevo webtoon"),
         _msg("/proyecto Días del futuro pasado"))
    _ficha(boveda.carpeta_proyectos / "Días del futuro pasado", "Deacon", alias=["Dikon"])
    _run(dp, bot, _voz(ctx, "dime mis tareas"))
    assert ctx.voz.pistas == ["Proyecto Días del futuro pasado. Personajes: Deacon, Dikon. "
                              "Otros proyectos: webtoon. zorro, villana"]


def test_imagen_de_personaje_va_a_su_ficha_solo_si_se_pide(tmp_path, cfg, boveda):
    from test_bot import SendPhoto, _con_imagenes
    ctx, dp, bot, sesion, _ = _bot_con_redactor(
        tmp_path, cfg, boveda, [],
        Interpretacion("imagen", 0.95, prompt="Deacon, piel bronceada", nombre_imagen="Deacon"),
        Interpretacion("imagen", 0.95, prompt="Deacon en su moto", nombre_imagen="Deacon"))
    _con_imagenes(ctx, boveda)
    _run(dp, bot, _msg("/proyecto nuevo Webtoon"))
    ficha = _ficha(boveda.carpeta_proyectos / "Webtoon", "Deacon", "Protagonista.")
    _run(dp, bot, _msg("crea una imagen de referencia de Dikon que va a estar dentro de su ficha"))
    fotos = [m for m in sesion.enviados if isinstance(m, SendPhoto)]
    assert "y en la ficha de Deacon" in fotos[-1].caption
    assert ficha.read_text(encoding="utf-8").endswith("## Referencias visuales\n\n![[deacon1.jpg]]\n")
    _run(dp, bot, _msg("hazme otra de Deacon en su moto"))                  # sin pedirlo: solo en Imagenes/
    assert "ficha" not in [m for m in sesion.enviados if isinstance(m, SendPhoto)][-1].caption
    assert "deacon2" not in ficha.read_text(encoding="utf-8")
