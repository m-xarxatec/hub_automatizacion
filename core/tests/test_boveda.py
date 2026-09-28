from datetime import datetime

from app.boveda import escritor


def test_slug_portable_en_windows():
    assert escritor.slug('Villana: ¿máscara de "zorro"?') == "villana-mascara-de-zorro"
    assert escritor.slug("CON") == "nota-con"
    assert escritor.slug("   ") == "nota"
    assert escritor.slug("Año nuevo / capítulo 3") == "ano-nuevo-capitulo-3"


def test_nombre_carpeta_conserva_mayusculas_y_quita_prohibidos():
    assert escritor.nombre_carpeta("Webtoon: Oscuro") == "Webtoon Oscuro"
    assert escritor.nombre_carpeta("Mi Cómic.") == "Mi Cómic"


def test_ruta_unica_no_pisa(tmp_path):
    ahora = datetime(2026, 9, 25, 14, 38)
    a = escritor.ruta_unica(tmp_path, "Idea", ".md", ahora)
    a.write_text("x")
    b = escritor.ruta_unica(tmp_path, "Idea", ".md", ahora)
    assert a.name == "2026-09-25-1438-idea.md"
    assert b.name == "2026-09-25-1438-idea-2.md"


def test_escritura_atomica_no_deja_temporales(tmp_path):
    ruta = tmp_path / "a" / "nota.md"
    escritor.escribir_atomico(ruta, "hola")
    assert ruta.read_text() == "hola"
    assert not list(tmp_path.rglob("*.tmp"))


def test_estructura_base_y_stignore(boveda):
    for carpeta in ("00-Bandeja", "Diario", "Proyectos", "_hub/plantillas"):
        assert (boveda.raiz / carpeta).is_dir()
    assert "*.tmp" in (boveda.raiz / ".stignore").read_text()


def test_crear_proyecto_y_buscar_por_nombre_o_alias(boveda):
    nombre = boveda.crear_proyecto("Webtoon")
    carpeta = boveda.carpeta_proyectos / nombre
    assert (carpeta / "Historia" / "Personajes").is_dir()
    assert (carpeta / "_proyecto.md").exists() and (carpeta / "tareas.md").exists()
    assert boveda.buscar_proyecto("webtoon") == "Webtoon"
    indice = carpeta / "_proyecto.md"
    indice.write_text(indice.read_text().replace("aliases: []", "aliases: [cómic oscuro]"))
    assert boveda.buscar_proyecto("Comic Oscuro") == "Webtoon"
    assert boveda.crear_proyecto("WEBTOON") == "Webtoon"  # no duplica


def test_guardar_nota_en_proyecto_y_en_bandeja(boveda):
    boveda.crear_proyecto("Webtoon")
    ruta = boveda.guardar_nota("Zamael no confía en nadie", "Webtoon", tipo="historia", origen="voz")
    assert ruta == boveda.carpeta_proyectos / "Webtoon" / "Historia.md"
    boveda.guardar_nota("El templo está en ruinas", "Webtoon", tipo="historia")
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith("---\ntipo: notas\nproyecto: Webtoon\n---\n# Historia de Webtoon\n")
    assert texto.count("\n## ") == 2 and "· voz\n\nZamael no confía en nadie\n" in texto
    assert "· texto\n\nEl templo está en ruinas\n" in texto
    suelta = boveda.guardar_nota("algo sin proyecto")
    assert suelta == boveda.bandeja / "Notas.md"
    diario = list((boveda.raiz / "Diario").glob("*.md"))[0].read_text(encoding="utf-8")
    assert diario.count("\n- ") == 3
    assert "[[Proyectos/Webtoon/Historia#" in diario and "|Historia de Webtoon]]" in diario


def test_nota_aparte_crea_archivo_unico(boveda):
    boveda.crear_proyecto("Webtoon")
    a = boveda.guardar_nota("Zamael no confía en nadie", "Webtoon", tipo="historia", aparte=True)
    b = boveda.guardar_nota("Zamael no confía en nadie", "Webtoon", tipo="historia", aparte=True)
    assert a != b and a.parent == boveda.carpeta_proyectos / "Webtoon" / "Historia"
    assert a.read_text(encoding="utf-8").startswith("---\ntipo: historia\nproyecto: Webtoon")


def test_tareas(boveda):
    boveda.crear_proyecto("Webtoon")
    boveda.agregar_tarea("terminar storyboard cap 3", "Webtoon")
    boveda.agregar_tarea("exportar páginas", "Webtoon")
    assert boveda.tareas_abiertas("Webtoon") == ["terminar storyboard cap 3", "exportar páginas"]
    boveda.agregar_tarea("sin proyecto")
    assert boveda.tareas_abiertas(None) == ["sin proyecto"]
