"""Voz (paso A): cliente del servicio local y órdenes habladas."""

import asyncio

import json

import httpx
import pytest

from app.router.reglas import (archivo_aparte, limpiar_tarea, nombre_respondido, orden_hablada,
                               pedido_personaje, tipo_nota)
from app.voz.cliente import ClienteVoz, ErrorVoz, para_hablar


def _cliente(manejar):
    return ClienteVoz("http://voz:8090", transport=httpx.MockTransport(manejar))


def test_transcribir_envia_el_audio_y_devuelve_texto():
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return httpx.Response(200, json={"texto": " Nota idea, hola. ", "duracion": 2.0})
    assert asyncio.run(_cliente(manejar).transcribir(b"OggS")) == "Nota idea, hola."
    assert pedidos[0].url.path == "/transcribir" and pedidos[0].url.params["idioma"] == "es"
    assert pedidos[0].content == b"OggS"


def test_el_vocabulario_viaja_como_pista():
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return httpx.Response(200, json={"texto": "zorro"})
    cli = ClienteVoz("http://voz:8090", vocabulario=" zorro, Zamael ", transport=httpx.MockTransport(manejar))
    asyncio.run(cli.transcribir(b"OggS"))
    asyncio.run(_cliente(manejar).transcribir(b"OggS"))
    assert pedidos[0].url.params["pista"] == "zorro, Zamael"
    assert "pista" not in pedidos[1].url.params  # sin vocabulario no se envía


def test_errores_del_servicio_son_legibles():
    largo = _cliente(lambda r: httpx.Response(413, json={"detail": "El audio dura 300 s; el máximo es 120 s"}))
    with pytest.raises(ErrorVoz, match="máximo es 120 s"):
        asyncio.run(largo.transcribir(b"x"))

    def caido(r):
        raise httpx.ConnectError("no")
    with pytest.raises(ErrorVoz, match="no responde"):
        asyncio.run(_cliente(caido).transcribir(b"x"))
    assert asyncio.run(_cliente(caido).estado()) == "sin respuesta"
    listo = _cliente(lambda r: httpx.Response(200, json={"cargado": True, "modelo": "small", "dispositivo": "cpu"}))
    assert asyncio.run(listo.estado()) == "listo (whisper small, cpu; sin voz de respuesta)"


def test_hablar_devuelve_ogg_y_errores_legibles():
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return httpx.Response(200, content=b"OggS-voz", headers={"content-type": "audio/ogg"})
    assert asyncio.run(_cliente(manejar).hablar("Listo.")) == b"OggS-voz"
    assert pedidos[0].url.path == "/hablar" and json.loads(pedidos[0].content) == {"texto": "Listo."}
    with pytest.raises(ErrorVoz, match="error 503"):
        asyncio.run(_cliente(lambda r: httpx.Response(503, json={"detail": "x"})).hablar("hola"))


@pytest.mark.parametrize("texto, hablado", [
    ("Nota (idea) agregada a Proyectos/webtoon/Ideas.md", "Nota agregada a Ideas"),
    ("Personaje Kira creado en Proyectos/webtoon/Historia/Personajes/Kira.md", "Personaje Kira creado"),
    ("Nota agregada a la ficha de Kira (Proyectos/webtoon/Historia/Personajes/Kira.md)",
     "Nota agregada a la ficha de Kira"),
    ("Nota (historia) guardada en un archivo propio: Proyectos/w/Historia/2026-09-27-mercado.md",
     "Nota guardada en un archivo propio"),
    ("Pendientes en webtoon:\n1. terminar el storyboard\n2. comprar tinta",
     "Pendientes en webtoon: 1. terminar el storyboard. 2. comprar tinta"),
    ("Es el guion **dibujado**.", "Es el guion dibujado."),
    ("Kira ya tenía ficha; agregué la descripción a sus notas: Proyectos/w/Historia/Personajes/Kira.md",
     "Kira ya tenía ficha; agregué la descripción a sus notas"),
    ("No pude transcribir la nota de voz: el servicio de voz no responde",
     "No pude transcribir la nota de voz: el servicio de voz no responde"),
])
def test_para_hablar_quita_rutas_y_formato(texto, hablado):
    assert para_hablar(texto) == hablado


def test_para_hablar_corta_lo_largo():
    largo = ". ".join(f"Frase número {i} de una respuesta larga" for i in range(30)) + "."
    hablado = para_hablar(largo)
    assert len(hablado) < 400 and hablado.endswith("Y hay más, míralo por escrito.")


