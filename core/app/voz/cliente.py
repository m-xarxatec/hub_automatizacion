"""Cliente del servicio de voz local (contenedor `voz`, sin APIs externas).

Paso A (hecho): transcribir notas de voz de Telegram con faster-whisper.
Paso C (hecho): hablar() con Kokoro para responder con voz (decisión 9: si el usuario habla,
el bot responde solo con voz, con frases cortas y sin leer rutas).
El audio crudo no se guarda en ningún lado: el servicio lo borra al transcribir.
"""

from __future__ import annotations

import re

import httpx

# Lo que se lee en voz alta: sin rutas ni listas largas.
MAX_HABLADO = 350
_RUTA_ENTRE_PARENTESIS = re.compile(r"\s*\([^()]*\.md\)")
_RUTA = re.compile(r"(?:\S+/)*(?P<archivo>[^\s/]+)\.(?:md|png|jpe?g|webp)\b")
# "Personaje Kira creado en Kira": el nombre propio (con mayúscula) ya se dijo; sobra el archivo.
_RUTA_TRAS_NOMBRE = re.compile(
    r"(?P<nombre>\b[A-ZÁÉÍÓÚÑ]\w+\b)(?P<medio>[^.\n]*?)(?:\s+(?:en|a)|:)\s+(?P=nombre)\b")


def para_hablar(texto: str) -> str:
    """Adapta un mensaje del bot para leerlo: 'Nota (idea) agregada a Proyectos/W/Ideas.md' ->
    'Nota agregada a Ideas'. Las listas largas se cortan."""
    t = _RUTA_ENTRE_PARENTESIS.sub("", texto)
    # Un archivo con fecha ("2026-09-27-mercado") no se lee: queda "guardada en un archivo propio".
    t = _RUTA.sub(lambda m: "" if re.match(r"\d{4}-\d\d-\d\d", m.group("archivo")) else m.group("archivo"), t)
    # "Personaje Kira creado en Kira" -> "Personaje Kira creado"
    t = _RUTA_TRAS_NOMBRE.sub(lambda m: m.group("nombre") + m.group("medio"), t)
    t = re.sub(r"\s*\((?:idea|historia|produccion|dialogo|general)\)", "", t)
    t = re.sub(r"[«»*_`]", "", t)
    t = re.sub(r"\s+", " ", t.replace("\n", ". ")).strip()
    t = re.sub(r"(?:\.\s*){2,}", ". ", t).replace(":.", ":").rstrip(" :")
    if len(t) > MAX_HABLADO:
        corte = t.rfind(". ", 0, MAX_HABLADO)
        t = (t[:corte + 1] if corte > 80 else t[:MAX_HABLADO].rsplit(" ", 1)[0]) + " Y hay más, míralo por escrito."
    return t


class ErrorVoz(Exception):
    """El servicio de voz no respondió o no pudo transcribir; el mensaje es legible."""


class ClienteVoz:
    def __init__(self, url: str, timeout: float = 120, vocabulario: str = "",
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = url.rstrip("/")
        self.vocabulario = vocabulario.strip()  # pista de ortografía para Whisper
        self.timeout = timeout
        self._transport = transport  # para pruebas con httpx.MockTransport

    async def transcribir(self, audio: bytes, idioma: str = "es") -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as cli:
                params = {"idioma": idioma}
                if self.vocabulario:
                    params["pista"] = self.vocabulario
                resp = await cli.post(f"{self.url}/transcribir", params=params, content=audio,
                                      headers={"Content-Type": "application/octet-stream"})
        except httpx.HTTPError as e:
            raise ErrorVoz(f"el servicio de voz no responde ({type(e).__name__})") from e
        if resp.status_code != 200:
            try:
                detalle = resp.json().get("detail", "")
            except ValueError:
                detalle = resp.text[:200]
            raise ErrorVoz(detalle or f"error {resp.status_code} del servicio de voz")
        try:
            return str(resp.json().get("texto", "")).strip()
        except ValueError as e:
            raise ErrorVoz("respuesta inválida del servicio de voz") from e

    async def hablar(self, texto: str) -> bytes:
        """Texto -> nota de voz OGG/Opus (Kokoro, local)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as cli:
                resp = await cli.post(f"{self.url}/hablar", json={"texto": texto})
        except httpx.HTTPError as e:
            raise ErrorVoz(f"el servicio de voz no responde ({type(e).__name__})") from e
        if resp.status_code != 200 or not resp.content.startswith(b"OggS"):
            raise ErrorVoz(f"no se pudo generar la voz (error {resp.status_code})")
        return resp.content

    async def estado(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=3, transport=self._transport) as cli:
                datos = (await cli.get(f"{self.url}/salud")).json()
        except (httpx.HTTPError, ValueError):
            return "sin respuesta"
        cargado = "listo" if datos.get("cargado") else "cargando el modelo"
        habla = "con voz" if datos.get("voz_cargada") else "sin voz de respuesta"
        return f"{cargado} (whisper {datos.get('modelo', '?')}, {datos.get('dispositivo', '?')}; {habla})"
