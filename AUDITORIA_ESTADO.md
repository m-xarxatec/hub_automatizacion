# Auditoría de estado — Hub creativo

Fecha: 2026-09-29 · Equipo auditado: laptop Windows 11 (clon en `entregable_automatizacion/hub_automatizacion`, 7 commits, último `84e0523`) · Solo lectura: el único archivo creado es este informe.

## Resumen

- El código está muy avanzado: bot, router (reglas + SetFit + IA si duda), bóveda, voz local, OpenClaw e imágenes están **implementados** y la bitácora registra 247 pruebas en verde en la PC de casa (Ubuntu), el 2026-09-28.
- **En esta laptop no se ha verificado nada todavía**: Docker Desktop está instalado pero apagado, no hay imágenes construidas, falta `.env` y `datos/` y `modelos/` están vacíos (no hay modelo del router ni de voz).
- La suite completa no se pudo ejecutar porque el Python del equipo (3.11) no tiene pytest, aiogram, httpx ni setfit, y la auditoría no permitía instalar paquetes. Corrí 20 pruebas sin dependencias: pasan 19 de 20 (con zona horaria UTC simulada). La que falla lo hace por un problema de codificación de la propia prueba en Windows.
- Solo son documentación: Syncthing (sin confirmar que esté instalado o emparejado), la app web (es una página de relleno) y la búsqueda web (vacía).
- Las imágenes **no** usan la API de OpenAI con clave: van por la suscripción de ChatGPT a través de OpenClaw (`gpt-image-2`).
- El modelo del router, las correcciones y las credenciales OAuth de OpenClaw viven solo en la PC de casa (no se suben al repo ni se sincronizan). Hay que rehacerlos o copiarlos en la laptop.
- No hay secretos en el repo ni en el historial de git.

## Inventario

- **Estructura:** `core/` (Python 3.12: bot, router, bóveda, estado, 11 archivos de prueba), `voz/` (FastAPI + faster-whisper + Kokoro), `openclaw/` (Dockerfile, fragmento de config y plugin `hub-puente` en JS), `docs/BITACORA.md`, `config.yaml`, `docker-compose*.yml`, `hub.sh` y `hub.ps1`.
- **Punto de entrada:** `core/app/main.py:52` (`principal()`), que arranca el bot, la web, el latido y la limpieza. Dependencias en `core/requirements.txt` (aiogram 3, fastapi, setfit 1.2.0, transformers 5.17, torch 2.14 CPU en el Dockerfile) y `voz/requirements.txt`.
- **Documentos:** están `README.md`, `GUIA.md` y `docs/BITACORA.md` (1385 líneas, del 26 al 28 de septiembre). **Faltan `CLAUDE.md` y `docs/CHECKPOINT.md`**: están en `.gitignore` (`.gitignore:15-16`), aunque la bitácora y `openclaw/fragmento-config.json5:5` los citan.
- **Diferencias entre documentos y código:**
  - El README dice "48 pruebas rápidas + 1 lenta" (`README.md:216`). El código tiene 154 funciones de prueba en `core` más 11 en `voz`, y la bitácora dice 247 casos.
  - El README dice que `/consulta` usa "ChatGPT mini". `config.yaml:39-41` usa `openai/gpt-6-luna` y, si falla, `claude-haiku-4-5`.
  - La cabecera de `core/app/boveda/escritor.py:4` dice "archivos nuevos en vez de editar existentes", pero `acciones/notas.py:3` acumula las notas en `Ideas.md`, `Historia.md`, etc.
  - El README dice que `chequeo` "verifica Syncthing". En realidad solo busca `.stfolder` (`core/scripts/chequeo.py:75`).
  - La hoja de ruta dice que el día 1 "falta instalar y sincronizar". La última entrada de la bitácora (`BITACORA.md:1343`) está escrita "antes de instalar Syncthing".

## Tabla de componentes

