"""Modo análisis (decisión 4): selección de notas, estimación de tokens y guardado. Sin red."""

import asyncio

import httpx

from app.acciones import analisis
from app.boveda import escritor
from app.proveedores.openclaw import OpenClaw, Respuesta


def _proyecto(boveda, nombre="Webtoon"):
    boveda.crear_proyecto(nombre)
    return boveda.carpeta_proyectos / nombre


def test_opciones_de_config_con_razonamiento_minimo(cfg):
    opciones = analisis.opciones_desde_config(cfg)
    assert [o.modelo for o in opciones] == ["claude-cli/claude-opus-5-5", "claude-cli/claude-sonnet-5",
                                            "openai/gpt-6-sol"]
    opus, sonnet, sol = opciones
    # El esfuerzo por defecto es el menor que acepta cada modelo (Opus no acepta "off").
    assert opus.nombre == "Opus 5.5" and opus.razonamiento == "low" and opus.aislado and opus.extra_tokens
    assert opus.lista_esfuerzos() == ("low", "medium", "high", "xhigh", "max")
    assert sonnet.razonamiento == "off" and "max" in sonnet.lista_esfuerzos()
    assert sol.razonamiento == "low" and not sol.aislado and sol.extra_tokens == 0
    assert opus.con_esfuerzo("high").nivel().razonamiento == "high"
    assert analisis.nombre_esfuerzo(opus.con_esfuerzo("xhigh")) == "muy alto"


def test_esfuerzos_sin_lista_o_invalidos():
    cfg = {"proveedores": {"analisis": {"opciones": [
        {"modelo": "a/uno"}, {"modelo": "a/dos", "esfuerzos": ["raro", "medium"]}]}}}
    uno, dos = analisis.opciones_desde_config(cfg)
    assert uno.razonamiento == "low" and uno.lista_esfuerzos() == ("low",)
    assert dos.lista_esfuerzos() == ("medium",) and dos.razonamiento == "medium"


def test_predeterminado_y_orden(cfg):
    assert analisis.predeterminado(cfg, None).modelo == "claude-cli/claude-opus-5-5"   # recomendado
    sol = analisis.predeterminado(cfg, "openai/gpt-6-sol")
    assert sol.nombre == "GPT-6 Sol"
    # Un modelo guardado que ya no está en config.yaml vuelve al recomendado.
    assert analisis.predeterminado(cfg, "openai/viejo").modelo == "claude-cli/claude-opus-5-5"
    orden = analisis.ordenar(analisis.opciones_desde_config(cfg), sol)
    assert [o.nombre for o in orden] == ["GPT-6 Sol", "Opus 5.5", "Sonnet 5"]


def test_preparar_incluye_todo_si_cabe_y_no_los_analisis_previos(boveda):
    carpeta = _proyecto(boveda)
    boveda.guardar_nota("la villana es la hermana del protagonista", "Webtoon", "historia")
    boveda.guardar_nota("máscara de zorro", "Webtoon", "idea")
    (carpeta / "Analisis").mkdir()
    (carpeta / "Analisis" / "viejo.md").write_text("análisis anterior", encoding="utf-8")
    prep = analisis.preparar(boveda, "Webtoon", "¿es viable que la villana sea la hermana?")
    nombres = [n.ruta.relative_to(carpeta).as_posix() for n in prep.notas]
    assert "Historia.md" in nombres and "Ideas.md" in nombres
    assert not any(n.startswith("Analisis/") for n in nombres) and not prep.fuera
    assert "la villana es la hermana" in prep.contexto and "análisis anterior" not in prep.contexto
    assert prep.contexto.startswith("Pedido del autor: ¿es viable")
    assert prep.tokens == analisis.estimar_tokens(analisis.SISTEMA) + analisis.estimar_tokens(prep.contexto)


def test_tope_prioriza_las_notas_del_pedido_y_recorta_dejando_el_final(boveda):
    carpeta = _proyecto(boveda)
    (carpeta / "Ideas.md").write_text("relleno " * 3000, encoding="utf-8")                # ~6.900 tokens
    (carpeta / "Historia.md").write_text("inicio " + "texto " * 2000 + "Zamael traiciona al grupo",
                                         encoding="utf-8")                              # ~3.400 tokens
    prep = analisis.preparar(boveda, "Webtoon", "analiza la traición de Zamael", tope_tokens=3000)
    primera = prep.notas[0]
    assert primera.ruta.name == "Historia.md" and primera.recortada       # la que habla de Zamael
    assert "Zamael traiciona al grupo" in prep.contexto                  # se conserva el final
    assert "inicio" not in prep.contexto
    assert any(p.name == "Ideas.md" for p in prep.fuera)                  # no quedó espacio
    assert prep.tokens <= 3000


