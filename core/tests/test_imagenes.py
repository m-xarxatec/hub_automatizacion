"""Día 4: proveedores de imágenes, cadena con failover y guardado en la bóveda.

Sin internet ni cuota: Cloudflare y tensor.art se simulan con httpx.MockTransport y la
firma RSA de tensor.art se verifica con la clave pública de una clave de prueba.
"""

import asyncio
import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.acciones import personajes
from app.acciones.imagenes import GeneradorImagenes, referente
from app.boveda import escritor
from app.estado.db import Estado
from app.proveedores.cadena import (CadenaImagenes, Cortacircuitos, ErrorProveedor, Imagen,
                                    SinProveedores, crear_cadena, extension_de)
from app.proveedores.cloudflare_img import CloudflareImagen
from app.proveedores.tensorart_img import TensorArtImagen, firmar
from app.router.reglas import renombrar_imagen

JPEG = b"\xff\xd8\xff\xe0-imagen-de-prueba"
PNG = b"\x89PNG\r\n-imagen-de-prueba"
CF_ENTORNO = {"CLOUDFLARE_ACCOUNT_ID": "cuenta1", "CLOUDFLARE_API_TOKEN": "tok"}


def _correr(coro):
    return asyncio.run(coro)


class ProveedorFalso:
    def __init__(self, nombre, resultado=None, error=None, falta=None):
        self.nombre, self.resultado, self.error, self.falta = nombre, resultado, error, falta
        self.llamadas = 0

    def falta_configurar(self):
        return self.falta

    async def generar(self, prompt):
        self.llamadas += 1
        if self.error:
            raise self.error
        return self.resultado

    async def diagnosticar(self):
        return "ok"


def test_extension_por_contenido():
    assert extension_de(JPEG) == ".jpg" and extension_de(PNG) == ".png"
    assert extension_de(b"RIFF1234WEBPxx") == ".webp"


# --- cadena ------------------------------------------------------------------------
def test_cadena_salta_sin_configurar_y_usa_el_siguiente_si_falla():
    sin_clave = ProveedorFalso("chatgpt", falta="día 5")
    roto = ProveedorFalso("cloudflare", error=ErrorProveedor("HTTP 429"))
    bueno = ProveedorFalso("tensorart", Imagen(PNG, ".png", "tensorart", "m"))
    img = _correr(CadenaImagenes([sin_clave, roto, bueno]).generar("gato"))
    assert img.proveedor == "tensorart" and roto.llamadas == 1 and sin_clave.llamadas == 0


def test_cadena_sin_proveedores_reune_los_motivos():
    cadena = CadenaImagenes([ProveedorFalso("a", falta="sin clave"),
                             ProveedorFalso("b", error=RuntimeError("explotó"))])
    with pytest.raises(SinProveedores) as e:
        _correr(cadena.generar("gato"))
    assert e.value.fallos == [("a", "sin clave"), ("b", "error inesperado: explotó")]
    diag = _correr(cadena.diagnosticar())
    assert diag == [("a", "sin configurar: sin clave"), ("b", "ok")]



# --- cortacircuitos ----------------------------------------------------------------
class Reloj:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def _cadena_con_corte(tmp_path, *proveedores):
    reloj = Reloj()
    corte = Cortacircuitos(Estado(tmp_path / "hub.sqlite3"), fallos=3, espera_min=5, reloj=reloj)
    return CadenaImagenes(list(proveedores), corte), reloj


def test_cortacircuitos_pausa_tras_tres_fallos_y_salta_al_siguiente(tmp_path):
    roto = ProveedorFalso("chatgpt", error=ErrorProveedor("HTTP 502"))
    bueno = ProveedorFalso("cloudflare", Imagen(PNG, ".png", "cloudflare", "m"))
    cadena, reloj = _cadena_con_corte(tmp_path, roto, bueno)
    for _ in range(3):
        _correr(cadena.generar("gato"))
    assert roto.llamadas == 3
    assert _correr(cadena.generar("gato")).proveedor == "cloudflare"
    assert roto.llamadas == 3                       # en pausa: ni se llama
    reloj.t += 5 * 60 + 1                           # pasa la pausa: se prueba una vez
    _correr(cadena.generar("gato"))
    assert roto.llamadas == 4
    _correr(cadena.generar("gato"))
    assert roto.llamadas == 4                       # volvió a fallar: otra pausa


