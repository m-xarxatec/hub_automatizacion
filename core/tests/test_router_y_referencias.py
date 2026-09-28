from app.acciones import referencias
from app.router import reglas
from app.router.cascada import Router


def test_reglas_acciones():
    assert reglas.decidir("tengo que terminar el storyboard").accion == "tarea"
    assert reglas.decidir("genera una imagen de Zamael bajo la lluvia").accion == "imagen"
    assert reglas.decidir("¿es viable que la villana sea su hermana?").accion == "analisis"
    d = reglas.decidir("la villana usa una máscara de zorro")
    assert d.accion == "nota" and d.confianza < 0.5 and d.tipo == "historia"
    assert reglas.decidir("se me ocurrió que la villana tenga un zorro").tipo == "idea"


def test_referencia_de_personaje():
    d = reglas.decidir("Oye, esta imagen quiero que sea una referencia para el personaje (zamael)",
                       tiene_imagen=True)
    assert d.accion == "referencia_personaje" and d.extra["personaje"] == "zamael"
    d = reglas.decidir("referencia para Zamael", tiene_imagen=True)
    assert d.extra["personaje"] == "Zamael"
    assert reglas.decidir("referencia de iluminación", tiene_imagen=True).accion == "referencia"
    assert reglas.decidir("", tiene_imagen=True).accion == "referencia"


def test_niveles(cfg, tmp_path):
    r = Router(cfg, tmp_path / "sin-modelo")
    assert r.clasificador is None
    assert r.nivel(reglas.Decision("tarea", 0.85)) == "ejecutar"
    assert r.nivel(reglas.Decision("consulta", 0.60)) == "confirmar"
    assert r.nivel(reglas.Decision("nota", 0.45)) == "preguntar"


def test_insertar_referencia_en_personaje(boveda):
    boveda.crear_proyecto("Webtoon")
    nota = referencias.crear_personaje(boveda, "Webtoon", "zamael")
    assert nota.name == "Zamael.md"
    hallado = referencias.buscar_personaje(boveda, "ZAMAEL")
    assert hallado == ("Webtoon", nota)
    img1 = referencias.guardar_imagen(boveda, "Webtoon", b"\x89PNG", ".png", "Zamael")
    img2 = referencias.guardar_imagen(boveda, "Webtoon", b"\x89PNG", ".png", "Zamael")
    referencias.insertar_en_personaje(nota, img1)
    referencias.insertar_en_personaje(nota, img2)
    referencias.insertar_en_personaje(nota, img2)  # no duplica
    texto = nota.read_text(encoding="utf-8")
    assert texto.count(f"![[{img1.name}]]") == 1 and texto.count(f"![[{img2.name}]]") == 1
    assert texto.index("## Referencias visuales") < texto.index(img1.name) < texto.index(img2.name)
    assert img1.parent.name == "Referencias"


def test_insertar_respeta_secciones_siguientes(boveda, tmp_path):
    nota = tmp_path / "Kira.md"
    nota.write_text("# Kira\n\n## Referencias visuales\n\n![[a.png]]\n\n## Notas\n\ntexto\n")
    referencias.insertar_en_personaje(nota, tmp_path / "b.png")
    assert nota.read_text() == ("# Kira\n\n## Referencias visuales\n\n![[a.png]]\n![[b.png]]\n\n"
                                "## Notas\n\ntexto\n")
    sin_seccion = tmp_path / "Leo.md"
    sin_seccion.write_text("# Leo\n")
    referencias.insertar_en_personaje(sin_seccion, tmp_path / "c.png")
    assert sin_seccion.read_text() == "# Leo\n\n## Referencias visuales\n\n![[c.png]]\n"


def test_personaje_mencionado_exige_nombre_con_mayuscula_y_uno_solo(boveda):
    from app.acciones import personajes, referencias
    boveda.crear_proyecto("Webtoon")
    referencias.crear_personaje(boveda, "Webtoon", "Luz")
    referencias.crear_personaje(boveda, "Webtoon", "Zamael")
    assert personajes.mencionado(boveda, "Webtoon", "Luz odia la lluvia").stem == "Luz"
    assert personajes.mencionado(boveda, "Webtoon", "la luz del templo es roja") is None
    assert personajes.mencionado(boveda, "Webtoon", "Zamael y Luz pelean") is None   # dos: no se elige
    assert personajes.mencionado(boveda, "Webtoon", "Zamaeles") is None