@pytest.mark.parametrize("frase, esperado", [
    ("Nota idea, la villana usa una máscara de zorro.", ("nota", "idea: la villana usa una máscara de zorro")),
    ("Nota de diálogo: Zamael dice que no.", ("nota", "dialogo: Zamael dice que no")),
    ("nota la ciudad tiene un mercado", ("nota", "la ciudad tiene un mercado")),
    ("Tarea: terminar el storyboard del capítulo 3.", ("tarea", "terminar el storyboard del capítulo 3")),
    ("Nueva tarea, comprar tinta.", ("tarea", "comprar tinta")),
    ("Añade la tarea practicar dos horas al día.", ("tarea", "practicar dos horas al día")),
    ("Apúntame una tarea: llamar al editor", ("tarea", "llamar al editor")),
    ("Agrega una nueva tarea, entintar la página 4", ("tarea", "entintar la página 4")),
    ("Guarda una nota de idea: el templo flota", ("nota", "idea: el templo flota")),
    ("Añade una nota, Zamael odia la lluvia", ("nota", "Zamael odia la lluvia")),
    ("Crea un proyecto nuevo llamado Webtoon.", ("proyecto", "nuevo Webtoon")),
    ("Nuevo proyecto: Cómic Zombi", ("proyecto", "nuevo Cómic Zombi")),
    ("Cambia al proyecto Webtoon.", ("proyecto", "Webtoon")),
    ("Muéstrame mis proyectos", ("proyecto", "")),
    ("¿Cuáles son mis tareas?", ("tareas", "")),
    ("¿Qué tengo pendiente?", ("tareas", "")),
    ("Estado.", ("estado", "")),
    ("Genera una imagen de un elefante albino.", ("img", "un elefante albino")),
    ("Dibújame una ilustración del templo en ruinas", ("img", "templo en ruinas")),
    ("Nota aparte, el templo flota.", ("nota", "Nota aparte, el templo flota")),
    ("la villana usa una máscara de zorro", None),
    ("tengo que terminar el storyboard", None),   # lo resuelve el router (regla de tarea)
    ("las tareas del capítulo son duras", None),
    ("la tarea de hoy es difícil", None),
    ("la nota del capítulo quedó rara", None),
])
def test_ordenes_habladas(frase, esperado):
    assert orden_hablada(frase) == esperado


@pytest.mark.parametrize("frase, esperado", [
    ("Añade la tarea practicar dos horas al día.", "practicar dos horas al día"),
    ("añadir tarea: revisar guion", "revisar guion"),
    ("Pon una tarea, comprar tinta", "comprar tinta"),
    ("tengo que terminar el storyboard", "terminar el storyboard"),
    ("Tarea: entintar", "entintar"),
    ("terminar la portada", "terminar la portada"),
    ("tarea", "tarea"),   # si no queda nada, se conserva el texto
])
def test_limpiar_tarea_quita_la_orden(frase, esperado):
    assert limpiar_tarea(frase) == esperado


@pytest.mark.parametrize("frase, esperado", [
    ("Crea un archivo sobre el mercado flotante.", "El mercado flotante"),
    ("Créame un documento nuevo con la lista de escenas", "La lista de escenas"),
    ("Nota aparte: el templo flota", "El templo flota"),
    ("El templo flota, en un archivo aparte.", "El templo flota"),
    ("aparte: los barcos son peces", "Los barcos son peces"),   # /nota aparte: …
    ("la nota del capítulo está en otro archivo", None),
    ("Nueva nota, el mercado", None),
    ("nota idea, la villana", None),
])
def test_archivo_aparte(frase, esperado):
    assert archivo_aparte(frase) == esperado


@pytest.mark.parametrize("frase, esperado", [
    ("Crea un personaje que sea un carnicero que use un gancho de carne.",
     (None, "Un carnicero que use un gancho de carne.")),
    ("Crea un personaje llamado Bruno que sea carnicero", ("Bruno", "Carnicero.")),
    ("Nuevo personaje: Kira, una espadachina", ("Kira", "Una espadachina.")),
    ("Nuevo personaje, Kira.", ("Kira", "")),
    ("Inventa un personaje que se llame Ana Luz, una bruja", ("Ana Luz", "Una bruja.")),
    ("crea un nuevo personaje de nombre toto", ("toto", "")),
    ("Crea un personaje. Un carnicero enorme.", (None, "Un carnicero enorme.")),
    ("Bueno, vamos a crear un personaje llamado Kira. Es una espadachina.",
     ("Kira", "Es una espadachina.")),
    ("Quiero que crees un personaje que sea un herrero", (None, "Un herrero.")),
    ("Tengo una idea. Crea un personaje llamado Aeli, una elfa albina.", ("Aeli", "Una elfa albina.")),
    ("Vamos a crear una escena en el mercado", None),
    ("el personaje es alto", None),
    ("la villana es la hermana del protagonista", None),
])
def test_pedido_personaje(frase, esperado):
    assert pedido_personaje(frase) == esperado


@pytest.mark.parametrize("frase, esperado", [
    ("Se llama Bruno.", "Bruno"), ("Bruno", "Bruno"), ("Ponle Ana Luz", "Ana Luz"),
    ("su nombre es Kira", "Kira"), ("la villana usa una máscara de zorro", None), ("", None),
    # respuestas reales del usuario (2026-09-27)
    ("El nombre del personaje será Aeli.", "Aeli"), ("El nombre del personaje sera aeli", "aeli"),
    ("Se va a llamar Ana Luz y es una bruja", "Ana Luz"), ("Llámala Aeli, como la flor", "Aeli"),
    ("Le vamos a poner «Toto».", "Toto"), ("se llamará Kira", "Kira"),
])
def test_nombre_respondido(frase, esperado):
    assert nombre_respondido(frase) == esperado


@pytest.mark.parametrize("frase, tipo", [
    ("En la ficha de personajes anota que la niña tiene poderes", "historia"),
    ("los capítulos 2 y 3 pasan de noche", "historia"),
    ("la paleta será cobre y tierra", "produccion"),
    ("hay que rehacer las viñetas", "produccion"),
])
def test_tipo_nota_con_plurales(frase, tipo):
    assert tipo_nota(frase) == tipo