def test_cortacircuitos_da_el_motivo_y_se_reinicia_con_un_exito(tmp_path):
    prov = ProveedorFalso("chatgpt", error=ErrorProveedor("HTTP 502"))
    cadena, reloj = _cadena_con_corte(tmp_path, prov)
    for _ in range(3):
        with pytest.raises(SinProveedores):
            _correr(cadena.generar("gato"))
    with pytest.raises(SinProveedores) as e:
        _correr(cadena.generar("gato"))
    assert "en pausa hasta las" in e.value.fallos[0][1] and "HTTP 502" in e.value.fallos[0][1]
    assert "en pausa" in _correr(cadena.diagnosticar())[0][1]
    reloj.t += 5 * 60 + 1
    prov.error, prov.resultado = None, Imagen(PNG, ".png", "chatgpt", "m")
    _correr(cadena.generar("gato"))
    assert cadena.cortacircuitos.estado.estado_proveedor("chatgpt") == (0, 0.0, "")
    prov.error = ErrorProveedor("HTTP 502")         # un fallo suelto ya no pausa
    with pytest.raises(SinProveedores):
        _correr(cadena.generar("gato"))
    assert cadena.cortacircuitos.en_pausa("chatgpt") is None


def test_cortacircuitos_no_cuenta_la_falta_de_configuracion(tmp_path):
    cadena, _ = _cadena_con_corte(tmp_path, ProveedorFalso("chatgpt", falta="sin token"))
    for _ in range(4):
        with pytest.raises(SinProveedores):
            _correr(cadena.generar("gato"))
    assert cadena.cortacircuitos.estado.estado_proveedor("chatgpt")[0] == 0


def test_crear_cadena_usa_el_cortacircuitos_de_config(cfg, tmp_path):
    assert crear_cadena(cfg, {}).cortacircuitos is None
    corte = crear_cadena(cfg, {}, estado=Estado(tmp_path / "hub.sqlite3")).cortacircuitos
    assert (corte.umbral, corte.espera_s) == (3, 300)

def test_crear_cadena_respeta_orden_y_activo(cfg):
    # MVP: solo la suscripción de ChatGPT; cloudflare y tensorart desactivados en config.yaml.
    assert [p.nombre for p in crear_cadena(cfg, {}).proveedores] == ["chatgpt"]
    for opciones in cfg["proveedores"]["imagen"]:
        opciones["activo"] = True
    assert [p.nombre for p in crear_cadena(cfg, {}).proveedores] == ["chatgpt", "cloudflare", "tensorart"]
    cfg["proveedores"]["imagen"][1]["activo"] = False
    cfg["proveedores"]["imagen"].append({"nombre": "inventado"})
    assert [p.nombre for p in crear_cadena(cfg, {}).proveedores] == ["chatgpt", "tensorart"]


# --- Cloudflare ------------------------------------------------------------------------
def _cloudflare(manejar, entorno=CF_ENTORNO):
    return CloudflareImagen({"modelo": "flux-1-schnell", "pasos": 20}, entorno,
                            transport=httpx.MockTransport(manejar))


def test_cloudflare_genera_jpeg():
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return httpx.Response(200, json={"result": {"image": base64.b64encode(JPEG).decode()},
                                         "success": True})
    img = _correr(_cloudflare(manejar).generar("a fox mask"))
    assert img.datos == JPEG and img.extension == ".jpg" and img.proveedor == "cloudflare"
    req = pedidos[0]
    assert req.url.path == "/client/v4/accounts/cuenta1/ai/run/@cf/black-forest-labs/flux-1-schnell"
    assert req.headers["Authorization"] == "Bearer tok"
    assert json.loads(req.content) == {"prompt": "a fox mask", "steps": 8}  # tope de 8 pasos


def test_cloudflare_errores_legibles():
    cuota = _cloudflare(lambda r: httpx.Response(429, json={"errors": [{"message": "daily limit"}]}))
    with pytest.raises(ErrorProveedor, match="HTTP 429: daily limit"):
        _correr(cuota.generar("x"))
    basura = _cloudflare(lambda r: httpx.Response(200, json={"result": {"image": "%%%"}}))
    with pytest.raises(ErrorProveedor, match="sin imagen"):
        _correr(basura.generar("x"))

    def sin_red(r):
        raise httpx.ConnectError("caído")
    with pytest.raises(ErrorProveedor, match="sin conexión"):
        _correr(_cloudflare(sin_red).generar("x"))
    assert "faltan" in _cloudflare(sin_red, entorno={}).falta_configurar()


