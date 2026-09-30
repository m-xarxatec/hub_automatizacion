"""Conflictos de Syncthing: detección, análisis, unión y resolución con botones (sin internet)."""

import asyncio
from datetime import datetime

import pytest

from app.boveda import conflictos
from app.boveda.conflictos import Vigilante
from app.entradas import telegram_bot
from test_bot import SendMessage, _boton, _montar, _msg, _run, _textos, _voz

AHORA = datetime(2026, 9, 30, 10, 0, 0)
SUFIJO = ".sync-conflict-20260930-021810-UAG6XSL"


def _conflicto(carpeta, nombre, actual, copia):
    """Crea el archivo actual y su copia de conflicto como los deja Syncthing."""
    original = carpeta / nombre
    original.parent.mkdir(parents=True, exist_ok=True)
    if actual is not None:
        original.write_text(actual, encoding="utf-8")
    ruta = original.with_name(original.stem + SUFIJO + original.suffix)
    ruta.write_text(copia, encoding="utf-8")
    return conflictos.leer_nombre(ruta)


# --- detección ------------------------------------------------------------------------------
def test_leer_nombre_y_buscar_sin_las_versiones_de_syncthing(tmp_path):
    c = conflictos.leer_nombre(tmp_path / f"Historia{SUFIJO}.md")
    assert (c.original.name, c.equipo, c.fecha) == ("Historia.md", "UAG6XSL", datetime(2026, 9, 30, 2, 18, 10))
    assert conflictos.leer_nombre(tmp_path / "Historia.md") is None
    sin_ext = conflictos.leer_nombre(tmp_path / f"notas{SUFIJO}")
    assert sin_ext.original.name == "notas"
    _conflicto(tmp_path / "Proyectos" / "W", "Historia.md", "a", "b")
    _conflicto(tmp_path / ".stversions", "Historia.md", "a", "b")          # versiones viejas: no cuentan
    assert [c.original.name for c in conflictos.buscar(tmp_path)] == ["Historia.md"]


# --- análisis y unión -----------------------------------------------------------------------
FM = "---\ntipo: notas\nproyecto: W\n---\n"


def test_unir_inserta_lo_de_la_copia_en_su_lugar_y_conserva_todo():
    """Caso típico: en el móvil se editó el medio; en la PC el bot agregó un bloque al final."""
    copia = FM + "# Historia\n\nKael caza monstruos.\nDeacon pierde la moto en el capítulo 2.\n\nFin del arco.\n"
    actual = FM + "# Historia\n\nKael caza monstruos.\n\nFin del arco.\n\n## Nuevo\n\nAely es la villana.\n"
    unido, solo_c, solo_a, ambos = conflictos.unir(actual, copia)
    assert unido == (FM + "# Historia\n\nKael caza monstruos.\nDeacon pierde la moto en el capítulo 2.\n\n"
                          "Fin del arco.\n\n## Nuevo\n\nAely es la villana.\n")
    assert solo_c == ["Deacon pierde la moto en el capítulo 2."]
    assert solo_a == ["## Nuevo", "Aely es la villana."] and ambos == 0
    assert unido.count("---\n") == 2                                          # frontmatter una sola vez


def test_unir_con_el_mismo_fragmento_cambiado_en_los_dos_deja_ambas_variantes():
    unido, solo_c, solo_a, ambos = conflictos.unir("Kael mide 1,80.\nFin.\n", "Kael mide 1,90.\nFin.\n")
    assert unido == "Kael mide 1,90.\nKael mide 1,80.\nFin.\n" and ambos == 1   # la copia (más vieja) primero


def test_analizar_sugiere_segun_el_caso(tmp_path):
    nada = conflictos.analizar(_conflicto(tmp_path, "a.md", "uno\n\ndos\n", "uno\ndos\n"))
    assert nada.sugerencia == "actual" and "no tiene nada" in nada.motivo           # solo líneas en blanco
    mas = conflictos.analizar(_conflicto(tmp_path, "b.md", "uno\n", "uno\ndos\n"))
    assert mas.sugerencia == "unir" and "todo lo de la actual y 1 línea más" in mas.motivo
    ambos = conflictos.analizar(_conflicto(tmp_path, "c.md", "uno\ntres\n", "uno\ndos\n"))
    assert ambos.sugerencia == "unir" and ambos.acciones == ("unir", "actual", "copia")
    borrado = conflictos.analizar(_conflicto(tmp_path, "d.md", None, "solo aquí\n"))
    assert borrado.sugerencia == "copia" and "ya no existe" in borrado.motivo
    json_ = conflictos.analizar(_conflicto(tmp_path, "e.json", '{"a": 1}', '{"a": 2}'))
    assert json_.acciones == ("actual", "copia") and "no se puede unir" in json_.motivo


# --- resolver -------------------------------------------------------------------------------
@pytest.mark.parametrize("accion, queda", [
    ("unir", "uno\ndos\ntres\n"), ("actual", "uno\ntres\n"), ("copia", "uno\ndos\n")])
def test_resolver_respalda_las_dos_versiones_antes_de_tocar(tmp_path, accion, queda):
    c = _conflicto(tmp_path / "boveda", "Historia.md", "uno\ntres\n", "uno\ndos\n")
    carpeta = conflictos.resolver(c, accion, tmp_path / "datos" / "conflictos", AHORA)
    assert c.original.read_text(encoding="utf-8") == queda and not c.copia.exists()
    assert carpeta.name == "20260930-100000"
    assert (carpeta / "actual-Historia.md").read_text(encoding="utf-8") == "uno\ntres\n"
    assert (carpeta / c.copia.name).read_text(encoding="utf-8") == "uno\ndos\n"
    assert conflictos.resolver(c, accion, tmp_path / "datos", AHORA) is None         # ya resuelto