| # | Componente | Estado | Evidencia |
|---|---|---|---|
| 1 | Bot Telegram: texto | Implementado | Handlers en `telegram_bot.py:361-787`; en esta laptop no se ha confirmado que funcione |
| 1 | Bot Telegram: voz | Implementado | `telegram_bot.py:738-760`; el audio se procesa en memoria, sin tocar disco (`:205-210`) |
| 1 | Seguridad: lista blanca | Implementado | Middleware `SoloAutorizados` (`telegram_bot.py:150-170`) aplicado a mensajes y botones (`:1077-1079`) |
| 2 | Router: reglas | Implementado | `router/reglas.py:26-37,104-118`; órdenes directas antes del router (`telegram_bot.py:344-358`) |
| 2 | Router: clasificador SetFit | Implementado, sin modelo en este equipo | `router/clasificador.py`. El modelo va en `datos/router/modelo/`, que aquí está vacío. Datos: `router/datos/ejemplos.yaml` (120 ejemplos, 20 por cada una de 6 acciones) más `datos/router/{correcciones,aprendidos}.yaml` |
| 2 | Precisión del router | Sin métrica formal | Solo la bitácora: 15 de 15 frases no vistas, unos 10 ms (`BITACORA.md:57-58`). No hay conjunto de prueba ni matriz de confusión |
| 2 | IA de respaldo | Implementado | `cascada.py:77-126`, `llm_openclaw.py:50-54` (gpt-6-luna y luego Haiku, máximo 150 tokens de salida) |
| 3 | Nota / tarea | Implementado | `acciones/notas.py:25-33`, `boveda/proyectos.py:113-158` |
| 3 | Ficha de personaje | Implementado | `reglas.pedido_personaje:202`, `acciones/referencias.py:47-58`, `acciones/personajes.py` |
| 3 | Consulta | Implementado (necesita OpenClaw) | `acciones/consulta.py:42-55` |
| 3 | Imagen | Implementado (necesita OpenClaw) | `acciones/imagenes.py:114-134`, `proveedores/chatgpt_img.py:42-46` |
| 3 | Imagen como referencia en la ficha | Implementado | `acciones/referencias.py:79-101` |
| 3 | Análisis | Implementado | `acciones/analisis.py:148,222`; prueba real con los 3 modelos en la bitácora (`BITACORA.md:1287`) |
| 3 | Búsqueda | No existe | `acciones/busqueda.py` es solo un comentario; el bot responde "llega en la fase 3" (`telegram_bot.py:55`) |
| 4 | Escritura en la bóveda | Implementado | Escritura atómica (`escritor.py:64-74`), nombres únicos (`:54`), nombres válidos en Windows (`:18-51`), carpetas por proyecto (`config.yaml:5-24`), `.stignore` (`proyectos.py:47-53`). No detecta archivos `.sync-conflict` |
| 5 | Transcripción local | Implementado, modelos sin descargar aquí | `voz/servidor.py:41-43,207` (Whisper `small`, CPU, int8, vocabulario de pista) |
| 5 | Respuesta por voz | Implementado | Kokoro `jf_tebukuro` (`voz/servidor.py:250-259`), se descarga con verificación SHA-256 (`:110`) |
| 6 | OpenClaw: modelos | Implementado | `config.yaml:39-62`, `openclaw/fragmento-config.json5`, plugin `hub-puente/index.js` |
| 6 | OpenClaw: OAuth | Solo documentado (paso manual) | `openclaw/README.md:66-75`. Las credenciales están en volúmenes Docker de cada equipo, así que en la laptop hay que repetir el login |
| 6 | Cambio de modelo si se agota la cuota | Parcial | En cada petición, cualquier error pasa al siguiente modelo (`openclaw.py:109-112`). No reconoce que la cuota se agotó, no recuerda qué modelo está agotado y no hay cortacircuitos. El análisis nunca cambia de modelo solo (es una decisión de diseño) |
| 7 | Imágenes | Implementado, por suscripción | `gpt-image-2` a través de OpenClaw, sin `OPENAI_API_KEY`. Cloudflare y tensor.art están desactivados (`config.yaml:69-75`). El cortacircuitos está en `cadena.py:11` |
| 8 | Limpieza | Implementado | `estado/limpieza.py:27-35`: tmp 24 h, logs 14 días, imágenes descartadas 7 días, `.tmp` de la bóveda 1 h. El historial de consulta queda en 6 mensajes y 12 h (`db.py:95-111`), y `/nuevo` lo borra. `audio_crudo` en la config no se lee, pero no hace falta (el audio nunca se guarda) |
| 9 | Syncthing | Solo documentado | README §2 y GUIA §4; en el código solo el `.stignore` y el aviso de `.stfolder` |
| 9 | App web local | Relleno | `entradas/web/servidor.py:21-31`: `/salud` y una página que dice "llega en la fase 2" |
| 10 | Docker | Implementado, sin verificar en Windows | 3 Dockerfiles y `docker-compose.yml` con perfiles. No hay ejecutable. Imágenes `latest` sin fijar (`openclaw/Dockerfile:1`, `docker-compose.yml:44`, `claude-code` sin versión) |
| 10 | Portabilidad Ubuntu ↔ Windows | Parcial | `hub.ps1` equivalente a `hub.sh` (sin `permisos`, que en Windows no hace falta), `.gitattributes` con LF y CRLF para `.ps1` (verificado con `git ls-files --eol`), latido y error 409 para que no corran dos servidores a la vez |