def test_textos_de_confirmacion(boveda):
    carpeta = _proyecto(boveda)
    boveda.guardar_nota("la villana usa una máscara", "Webtoon", "historia")
    prep = analisis.preparar(boveda, "Webtoon", "revisa la historia")
    texto = analisis.resumen(prep, carpeta, 10)
    assert "Análisis en Webtoon: «revisa la historia»" in texto and "Historia.md" in texto
    assert f"~{prep.tokens}" in texto and "caducan en 10 minutos" in texto
    hablado = analisis.resumen_hablado(prep)
    assert hablado.startswith("Voy a analizar") and "menos de mil tokens" in hablado and "/" not in hablado
    prep.tokens = 1177
    assert "unos mil tokens" in analisis.resumen_hablado(prep)
    prep.tokens = 4877
    assert "unos 5 mil tokens" in analisis.resumen_hablado(prep)
    opus = analisis.Opcion("claude-cli/claude-opus-5-5", "Opus 5.5", "off", True, 3700)
    assert analisis.etiqueta(opus, prep, True) == f"✓ Opus 5.5 · ~{analisis.miles(prep.tokens + 3700)} tokens"
    assert analisis.miles(20000) == "20.000"


def test_analizar_usa_solo_el_modelo_elegido_con_mas_tiempo(boveda, cfg):
    import json
    _proyecto(boveda)
    boveda.guardar_nota("nota", "Webtoon", "historia")
    prep = analisis.preparar(boveda, "Webtoon", "revisa")
    cuerpos = []

    def manejar(req):
        cuerpos.append(json.loads(req.content))
        return httpx.Response(502, json={"error": "sin cuota"})
    cliente = OpenClaw("http://openclaw:18789", "secreto", transport=httpx.MockTransport(manejar))
    opus = analisis.opciones_desde_config(cfg)[0]
    assert asyncio.run(analisis.analizar(cliente, opus, prep, cfg)) is None
    assert len(cuerpos) == 1                                          # nunca cambia de modelo solo
    c = cuerpos[0]
    assert c["modelo"] == "claude-cli/claude-opus-5-5" and c["aislado"] and c["razonamiento"] == "low"
    assert c["tiempo_max_s"] == 300 and c["max_tokens"] == 2500 and c["sistema"] == analisis.SISTEMA
    assert c["mensaje"] == prep.contexto
    assert cliente.ultimo_error == "HTTP 502 sin cuota"


def test_guardar_crea_archivo_propio_y_anota_el_diario(boveda):
    _proyecto(boveda)
    boveda.guardar_nota("la villana es la hermana", "Webtoon", "historia")
    prep = analisis.preparar(boveda, "Webtoon", "¿es viable que la villana sea la hermana?")
    opus = analisis.Opcion("claude-cli/claude-opus-5-5", "Opus 5.5", "high", True)
    r = Respuesta("## Conclusión\nEs viable.", "claude-opus-5-5", 900, 120)
    ruta = analisis.guardar(boveda, prep, r, opus)
    assert ruta.parent == boveda.carpeta_proyectos / "Webtoon" / "Analisis"
    meta = escritor.leer_frontmatter(ruta)
    assert meta["tipo"] == "analisis" and meta["modelo"] == "claude-opus-5-5"
    assert meta["tokens_entrada"] == 900 and meta["tokens_salida"] == 120 and meta["esfuerzo"] == "high"
    texto = ruta.read_text(encoding="utf-8")
    assert "[[Proyectos/Webtoon/Historia|Historia]]" in texto and "Es viable." in texto
    assert "**Modelo:** Opus 5.5 (esfuerzo alto)" in texto
    # Un segundo análisis igual no pisa el primero.
    assert analisis.guardar(boveda, prep, r, opus) != ruta
    diario = next((boveda.raiz / "Diario").glob("*.md")).read_text(encoding="utf-8")
    assert f"Análisis [[{ruta.stem}]] con Opus 5.5 (esfuerzo alto) en Webtoon" in diario
