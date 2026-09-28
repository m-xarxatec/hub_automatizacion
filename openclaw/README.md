# OpenClaw (día 5)

OpenClaw da acceso a **ChatGPT** y **Claude** con las suscripciones del usuario (sin claves
de API). `core` lo usa para las consultas, las dudas del router y, más adelante, las
imágenes y el modo análisis. No maneja Telegram: eso lo hace `core`. Corre en su propio
contenedor, sin puertos publicados, y guarda sus credenciales en dos volúmenes de Docker
que no salen del equipo (`openclaw_estado` y `openclaw_claude`).

> Estos pasos se hacen **una vez en cada equipo** (PC de casa y laptop), porque las
> sesiones de ChatGPT y Claude quedan guardadas en ese equipo.
> Verificado con **OpenClaw 2026.9.6**. La API de plugins es experimental: si cambias de
> versión, repite la prueba del paso 6.

## Cómo lo usa core: el plugin puente

`core` **no** usa el agente de OpenClaw: su prompt propio suma ~5.700 tokens a cada mensaje.
Usa el plugin del hub `plugins/hub-puente/` (montado en solo lectura por `docker-compose.yml`),
que expone `POST /hub/completar` (protegido con el token del gateway) y llama al modelo con
solo nuestro prompt:

| Vía | Tokens de entrada (duda del router) | Tiempo |
| --- | --- | --- |
| Agente (`/v1/chat/completions`) | 5.694 | 3,4 s |
| Herramienta `llm-task` (incluida en OpenClaw) | 2.835 | 3–7 s |
| **Plugin puente con ChatGPT** | **134** | **1,6 s** |
| Plugin puente con Haiku (respaldo) | ~3.700 | 2 s |

Haiku cuesta más porque es un programa (Claude Code) con su propio prompt; solo entra si
ChatGPT falla. La cadena está en `config.yaml` (`proveedores.consulta`).

El puente también tiene `POST /hub/imagen` (prompt, modelo, calidad, tamaño): genera con
`openai/gpt-image-2` por la suscripción de ChatGPT y devuelve la imagen en base64 (OpenClaw no
la guarda en disco). Medido: ~55 s por imagen de 1024×1536 en calidad `low`. Lo usa
`core/app/proveedores/chatgpt_img.py`, primero de la cadena de imágenes.

## 0. Antes de empezar

Si ya tienes OpenClaw instalado fuera de este proyecto conectado al mismo bot de
Telegram, **desactiva ese canal o detén ese OpenClaw**. Dos procesos leyendo el mismo
bot provocan el error 409 y `core` se niega a arrancar.

## 1. Activar el servicio

En `.env`:

```
COMPOSE_PROFILES=consulta
OPENCLAW_GATEWAY_TOKEN=<salida de ./hub.sh token>
```

```bash
docker compose --profile consulta build openclaw     # imagen de ~5 GB
```

## 2. Onboarding sin preguntas y sin canales

```bash
docker compose run --rm --no-deps -T --entrypoint node openclaw dist/index.js onboard --non-interactive \
  --accept-risk --mode local --auth-choice skip --gateway-auth token --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
  --gateway-bind lan --gateway-port 18789 --skip-channels --skip-bootstrap --skip-skills --skip-search \
  --skip-hooks --skip-ui --no-install-daemon --skip-health
```

El token no se copia: la configuración apunta a la variable `OPENCLAW_GATEWAY_TOKEN`.

## 3. Iniciar sesión en ChatGPT y en Claude (en tu terminal)

```bash
# ChatGPT: muestra un enlace y un código de dispositivo
docker compose run --rm --no-deps --entrypoint node openclaw dist/index.js models auth login --provider openai --device-code
# Claude: dentro de Claude Code escribe /login, sigue el enlace y sal con /exit
docker compose run --rm --no-deps --entrypoint claude openclaw
```

Aviso: hay reportes contradictorios sobre si Anthropic permite usar la suscripción en
herramientas de terceros. Si un día se bloquea, la cadena sigue sin Haiku.

## 4. Configuración mínima y modelos

Con el servicio levantado (`docker compose up -d openclaw`):

```bash
docker compose exec -T openclaw node dist/index.js config patch --stdin < openclaw/fragmento-config.json5
docker compose exec -T openclaw node dist/index.js models set openai/gpt-6-luna
docker compose exec -T openclaw node dist/index.js models fallbacks add claude-cli/claude-haiku-4-5
docker compose exec -T openclaw node dist/index.js models status
```

En 2026.9.6 `config patch` falla si el fragmento incluye modelos; por eso van aparte.
`fragmento-config.json5` deja lo mínimo: sin herramientas, sin skills, sin latido, solo los
plugins de ChatGPT (`codex`), Claude (`anthropic`) y el puente, y el agente HTTP apagado.

Al arrancar, el log debe decir `http server listening (3 plugins: anthropic, codex, hub-puente)`.
El aviso "OpenClaw can't verify where this plugin came from" es normal: el puente es código
del propio proyecto, no instalado desde un registro.

## 5. Comprobar

```bash
./hub.sh chequeo        # o .\hub.ps1 chequeo en Windows
```

Debe mostrar `OpenClaw y el plugin hub-puente responden`. El chequeo manda una petición vacía
que no llega al modelo (no gasta tokens).

## 6. Prueba real (gasta unos 150 tokens)

```bash
docker compose exec -T openclaw node -e 'fetch("http://127.0.0.1:18789/hub/completar",{method:"POST",
  headers:{Authorization:`Bearer ${process.env.OPENCLAW_GATEWAY_TOKEN}`,"Content-Type":"application/json"},
  body:JSON.stringify({modelo:"openai/gpt-6-luna",razonamiento:"low",mensaje:"Responde solo: listo"})})
  .then(async r=>console.log(r.status,await r.text()))'
```

Respuesta esperada: `200 {"texto":"listo",...,"uso":{"inputTokens":...}}`.

## Problemas conocidos

- `EAI_AGAIN` al iniciar sesión o llamar al modelo: DNS momentáneo (p. ej. una VPN);
  reintentar.
- `Thinking level "off" is not supported for openai/gpt-6-luna`: ese modelo acepta desde `low`.
- Respuesta vacía con `claude-cli/...`: ese modelo necesita `"aislado": true` (lo pone `core`
  según `config.yaml`).
- Un modelo nuevo en `config.yaml` también debe ir en `allowedCompletionModels` del fragmento;
  si no, el plugin lo rechaza.