## Resultados de pruebas

**Suite completa (`hub.ps1 tests`): no se ejecutó.** El motor de Docker no responde (`dockerDesktopLinuxEngine` no existe) y el Python del equipo (3.11.7) no tiene pytest, aiogram, httpx, fastapi, setfit, cryptography ni tzdata.

**Pruebas que sí se pudieron correr:** usé un mini-ejecutor en una carpeta temporal fuera del repo, con `-B` para no dejar caché, sobre los módulos que solo usan la biblioteca estándar y PyYAML. Son 20 pruebas de `test_boveda`, `test_estado` y `test_router_y_referencias`:
- Tal cual: 12 pasan y 8 fallan, todas con `ZoneInfoNotFoundError` (en Windows, Python no trae la base de zonas horarias sin `tzdata`; en Docker sí viene).
- Con la zona horaria simulada a UTC: 19 pasan y 1 falla. `test_crear_proyecto_y_buscar_por_nombre_o_alias` da `UnicodeDecodeError` porque la prueba escribe con la codificación por defecto (cp1252) en `tests/test_boveda.py:47`.

**Router con 15 frases:** solo se pudo probar la capa de reglas (más las órdenes directas previas). No hay setfit ni modelo entrenado en este equipo, y la IA de respaldo no se llamó para no gastar tokens.

| Frase | Acción (reglas) | Conf. | Ruta / nivel |
|---|---|---|---|
| nota idea: el mercado flota sobre el río | nota (tipo general, no "idea") | 0.45 | reglas → preguntar (IA si hay OpenClaw). Por voz la toma la orden hablada |
| tengo que terminar el storyboard del capítulo 3 | tarea | 0.85 | reglas → ejecutar |
| recuérdame llamar al editor el viernes | tarea | 0.85 | reglas → ejecutar |
| crea un personaje que sea un carnicero llamado Bruno | personaje | — | orden directa (`pedido_personaje`), antes del router |
| Zamael tiene miedo a los perros | nota | 0.45 | reglas → preguntar/IA; al guardar va a la ficha si existe |
| ¿cuántos paneles suele tener un capítulo de webtoon? | consulta | 0.60 | reglas → confirmar/IA |
| cómo se entinta digitalmente | consulta | 0.60 | reglas → confirmar/IA |
| genera una imagen de una elfa albina bajo la lluvia | imagen | 0.85 | reglas → ejecutar |
| dibújame el templo en ruinas de noche | nota ✗ | 0.45 | reglas → preguntar/IA (falla porque no dice "imagen") |
| analiza si es viable que la villana sea la hermana… | análisis | 0.80 | reglas → ejecutar (luego pide confirmar modelo) |
| búscame referencias de armaduras samurái | búsqueda | 0.75 | reglas → confirmar → "fase 3" (no implementada) |
| la villana usa una máscara de zorro | nota/historia | 0.45 | reglas → preguntar/IA |
| mañana revisar los colores | nota ✗ (es tarea) | 0.45 | reglas → preguntar/IA |
| quizás el protagonista debería morir en el arco final | nota/historia | 0.45 | reglas → preguntar/IA |
| el templo | nota | 0.45 | reglas → preguntar/IA (ambigua) |

Sin SetFit, solo 6 de 15 frases se resuelven sin preguntar (4 ejecutadas por reglas, el análisis y 1 orden directa). Las otras 9 irían a la IA de respaldo o a los botones. **Por eso, en la laptop sin modelo entrenado se gastan más tokens.**

