// Plugin puente del hub: POST /hub/completar -> una sola llamada al modelo, sin agente.
//
// Por qué existe: el agente de OpenClaw (/v1/chat/completions) agrega ~5.700 tokens de
// prompt propio a cada mensaje. Esta ruta llama a api.runtime.llm.complete, que manda al
// modelo solo nuestro prompt (~134 tokens para una duda del router). Ver docs/BITACORA.md.
//
// Cuerpo (JSON):
//   sistema        texto del prompt de sistema (opcional)
//   mensaje        texto del usuario, o bien
//   mensajes       [{rol: "user"|"assistant", texto}] con el historial (el último, del usuario)
//   modelo         "proveedor/modelo" (debe estar en plugins.entries.hub-puente.llm)
//   razonamiento   off | minimal | low | ... (gpt-6-luna acepta desde "low")
//   max_tokens     tope de salida (orientativo)
//   aislado        true para modelos por CLI (claude-cli): solo admite un mensaje
//   tiempo_max_s   tope de espera (por defecto 60 s; el modo análisis pide más)
// Respuesta: {texto, proveedor, modelo, uso, ms} o {error, codigo}.
//
// POST /hub/imagen -> api.runtime.imageGeneration (ChatGPT por suscripción, gpt-image-2):
//   prompt, modelo ("openai/gpt-image-2"), calidad (low|medium|high), tamano ("1024x1536")
// Respuesta: {imagen (base64), mime, proveedor, modelo, ms}. La imagen viaja en memoria:
// OpenClaw no la guarda en disco; la guarda core en la bóveda.
// Las dos rutas están protegidas con el token del gateway (auth: "gateway").

const MAX_BYTES = 256 * 1024;   // peticiones de core: texto, sin imágenes
const ROLES = new Set(["user", "assistant"]);
const TIEMPO_POR_DEFECTO_S = 60;
const TIEMPO_MAXIMO_S = 900;

function tiempoMs(valor) {
  const s = Number.isFinite(valor) && valor > 0 ? Math.min(valor, TIEMPO_MAXIMO_S) : TIEMPO_POR_DEFECTO_S;
  return Math.round(s * 1000);
}

async function leerJson(req) {
  const partes = [];
  let total = 0;
  for await (const parte of req) {
    total += parte.length;
    if (total > MAX_BYTES) throw new SolicitudInvalida("la petición es demasiado grande");
    partes.push(parte);
  }
  try {
    return JSON.parse(Buffer.concat(partes).toString("utf8") || "{}");
  } catch {
    throw new SolicitudInvalida("el cuerpo no es JSON válido");
  }
}

class SolicitudInvalida extends Error {}

function armarMensajes(c) {
  if (Array.isArray(c.mensajes) && c.mensajes.length > 0) {
    const mensajes = c.mensajes.map((m) => {
      if (!m || !ROLES.has(m.rol) || typeof m.texto !== "string") {
        throw new SolicitudInvalida('cada mensaje necesita rol ("user" o "assistant") y texto');
      }
      return { role: m.rol, content: m.texto };
    });
    if (mensajes.at(-1).role !== "user") throw new SolicitudInvalida("el último mensaje debe ser del usuario");
    return mensajes;
  }
  if (typeof c.mensaje === "string" && c.mensaje.trim()) return [{ role: "user", content: c.mensaje }];
  throw new SolicitudInvalida("falta mensaje o mensajes");
}

// "Plugin LLM completion failed." no dice nada: el motivo real viaja en error.cause.
function detalle(e) {
  const partes = [];
  for (let actual = e; actual && partes.length < 4; actual = actual.cause) {
    const texto = String(actual?.message ?? actual).trim();
    if (texto && !partes.includes(texto)) partes.push(texto);
  }
  return partes.join(" <- ").slice(0, 600);
}

function fallo(res, ruta, e) {
  const error = detalle(e);
  console.warn(`[hub-puente] ${ruta} falló: ${error}`);
  return responder(res, 502, { error, codigo: e?.code ?? null });
}

function responder(res, estado, datos) {
  res.statusCode = estado;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(datos));
  return true;
}

export default {
  id: "hub-puente",
  name: "Hub puente",
  description: "Llamada directa al modelo para core, sin agente ni herramientas.",
  configSchema: {
    safeParse: (valor) => ({ success: true, data: valor }),
    jsonSchema: { type: "object", additionalProperties: false, properties: {} },
  },
  register(api) {
    api.registerHttpRoute({
      path: "/hub/imagen",
      auth: "gateway",
      match: "exact",
      handler: async (req, res) => {
        if (req.method !== "POST") return responder(res, 405, { error: "solo POST" });
        const inicio = Date.now();
        try {
          const c = await leerJson(req);
          if (typeof c.prompt !== "string" || !c.prompt.trim()) throw new SolicitudInvalida("falta prompt");
          const r = await api.runtime.imageGeneration.generate({
            prompt: c.prompt,
            cfg: api.config,
            modelOverride: typeof c.modelo === "string" ? c.modelo : undefined,
            quality: typeof c.calidad === "string" ? c.calidad : undefined,
            size: typeof c.tamano === "string" ? c.tamano : undefined,
            count: 1,
            // Solo el modelo pedido: nada de saltar a otro proveedor por su cuenta.
            autoProviderFallback: false,
            timeoutMs: 180_000,
          });
          const imagen = r.images[0];
          return responder(res, 200, {
            imagen: Buffer.from(imagen.buffer).toString("base64"),
            mime: imagen.mimeType ?? "image/png",
            proveedor: r.provider,
            modelo: r.model,
            ms: Date.now() - inicio,
          });
        } catch (e) {
          if (e instanceof SolicitudInvalida) return responder(res, 400, { error: e.message });
          return fallo(res, req.url, e);
        }
      },
    });
    api.registerHttpRoute({
      path: "/hub/completar",
      auth: "gateway",
      match: "exact",
      handler: async (req, res) => {
        if (req.method !== "POST") return responder(res, 405, { error: "solo POST" });
        const inicio = Date.now();
        try {
          const c = await leerJson(req);
          const mensajes = armarMensajes(c);
          if (c.aislado && mensajes.length !== 1) {
            throw new SolicitudInvalida("el modo aislado admite un solo mensaje");
          }
          const limite = tiempoMs(c.tiempo_max_s);
          const r = await api.runtime.llm.complete({
            messages: mensajes,
            systemPrompt: typeof c.sistema === "string" ? c.sistema : undefined,
            model: typeof c.modelo === "string" ? c.modelo : undefined,
            reasoning: typeof c.razonamiento === "string" ? c.razonamiento : undefined,
            maxTokens: Number.isInteger(c.max_tokens) && c.max_tokens > 0 ? c.max_tokens : undefined,
            purpose: "hub-puente",
            ...(c.aislado
              ? { execution: { mode: "isolated-agent-runtime", timeoutMs: limite } }
              : { signal: AbortSignal.timeout(limite) }),
          });
          return responder(res, 200, {
            texto: r.text ?? "",
            proveedor: r.provider,
            modelo: r.model,
            uso: r.usage ?? null,
            ms: Date.now() - inicio,
          });
        } catch (e) {
          if (e instanceof SolicitudInvalida) return responder(res, 400, { error: e.message });
          return fallo(res, req.url, e);
        }
      },
    });
  },
};
