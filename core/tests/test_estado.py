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
    e.sumar_gasto("2026-09-25", "cloudflare")
    e.sumar_gasto("2026-09-25", "cloudflare")
    assert e.gasto_del_dia("2026-09-25") == [("cloudflare", 2, 0.0)]


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