def test_cloudflare_diagnostico_no_genera():
    rutas = []

    def manejar(req):
        rutas.append(req.url.path)
        return httpx.Response(200, json={"result": {"status": "active"}})
    assert _correr(_cloudflare(manejar).diagnosticar()) == "ok: token active"
    assert rutas == ["/client/v4/user/tokens/verify"]
    rechazo = _cloudflare(lambda r: httpx.Response(401, json={"errors": [{"message": "Invalid"}]}))
    assert "token rechazado" in _correr(rechazo.diagnosticar())


# --- tensor.art -------------------------------------------------------------------------
@pytest.fixture
def clave_rsa(tmp_path):
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ruta = tmp_path / "tensorart_private_key.pem"
    ruta.write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    return clave, ruta


def _verificar(cabecera, metodo, ruta, cuerpo, publica):
    tipo, _, campos = cabecera.partition(" ")
    datos = dict(c.split("=", 1) for c in campos.split(","))
    texto = f"{metodo}\n{ruta}\n{datos['timestamp']}\n{datos['nonce_str']}\n{cuerpo}"
    publica.verify(base64.b64decode(datos["signature"]), texto.encode(), padding.PKCS1v15(), hashes.SHA256())
    return tipo, datos


def test_firma_tams_formato_oficial(clave_rsa):
    clave, ruta = clave_rsa
    cabecera = firmar("post", "/v1/jobs", '{"a": 1}', "app9", ruta.read_bytes(), timestamp="100", nonce="n1")
    tipo, datos = _verificar(cabecera, "POST", "/v1/jobs", '{"a": 1}', clave.public_key())
    assert tipo == "TAMS-SHA256-RSA" and datos["app_id"] == "app9" and datos["timestamp"] == "100"


def _tensorart(manejar, ruta_clave, opciones=None):
    entorno = {"TENSORART_ENDPOINT": "ap-east-1.tensorart.cloud", "TENSORART_APP_ID": "app9",
               "TENSORART_PRIVATE_KEY_PATH": str(ruta_clave)}
    p = TensorArtImagen(opciones or {"modelo_id": "123", "pasos": 15}, entorno,
                        transport=httpx.MockTransport(manejar))
    p.espera_s = 0
    return p


def test_tensorart_crea_espera_y_descarga(clave_rsa):
    clave, ruta = clave_rsa
    estados = iter(["RUNNING", "SUCCESS"])
    vistos = []

    def manejar(req):
        vistos.append((req.method, req.url.path))
        if req.url.host == "cdn.tensor.art":
            return httpx.Response(200, content=PNG)
        cuerpo = req.content.decode()
        _verificar(req.headers["Authorization"], req.method, req.url.path, cuerpo, clave.public_key())
        if req.method == "POST":
            datos = json.loads(cuerpo)
            difusion = datos["stages"][1]["diffusion"]
            assert difusion["sd_model"] == "123" and difusion["prompts"] == [{"text": "a fox"}]
            return httpx.Response(200, json={"job": {"id": "j1", "status": "CREATED"}})
        estado = next(estados)
        exito = {"images": [{"url": "https://cdn.tensor.art/j1.png"}]} if estado == "SUCCESS" else None
        return httpx.Response(200, json={"job": {"id": "j1", "status": estado, "successInfo": exito}})

    img = _correr(_tensorart(manejar, ruta).generar("a fox"))
    assert img.datos == PNG and img.extension == ".png" and img.proveedor == "tensorart"
    assert vistos == [("POST", "/v1/jobs"), ("GET", "/v1/jobs/j1"), ("GET", "/v1/jobs/j1"),
                      ("GET", "/j1.png")]


def test_tensorart_trabajo_fallido_y_configuracion(clave_rsa, tmp_path):
    _, ruta = clave_rsa

    def manejar(req):
        if req.method == "POST":
            return httpx.Response(200, json={"job": {"id": "j2"}})
        return httpx.Response(200, json={"job": {"status": "FAILED", "failedInfo": {"reason": "NSFW"}}})
    with pytest.raises(ErrorProveedor, match="trabajo failed: NSFW"):
        _correr(_tensorart(manejar, ruta).generar("x"))
    assert "clave privada" in _tensorart(manejar, tmp_path / "no.pem").falta_configurar()
    assert "faltan" in TensorArtImagen({"modelo_id": "1"}, {}).falta_configurar()


