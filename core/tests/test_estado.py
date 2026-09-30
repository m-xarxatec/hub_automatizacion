import os
import time

from app.estado import latido, limpieza
from app.estado.db import Estado


def test_latido_detecta_otro_equipo(tmp_path):
    ahora = time.time()
    latido.escribir(tmp_path, "pc-casa", ahora)
    assert latido.conflicto(tmp_path, "pc-casa", 180, ahora + 10) is None
    assert "pc-casa" in latido.conflicto(tmp_path, "laptop", 180, ahora + 10)
    assert latido.conflicto(tmp_path, "laptop", 180, ahora + 600) is None


def test_cada_equipo_late_en_su_archivo_y_se_leen_todos(tmp_path):
    """Un archivo por equipo: nadie escribe en el del otro, así Syncthing no crea copias de conflicto."""
    import json
    ahora = time.time()
    latido.escribir(tmp_path, "pc-casa", ahora)
    latido.escribir(tmp_path, "laptop", ahora - 500)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["servidor-laptop.json", "servidor-pc-casa.json"]
    assert latido.leer(tmp_path)["servidor"] == "pc-casa"                     # el más reciente
    assert "pc-casa" in latido.conflicto(tmp_path, "laptop", 180, ahora + 10)
    assert latido.conflicto(tmp_path, "pc-casa", 180, ahora + 10) is None      # el de la laptop es viejo
    # El archivo anterior (código viejo en el otro equipo) también cuenta; las copias de conflicto, no.
    (tmp_path / "servidor.json").write_text(json.dumps({"servidor": "laptop", "epoch": ahora}), encoding="utf-8")
    (tmp_path / "servidor.sync-conflict-20260930-021810-YEYNFXT.json").write_text(
        json.dumps({"servidor": "tablet", "epoch": ahora}), encoding="utf-8")
    assert "laptop" in latido.conflicto(tmp_path, "pc-casa", 180, ahora + 10)
    assert latido.conflicto(tmp_path, "laptop", 180, ahora + 10).startswith("El equipo 'pc-casa'")
    (tmp_path / "servidor-roto.json").write_text("{no es json", encoding="utf-8")
    assert len(latido.leer_todos(tmp_path)) == 3                              # el roto se ignora


def test_limpieza_por_antiguedad(tmp_path):
    datos, boveda = tmp_path / "datos", tmp_path / "Boveda"
    viejo = datos / "tmp" / "conversion.wav"
    nuevo = datos / "tmp" / "reciente.wav"
    resto = boveda / "Proyectos" / ".nota.md.tmp"
    nota = boveda / "Proyectos" / "nota.md"
    for p in (viejo, nuevo, resto, nota):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    hace_dos_dias = time.time() - 2 * 86400
    for p in (viejo, resto, nota):
        os.utime(p, (hace_dos_dias, hace_dos_dias))
    cfg = {"temp_dir_horas": 24, "temporales_boveda_horas": 1}
    simulados = limpieza.limpiar(datos, boveda, cfg, simular=True)
    assert set(simulados) == {viejo, resto} and viejo.exists()
    limpieza.limpiar(datos, boveda, cfg)
    assert not viejo.exists() and not resto.exists()
    assert nuevo.exists() and nota.exists()  # las notas nunca se tocan


def test_estado_sqlite(tmp_path):
    e = Estado(tmp_path / "hub.sqlite3")
    assert e.proyecto_activo(1) is None
    e.fijar_proyecto(1, "Webtoon")
    assert e.proyecto_activo(1) == "Webtoon"
    s1 = e.sesion(1)
    assert e.nueva_sesion(1) != s1



def test_uso_de_modelos_por_dia_funcion_y_modelo(tmp_path):
    e = Estado(tmp_path / "hub.sqlite3")
    assert e.primer_dia_de_uso() is None and e.uso() == []
    e.sumar_uso("2026-09-29", "interprete", "gpt-6-sol", 700, 70)
    e.sumar_uso("2026-09-30", "interprete", "gpt-6-sol", 650, 60)
    e.sumar_uso("2026-09-30", "interprete", "gpt-6-sol", 600, 50)
    e.sumar_uso("2026-09-30", "analisis", "claude-opus-5-5", 540, 900, estimada=True)
    e.sumar_uso("2026-09-30", "imagen", "gpt-image-2")
    assert e.primer_dia_de_uso() == "2026-09-29"
    # De más a menos tokens; las imágenes (sin tokens) al final.
    assert e.uso("2026-09-30", "2026-09-30") == [
        ("analisis", "claude-opus-5-5", 1, 540, 900, 1), ("interprete", "gpt-6-sol", 2, 1250, 110, 0),
        ("imagen", "gpt-image-2", 1, 0, 0, 0)]
    assert e.uso(por=("modelo",))[0] == ("gpt-6-sol", 3, 1950, 180, 0)       # sin límite de fechas


def test_historial_de_consulta(tmp_path):
    e = Estado(tmp_path / "hub.sqlite3")
    sesion = e.sesion(1)
    for i in range(4):
        e.agregar_vuelta(sesion, f"p{i}", f"r{i}", guardar=6)
    # Solo quedan los últimos 6 mensajes, del más antiguo al más nuevo
    assert e.historial(sesion) == [("user", "p1"), ("assistant", "r1"), ("user", "p2"),
                                   ("assistant", "r2"), ("user", "p3"), ("assistant", "r3")]
    # Lo viejo no cuenta
    e.cx.execute("UPDATE conversacion SET creado = creado - 13 * 3600")
    assert e.historial(sesion) == []
    # /nuevo borra la sesión anterior
    e.agregar_vuelta(sesion, "a", "b")
    nueva = e.nueva_sesion(1)
    assert nueva != sesion and e.historial(nueva) == []
    assert e.cx.execute("SELECT COUNT(*) FROM conversacion").fetchone()[0] == 0


def test_preferencias_por_chat(tmp_path):
    e = Estado(tmp_path / "hub.sqlite3")
    assert e.preferencia(1, "modelo_analisis") is None
    e.fijar_preferencia(1, "modelo_analisis", "openai/gpt-6-sol")
    e.fijar_preferencia(1, "modelo_analisis", "claude-cli/claude-sonnet-5")
    assert e.preferencia(1, "modelo_analisis") == "claude-cli/claude-sonnet-5"
    assert e.preferencia(2, "modelo_analisis") is None