def test_resolver_restaura_un_original_borrado_y_no_une_lo_que_no_es_texto(tmp_path):
    c = _conflicto(tmp_path, "d.md", None, "solo aquí\n")
    conflictos.resolver(c, "copia", tmp_path / "respaldos", AHORA)
    assert c.original.read_text(encoding="utf-8") == "solo aquí\n"
    j = _conflicto(tmp_path, "e.json", '{"a": 1}', '{"a": 2}')
    with pytest.raises(ValueError):
        conflictos.resolver(j, "unir", tmp_path / "respaldos", AHORA)


def test_vigilante_solo_avisa_de_lo_estable_y_una_vez(tmp_path):
    v = Vigilante(tmp_path)
    c = _conflicto(tmp_path, "a.md", "uno\n", "uno\ndos\n")
    assert v.revisar() == []                                     # recién aparecido: puede estar a medio copiar
    (nuevo,) = v.revisar()
    v.avisada(nuevo)
    assert nuevo.copia == c.copia and v.revisar() == []          # ya avisado
    c.copia.unlink()
    assert v.revisar() == [] and v.avisadas == set()             # resuelto: se olvida


# --- en el bot ------------------------------------------------------------------------------
def _botones(mensaje):
    return [(b.text, b.callback_data) for fila in mensaje.reply_markup.inline_keyboard for b in fila]


def test_el_bot_avisa_sugiere_y_une_con_un_boton(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    carpeta = boveda.carpeta_proyectos / "W"
    c = _conflicto(carpeta, "Historia.md", "# Historia\n\nKael caza.\n\n## Nuevo\n\nAely es la villana.\n",
                   "# Historia\n\nKael caza.\nDeacon pierde la moto.\n")
    assert asyncio.run(telegram_bot.revisar_conflictos(bot, ctx)) == 0       # primera vista: espera
    assert asyncio.run(telegram_bot.revisar_conflictos(bot, ctx)) == 1
    aviso = [m for m in sesion.enviados if isinstance(m, SendMessage)][-1]
    assert aviso.chat_id == 1111 and aviso.text.startswith("⚠ Conflicto de Syncthing en Proyectos/W/Historia.md")
    assert "Solo en la copia (1 línea):\n  · Deacon pierde la moto." in aviso.text
    assert "Sugerencia: unir. Cada versión tiene algo propio" in aviso.text
    botones = _botones(aviso)
    assert [t for t, _ in botones] == ["✓ Unir", "Quedarme con la actual", "Usar la copia", "Después"]
    assert asyncio.run(telegram_bot.revisar_conflictos(bot, ctx)) == 0       # no repite el aviso
    _run(dp, bot, _boton(botones[0][1]))
    assert _textos(sesion)[-1].startswith("Listo: uní las dos versiones en Proyectos/W/Historia.md.")
    assert c.original.read_text(encoding="utf-8") == ("# Historia\n\nKael caza.\nDeacon pierde la moto.\n\n"
                                                      "## Nuevo\n\nAely es la villana.\n")
    assert not c.copia.exists() and len(list((ctx.ajustes.datos / "conflictos").iterdir())) == 1
    diario = next((boveda.raiz / "Diario").glob("*.md")).read_text(encoding="utf-8")
    assert "Conflicto de Syncthing resuelto en [[Proyectos/W/Historia|Historia]] (unir)" in diario


def test_conflictos_por_comando_voz_y_despues(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    _run(dp, bot, _msg("/conflictos"))
    assert _textos(sesion)[-1] == "No hay conflictos de Syncthing en la bóveda."
    c = _conflicto(boveda.carpeta_proyectos / "W", "Ideas.md", "uno\ndos\n", "uno\n")
    _run(dp, bot, _msg("hay conflictos?"))                               # orden fija, sin tokens
    aviso = sesion.enviados[-1]
    assert "Sugerencia: quedarme con la actual. La copia no tiene nada" in aviso.text
    assert _botones(aviso)[0][0] == "✓ Quedarme con la actual"
    _run(dp, bot, _boton(_botones(aviso)[-1][1]))                        # Después: no toca nada
    assert c.copia.exists() and "Lo dejo como está" in _textos(sesion)[-1]
    _run(dp, bot, _voz(ctx, "muéstrame los conflictos"))
    assert ctx.voz.hablados[-1].startswith("Hay un conflicto de Syncthing en Ideas. La copia no tiene nada")
    assert ctx.voz.hablados[-1].endswith("Te sugiero quedarme con la actual; elige en los botones.")


def test_el_conflicto_del_latido_se_borra_sin_preguntar(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    c = _conflicto(boveda.raiz / "_hub", "servidor.json", '{"servidor": "pc-casa"}', '{"servidor": "laptop"}')
    asyncio.run(telegram_bot.revisar_conflictos(bot, ctx))
    assert asyncio.run(telegram_bot.revisar_conflictos(bot, ctx)) == 0
    assert not c.copia.exists() and c.original.exists() and _textos(sesion) == []


def test_un_boton_viejo_o_de_otra_ruta_no_hace_nada(tmp_path, cfg, boveda):
    ctx, dp, bot, sesion = _montar(tmp_path, cfg, boveda)
    fuera = _conflicto(tmp_path / "fuera", "x.md", "a\n", "b\n")
    clave = ctx.guardar_pendiente(tipo="conflicto", copia=str(fuera.copia))
    _run(dp, bot, _boton(f"cf:actual:{clave}"), _boton("cf:actual:inexistente"))
    assert fuera.copia.exists()                                          # fuera de la bóveda: no se toca