def test_tensorart_diagnostico_pide_solo_el_costo(clave_rsa):
    _, ruta = clave_rsa
    rutas = []

    def manejar(req):
        rutas.append(req.url.path)
        return httpx.Response(200, json={"credits": "0.8"})
    assert "ok: firma aceptada" in _correr(_tensorart(manejar, ruta).diagnosticar())
    assert rutas == ["/v1/jobs/credits"]
    rechazo = _tensorart(lambda r: httpx.Response(401, text="bad signature"), ruta)
    assert "HTTP 401" in _correr(rechazo.diagnosticar())


# --- guardado en la bóveda ---------------------------------------------------------------
class LLMFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta

    async def chat_json(self, sistema, usuario, esquema):
        return self.respuesta


def _generador(boveda, llm=None, proveedor=None):
    proveedor = proveedor or ProveedorFalso("cloudflare", Imagen(JPEG, ".jpg", "cloudflare", "flux"))
    return GeneradorImagenes(boveda, CadenaImagenes([proveedor]), llm)


def test_imagen_y_nota_hermana_en_el_proyecto(boveda):
    boveda.crear_proyecto("Webtoon")
    llm = LLMFalso({"prompt": "fox mask villain, rainy neon city"})
    r = _correr(_generador(boveda, llm).crear("la villana con máscara de zorro", "Webtoon"))
    assert r.imagen.parent == boveda.carpeta_proyectos / "Webtoon" / "Imagenes"
    assert r.imagen.suffix == ".jpg" and r.imagen.read_bytes() == JPEG
    assert r.imagen.name == "villana1.jpg" and r.nota == r.imagen.with_suffix(".md")
    meta = escritor.leer_frontmatter(r.nota)
    assert meta["tipo"] == "imagen_ia" and meta["proveedor"] == "cloudflare" and meta["imagen"] == r.imagen.name
    texto = r.nota.read_text(encoding="utf-8")
    assert f"![[{r.imagen.name}]]" in texto and "**Prompt:** fox mask villain" in texto
    diario = next((boveda.raiz / "Diario").glob("*.md")).read_text(encoding="utf-8")
    assert f"Imagen [[{r.nota.stem}]] (cloudflare) en Webtoon" in diario


def test_sin_llm_o_respuesta_mala_usa_la_idea(boveda):
    for llm in (None, LLMFalso(None), LLMFalso({"prompt": "  "})):
        assert _correr(_generador(boveda, llm).mejorar_prompt(" templo en ruinas ")) == "templo en ruinas"


def test_sin_proyecto_va_a_la_bandeja_y_no_pisa_notas(boveda):
    gen = _generador(boveda)
    r1 = _correr(gen.crear("templo", None))
    r2 = _correr(gen.crear("templo", None))
    assert r1.imagen.parent == boveda.bandeja and r1.imagen != r2.imagen and r1.nota != r2.nota
    assert (r1.imagen.name, r2.imagen.name) == ("templo1.jpg", "templo2.jpg")


@pytest.mark.parametrize("idea, nombre", [
    ("Crea una chica anime elfa pálida con los ojos rojos", "elfa"),
    ("Muy bien.. Ahora vas a crear a la misma elfa pero con un hacha de batalla", "elfa"),
    ("Creo una imagen en estilo álimen de un mercenario calvo con barba", "mercenario"),
    ("un zorro con máscara de kitsune, paleta cobre", "zorro"),
    ("una chica en la playa", "chica"),
    ("quiero que me hagas una imagen", "imagen"),
])
def test_referente_es_una_palabra_simple(idea, nombre):
    assert referente(idea) == nombre


def test_numeracion_sigue_la_mas_alta_y_personaje_con_ficha(boveda):
    boveda.crear_proyecto("Webtoon")
    personajes.crear_o_anotar(boveda, "Webtoon", "Zamael", "Villano.", "texto")
    gen = _generador(boveda)
    carpeta = gen.carpeta("Webtoon")
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "Elfa4.png").write_bytes(PNG)   # sin distinguir mayúsculas, como Windows
    assert _correr(gen.crear("otra elfa guerrera", "Webtoon")).imagen.name == "elfa5.jpg"
    assert _correr(gen.crear("Zamael bajo la lluvia", "Webtoon")).imagen.name == "zamael1.jpg"