**Arranque del bot con una bóveda temporal: no confirmado.** Hace falta aiogram, un `TELEGRAM_TOKEN` y Docker. Las comprobaciones de arranque están en `main.py:57-66` (token, bóveda montada, latido).

**Problemas específicos de Windows encontrados:**
1. El motor de Docker está apagado y ninguna imagen se ha construido nunca en esta laptop (**no se ha confirmado que compile en Windows**).
2. Fuera de Docker, `ZoneInfo` falla sin `tzdata` (`boveda/proyectos.py`, `estado/limpieza.py`). Dentro del contenedor no afecta.
3. Algunas pruebas leen y escriben sin `encoding` (`test_boveda.py:21,30,37,47`, `test_estado.py:24`, `test_router_y_referencias.py:52-59`) y fallan si se corren fuera de Docker en Windows.
4. `leer_frontmatter` (`escritor.py:90-93`) solo captura `OSError`. Un `.md` guardado en ANSI (por ejemplo, desde el Bloc de notas) lanza `UnicodeDecodeError` en `buscar_proyecto` (`proyectos.py:73`) y en `agregar_al_final` (`escritor.py:79`).
5. `git config core.autocrlf` vale `true` en este equipo (el README pide `false`). `.gitattributes` lo compensa: `main.py` y `hub.sh` están en LF en el disco.
6. Sin confirmar: el rendimiento del montaje de `C:/…` a través de WSL2 y si `os.replace` falla cuando Obsidian tiene el archivo abierto en Windows.

## Ahorro de tokens

| Punto de llamada | Modelo | Contexto enviado | Caché | ¿Local o reglas? |
|---|---|---|---|---|
| Duda del router (`llm_openclaw.py:50-54`) | gpt-6-luna (bajo) y luego Haiku en modo aislado | Prompt corto + frase, unos 134 tokens de entrada (`BITACORA.md:734`). **Haiku aislado: unos 3.636** (`:793`). Salida máx. 150 | No | Sí: solo si la confianza es < 0.80 o hay contradicción. Lo aprendido va a `aprendidos.yaml` y `/reentrenar` |
| Consulta (`consulta.py:45-47`) | gpt-6-luna y luego Haiku | Prompt + hasta 6 mensajes (12 h) + pregunta. Salida máx. 600 (200 por voz) | No | No (pregunta abierta) |
| Análisis (`analisis.py:148,222`) | Opus 5.5 / Sonnet 5 / GPT-6 Sol, a elección | Hasta 20.000 tokens de notas + unos 3.700 que agrega Claude Code. Salida máx. 2.500 | No | No. Siempre con estimación y confirmación previas |
| Imagen (`chatgpt_img.py:42-46`) | gpt-image-2, calidad low, 1024×1536 | Idea tal cual (máx. 4.000 caracteres) | No | Mejorar el prompt con qwen está apagado (`config.yaml:47`) |
| Transcripción / TTS / SetFit / reglas | Whisper, Kokoro, MiniLM (locales) | — | — | 0 tokens |

- **% de solicitudes resueltas sin tokens: no confirmado.** En esta laptop no hay registros (`datos/` vacío). El log registra el motor de cada decisión (`telegram_bot.py:797`), así que se puede calcular con `datos/logs/hub.log` de la PC de casa.
- Mejoras posibles:
  - Evitar que Haiku en modo aislado sea el respaldo del router, porque cuesta unas 27 veces más.
  - Ampliar las reglas con verbos como "dibújame…" y "mañana…".
  - Copiar el modelo entrenado a la laptop.

## Riesgos

**Seguridad**
- Sin secretos en el repo ni en el historial (revisé los diffs de todo el historial).
- `.gitignore` cubre `.env*`, `datos/`, `modelos/`, `CLAUDE.md` y `CHECKPOINT.md`.
- Con `TELEGRAM_USUARIOS` vacío, el bot le responde a cualquiera con su ID (no ejecuta acciones), en `telegram_bot.py:165`.
- La web con `LAN_IP=0.0.0.0` no tiene autenticación. Hoy solo muestra estado, pero exige cuidado cuando crezca.
- El gateway de OpenClaw no publica puertos y el plugin exige token.
- Usar la suscripción de Claude a través de OpenClaw tiene un riesgo de términos de servicio que el propio repo advierte (`openclaw/README.md:75`).
- Las imágenes `latest` sin fijar pueden cambiar y romper algo el día de la demo.

