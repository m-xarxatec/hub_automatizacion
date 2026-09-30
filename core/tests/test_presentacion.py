"""Formato seguro y límites reales de los mensajes de Telegram."""

from app.entradas.presentacion import formato, fragmentos


def test_contenido_externo_no_inyecta_html():
    resultado = formato('## Idea\n**Kael** & <b>Aely</b>\n`x < 3`')
    assert resultado == '<b>Idea</b>\n<b>Kael</b> &amp; &lt;b&gt;Aely&lt;/b&gt;\n<code>x &lt; 3</code>'


def test_codigo_conserva_su_contenido():
    assert formato('```python\n**literal** <tag>\n```') == '<pre>**literal** &lt;tag&gt;\n</pre>'
    assert formato('```') == '```'


def test_fragmentos_respetan_utf16_y_no_pierden_contenido():
    texto = '✨😀' * 4000 + '\nfin'
    partes = fragmentos(texto)
    assert ''.join(partes) == texto
    assert all(len(p.encode('utf-16-le')) // 2 <= 3500 for p in partes)


def test_confirmacion_tiene_jerarquia_y_consulta_conserva_titulo():
    assert formato('Tarea agregada a tareas.md').startswith('<b>✅')
    assert formato('## Mi respuesta').startswith('<b>Mi respuesta</b>')