def test_renombrar_la_ultima_imagen(boveda):
    boveda.crear_proyecto("Webtoon")
    gen = _generador(boveda)
    _correr(gen.crear("un templo", "Webtoon"))
    r = _correr(gen.crear("una elfa pálida", "Webtoon"))
    assert gen.ultima("Webtoon") == r.nota
    nueva = gen.renombrar(r.nota, "Aeli")
    assert nueva.name == "aeli1.md" and not r.nota.exists() and not r.imagen.exists()
    assert (nueva.parent / "aeli1.jpg").read_bytes() == JPEG
    texto = nueva.read_text(encoding="utf-8")
    assert "![[aeli1.jpg]]" in texto and "\n# aeli1\n" in texto
    assert escritor.leer_frontmatter(nueva)["imagen"] == "aeli1.jpg"
    diario = next((boveda.raiz / "Diario").glob("*.md")).read_text(encoding="utf-8")
    assert "Imagen elfa1 renombrada a [[aeli1]]" in diario
    assert gen.renombrar(nueva, "aeli") == nueva   # ya se llama así: no cambia nada
    assert gen.ultima(None) is None


@pytest.mark.parametrize("texto, nombre", [
    ("La imagen que se acaba de crear será el personaje Aeli.", "Aeli"),
    ("la imagen que acabas de generar es Kira", "Kira"),
    ("Muy bien, la última imagen será el personaje zamael", "zamael"),
    ("Renombra la imagen como kira", "kira"),
    ("Llama a la imagen Ana Luz", "Ana Luz"),
    ("la imagen es muy bonita", None),
    ("esta imagen es la elfa", None),
    ("crea una imagen de una elfa", None),
])
def test_regla_renombrar_imagen(texto, nombre):
    assert renombrar_imagen(texto) == nombre


def test_si_falla_todo_no_se_escribe_nada(boveda):
    gen = _generador(boveda, proveedor=ProveedorFalso("cloudflare", error=ErrorProveedor("HTTP 500")))
    with pytest.raises(SinProveedores):
        _correr(gen.crear("templo", None))
    assert not list(boveda.bandeja.glob("*.jpg"))


# --- ChatGPT por OpenClaw (día 5) ----------------------------------------------------------
PNG = b"\x89PNG\r\n\x1a\n-imagen"


def _chatgpt(manejar, token="secreto", opciones=None):
    from app.proveedores.chatgpt_img import ChatGPTImagen
    return ChatGPTImagen(opciones or {"modelo": "gpt-image-2", "calidad": "low", "tamano": "1024x1536"},
                         {"OPENCLAW_URL": "http://openclaw:18789", "OPENCLAW_GATEWAY_TOKEN": token},
                         transport=httpx.MockTransport(manejar))


def test_chatgpt_genera_por_el_puente():
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return httpx.Response(200, json={"imagen": base64.b64encode(PNG).decode(), "mime": "image/png",
                                         "proveedor": "openai", "modelo": "gpt-image-2"})
    img = _correr(_chatgpt(manejar).generar("zorro con máscara"))
    assert img.datos == PNG and img.extension == ".png"
    assert img.proveedor == "chatgpt" and img.modelo == "gpt-image-2"
    req = pedidos[0]
    assert req.url.path == "/hub/imagen" and req.headers["authorization"] == "Bearer secreto"
    assert json.loads(req.content) == {"prompt": "zorro con máscara", "modelo": "openai/gpt-image-2",
                                       "calidad": "low", "tamano": "1024x1536"}


@pytest.mark.parametrize("respuesta, motivo", [
    (httpx.Response(502, json={"error": "usage limit reached"}), "HTTP 502: usage limit"),
    (httpx.Response(200, json={"imagen": "no-es-base64!"}), "sin imagen válida"),
    (httpx.Response(200, json={"imagen": ""}), "imagen vacía"),
])
def test_chatgpt_fallos_son_legibles(respuesta, motivo):
    with pytest.raises(ErrorProveedor, match=motivo):
        _correr(_chatgpt(lambda req: respuesta).generar("x"))


def test_chatgpt_sin_red_y_sin_token():
    def caido(req):
        raise httpx.ConnectError("no")
    with pytest.raises(ErrorProveedor, match="no responde"):
        _correr(_chatgpt(caido).generar("x"))
    assert _chatgpt(caido, token="").falta_configurar()


@pytest.mark.parametrize("estado, texto", [(400, "ok:"), (401, "rechaza el token"), (404, "falta el plugin")])
def test_chatgpt_diagnostico_sin_gastar(estado, texto):
    pedidos = []

    def manejar(req):
        pedidos.append(json.loads(req.content))
        return httpx.Response(estado, json={"error": "falta prompt"})
    assert texto in _correr(_chatgpt(manejar).diagnosticar())
    assert pedidos == [{}]   # petición vacía: no genera nada