**Pérdida de datos en la bóveda**
- `agregar_al_final` lee, modifica y reescribe el archivo entero (`escritor.py:77-82`) sobre archivos compartidos (`Ideas.md`, `tareas.md`, `Diario`). Si llega a la vez una edición del móvil, pueden aparecer `.sync-conflict` o perderse cambios, y el código no los detecta.
- `insertar_en_seccion` reescribe la ficha completa (`referencias.py:93`).
- Dos imágenes simultáneas con el mismo nombre pueden pisarse (`imagenes.py:117-120`, `os.replace`). La probabilidad es baja.
- El versionado de Syncthing solo está previsto en la PC (README §2.5).
- `FORZAR_ARRANQUE=1` salta la protección contra dos servidores a la vez (`main.py:69-72`).
- `datos/router` (correcciones y aprendizaje) no se sincroniza, así que el entrenamiento de la PC y el de la laptop se separan.

## Faltantes priorizados (MVP en vivo desde la laptop)

**Bloqueantes**
1. Arrancar Docker Desktop con WSL2, construir las imágenes (`hub.ps1 arrancar`) y confirmar que compilan en Windows.
2. Crear `.env` (no existe) con `TELEGRAM_TOKEN`, `TELEGRAM_USUARIOS`, `VAULT_PATH` (con `/`), `SERVIDOR_NOMBRE=laptop`, `LAN_IP`, `OPENCLAW_GATEWAY_TOKEN` y `COMPOSE_PROFILES=consulta`.
3. Tener la bóveda en la laptop: por Syncthing (sin confirmar) o, como mínimo, una carpeta local con un proyecto de demo.
4. Modelos:
   - `hub.ps1 modelos` (MiniLM, unos 470 MB).
   - `hub.ps1 entrenar` (unos 3 min), o copiar `datos/router/` de la PC.
   - El primer arranque de `voz` descarga Whisper y Kokoro (hace falta internet).
5. OpenClaw en la laptop: onboarding, login OAuth de ChatGPT y de Claude, `config patch` y `models set` (`openclaw/README.md` pasos 1-5). Las credenciales no viajan entre equipos.
6. Detener el stack en la PC de casa antes de la demo (error 409 y latido).
7. En la laptop, `hub.ps1 tests` y `hub.ps1 chequeo` deben terminar en "listo". **Nunca se ha verificado en Windows.**

**Importantes**
- Fijar versiones de las imágenes de OpenClaw, Claude Code y Ollama.
- Activar el versionado de Syncthing también en la laptop.
- Terminar el día 6 (`/estado` con gasto y cuotas, pruebas de fallos).
- Grabar un video de respaldo (día 7).
- Manejar los `.md` que no estén en UTF-8 sin que el bot falle.
- Calcular el % de solicitudes sin tokens a partir de los logs.

**Opcionales**
- App web (fase 2), búsqueda (fase 3), Cloudflare y tensor.art, qwen local, Whisper en GPU.
- Que las pruebas corran fuera de Docker en Windows (`encoding` y `tzdata`).
- Recordar qué modelo se quedó sin cuota.

## Preguntas que necesito responderte

1. ¿La demo será en esta laptop? ¿Hay algún problema para arrancar Docker Desktop y construir las imágenes aquí? (unos GB de descarga).
2. ¿Puedes copiar `datos/router/` desde la PC de casa (modelo, correcciones y aprendidos), o reentrenamos en la laptop?
3. ¿Syncthing ya está instalado y emparejado? La bitácora termina justo antes de instalarlo.
4. Tu pedido menciona la "API de OpenAI" para las imágenes, pero el código usa la suscripción de ChatGPT a través de OpenClaw. ¿Lo dejamos así?
5. ¿Puedes pasarme `CLAUDE.md` y `docs/CHECKPOINT.md`? Están excluidos de git y no están en este clon.
6. Cuando un modelo se queda sin cuota, ¿basta con probar el siguiente en cada petición (como ahora) o quieres que el bot recuerde cuál se agotó y lo salte hasta que se renueve?
7. ¿Aceptas el riesgo de términos de servicio de usar la suscripción de Claude a través de OpenClaw para la demo?
