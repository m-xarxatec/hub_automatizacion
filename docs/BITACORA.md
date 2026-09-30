# Bitácora del proyecto

Una entrada por tarea terminada, la más reciente al final. Cada entrada incluye:
qué se hizo, archivos tocados, decisiones y por qué, problemas y cómo se resolvieron,
cómo probarlo y el concepto aprendido.

---

## 2026-09-26 — Contexto del proyecto y verificación del entorno

**Qué se hizo**
- Lectura del proyecto: README, GUIA (sección 7), config.yaml, docker-compose.yml y core/app/.
- Creación de `CLAUDE.md` con el contexto, las decisiones fijas, la forma de trabajar y el plan.
- Verificación del entorno y propuesta del plan del día 3.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `CLAUDE.md` | Contexto que cada sesión nueva de Claude Code carga automáticamente |
| `.venv/` (no se sube) | Entorno virtual de Python para probar sin Docker |

**Decisiones**
- Probar en un entorno virtual (`.venv` en la raíz) porque Docker no estaba instalado. Así se valida
  el código con el mismo Python 3.12 que usa la imagen.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| Docker no está instalado en la PC de casa | Pruebas en `.venv`; instalación de Docker pendiente (GUIA, sección 2) |
| Faltaban `.gitignore`, `.gitattributes` y `.env.example` (probablemente se perdieron al copiar la carpeta, porque empiezan con punto) | Se recrearon en la tarea siguiente |
| La GUIA mencionaba solo la RTX 3050 | Aclarado: la PC de casa tiene una GTX 1650 y la laptop de la presentación una RTX 3050 (ambas de 4 GB) |

**Resultado:** 23 pruebas pasan en `.venv`; `docker compose build core` no se pudo ejecutar porque falta Docker.

**Cómo probarlo**
```bash
python3 -m venv .venv && .venv/bin/pip install -r core/requirements.txt
cd core && ../.venv/bin/python -m pytest -q
```

**Qué aprendiste: el entorno virtual.** Un `.venv` es una copia aislada de Python con sus
propias librerías: instalar algo ahí no toca el Python del sistema. Se parece a la imagen de
Docker, pero solo aísla Python, no todo el sistema operativo. Por eso sirve para probar rápido
aunque Docker no esté instalado.

---

## 2026-09-27 — Archivos faltantes y día 3: router local

**Qué se hizo**
- Se recrearon `.gitignore`, `.gitattributes` y `.env.example`.
- Router local completo: clasificador SetFit, segunda opinión con el LLM local, correcciones
  aprendidas con los botones y `/reentrenar`.
- Se instalaron torch (solo CPU) y SetFit en `.venv` y se comprobó que el entrenamiento real funciona.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `.gitignore` | Excluye `.env`, `datos/`, `modelos/` y `.venv/` del repositorio |
| `.gitattributes` | LF en todo (los scripts corren en contenedores Linux); CRLF solo en `.ps1` |
| `.env.example` | Plantilla de todas las variables, sin valores reales |
| `core/app/router/clasificador.py` | Entrena y carga SetFit. Guarda en una carpeta temporal y solo al final reemplaza el modelo anterior |
| `core/app/router/ejemplos.py` (nuevo) | Une `ejemplos.yaml` con `datos/router/correcciones.yaml`; si chocan, gana la corrección |
| `core/app/router/datos/ejemplos.yaml` | 20 ejemplos por acción (120 en total) |
| `core/app/proveedores/ollama.py` | Cliente de `/api/chat` con esquema JSON y temperatura 0; si algo falla devuelve `None` |
| `core/app/router/llm_local.py` | Segunda opinión restringida a las acciones de `config.yaml`, validada en Python |
| `core/app/router/cascada.py` | Clasificador → reglas → LLM (solo si hay duda) → botones; ahora es asíncrono |
| `core/app/entradas/telegram_bot.py` | Fila de botones Imagen · Consulta · Análisis · Búsqueda para corregir; registro de correcciones; `/reentrenar` |
| `core/app/main.py` | Crea el LLM local y se lo pasa al router |
| `core/app/config.py`, `config.yaml` | `segunda_opinion` y `llm_timeout_s` |
| `core/scripts/entrenar_router.py` | Entrena desde la terminal (`./hub.sh entrenar`) |
| `core/scripts/descargar_modelos.py` | También descarga MiniLM a `modelos/hf` |
| `core/Dockerfile`, `core/requirements.txt` | torch 2.14 solo CPU en su propia capa; setfit, sentence-transformers, transformers y datasets con versión fija |
| `docker-compose.yml` | `HF_HOME` y el volumen `./modelos/hf` en `core` |
| `hub.sh`, `hub.ps1` | Atajo `entrenar` |
| `core/tests/test_router_local.py` (nuevo), `test_bot.py`, `conftest.py` | 25 pruebas nuevas y el marcador `lenta` |
| `README.md`, `GUIA.md`, `CLAUDE.md` | Comandos, hoja de ruta y estado actualizados |

**Decisiones y por qué**
- **torch solo CPU:** pesa unos 200 MB frente a más de 2 GB con CUDA. MiniLM predice en ~10 ms en CPU,
  y así la GPU (4 GB) queda libre para Ollama.
- **Versiones fijas** (setfit 1.2.0, sentence-transformers 6.1.0, transformers 5.17.0, datasets 5.0.1):
  setfit suele romperse cuando cambia transformers. Se fijó la combinación que se probó.
- **Correcciones en `/datos/router/correcciones.yaml`** y no en `ejemplos.yaml`: el contenedor no
  escribe en archivos del repositorio, y cada equipo guarda su propio estado operativo.
- **El LLM solo opina cuando hay duda** (confianza por debajo de `umbral_ejecutar`). Si coincide,
  la confianza sube; si no coincide, se pregunta. Lo que dice solo el LLM nunca se ejecuta directo:
  como mucho se pide confirmación.
- **No se registra como corrección** pulsar "Nota" cuando el router propuso una función que aún no
  existe (por ejemplo, imagen): eso significa "guárdalo mientras tanto", y registrarlo ensuciaría
  los datos de entrenamiento.
- **`setfit` se importa dentro de las funciones:** importar el módulo no carga torch, así las
  pruebas y el arranque sin modelo siguen siendo rápidos.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| Instalar `setfit` directamente habría descargado torch con CUDA (más de 2 GB) | Instalar antes torch desde el índice CPU de PyTorch; pip lo reutiliza |
| En la prueba del bot, el último mensaje enviado era la respuesta al botón y no el texto | Función auxiliar que busca el último mensaje que tiene botones |
| Docker sigue sin estar instalado | Pausa: el usuario instala Docker y el NVIDIA Container Toolkit (GUIA, sección 2) |

**Resultado:** 48 pruebas rápidas pasan y la lenta, que entrena de verdad, tarda unos 2 min 40 s y
también pasa. Con 15 frases que no estaban en los ejemplos acertó las 15, con unos 10 ms por
predicción. Queda pendiente verificar `docker compose build core` y `./hub.sh tests`.

**Cómo probarlo**
```bash
cd core && ../.venv/bin/python -m pytest -q
HUB_PRUEBAS_LENTAS=1 ../.venv/bin/python -m pytest -q -k setfit_real   # ~3 min
# Con Docker:
./hub.sh modelos && ./hub.sh entrenar && ./hub.sh reiniciar
# En Telegram: /estado → "clasificador local (120 ejemplos…) + LLM local";
# escribir frases ambiguas, corregir con los botones y usar /reentrenar.
```

**Qué aprendiste: few-shot learning con SetFit.** En vez de entrenar un modelo enorme con miles
de ejemplos, SetFit parte de un modelo que ya "entiende" frases (MiniLM). Primero le enseña a
acercar las frases de la misma acción y alejar las de acciones distintas usando pares de ejemplos
(con 120 frases salen 4.800 pares), y después entrena encima un clasificador simple. Por eso
bastan 20 ejemplos por acción y reconoce frases que nunca vio.

---

## 2026-09-27 — Docker instalado y día 3 verificado en contenedor

**Qué se hizo**
- Se diagnosticó el error de permisos de Docker después de instalarlo.
- Se construyó la imagen de `core` y se ejecutaron las pruebas dentro del contenedor.
- Se ejecutó el entrenamiento real del router dentro del contenedor, con los volúmenes de `datos/` y `modelos/hf`.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `datos/router/modelo/` (no se sube) | Primer modelo del router entrenado (120 ejemplos) |
| `modelos/hf/` (no se sube) | Caché de MiniLM (458 MB); no se vuelve a descargar al reconstruir |
| `CLAUDE.md` | Estado actualizado: el día 3 está verificado en Docker |

No hubo cambios de código.

**Decisiones y por qué**
- **No se creó `.env` para probar:** el compose exige `VAULT_PATH` y `.env`, y tocar `.env` requiere
  confirmación. Para construir se pasó `VAULT_PATH=/tmp/boveda-prueba` solo en ese comando, y las
  pruebas se ejecutaron con `docker run` montando `config.yaml`, igual que lo haría el compose.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| `permission denied ... /var/run/docker.sock` | El usuario ya estaba en el grupo `docker`, pero la sesión se había abierto antes del cambio. Solución definitiva: cerrar sesión y volver a entrar. Mientras tanto, `sg docker -c "<comando>"` ejecuta el comando con el grupo activo |
| `./hub.sh tests` no funciona sin `.env` (el compose usa `env_file: .env`) | Se usó `docker run` directo. Cuando exista el `.env`, `./hub.sh tests` funcionará normal |
| Los archivos que el contenedor crea en `datos/` y `modelos/` son de `root` (ya pasaba antes del día 3) | **Pendiente de decidir:** ejecutar el contenedor con el usuario del equipo (`user:` en el compose) cambia la arquitectura; en Windows con Docker Desktop no afecta. Mientras tanto, para borrarlos a mano en Ubuntu: `sudo rm -r datos/router` |

**Resultado**
- Imagen `hub-creativo-core`: 2,34 GB en disco, con torch `2.14.0+cpu` y ningún paquete `nvidia-*` (`torch.version.cuda = None`).
- Primera construcción: 2 min 12 s.
- La GPU GTX 1650 se ve desde un contenedor (`./hub.sh gpu`).
- 48 pruebas pasan dentro del contenedor y 1 lenta se salta.
- Entrenamiento real dentro del contenedor: 215 s.

**Cómo probarlo**
```bash
# Después de cerrar sesión y volver a entrar (o anteponiendo sg docker -c "..."):
docker run --rm hello-world && ./hub.sh gpu
VAULT_PATH=/tmp/boveda-prueba docker compose build core
docker run --rm -e CONFIG_PATH=/app/config.yaml -v ./config.yaml:/app/config.yaml:ro \
  hub-creativo-core python -m pytest -q
# Con .env creado: ./hub.sh tests  y  ./hub.sh entrenar
```

**Qué aprendiste: grupos de Linux y sesiones.** Los grupos de un usuario se cargan al iniciar
sesión, así que un proceso conserva los grupos que tenía cuando arrancó. Por eso `usermod -aG docker`
no surte efecto en la terminal ya abierta hasta que cierras sesión y vuelves a entrar. `sg docker`
(o `newgrp docker`) abre un proceso nuevo que ya incluye el grupo.

---

## 2026-09-27 — Decisión: permisos de los contenedores y datos del .env

**Qué se hizo**
- Se decidió cómo manejar los archivos de root que crean los contenedores.
- Se entregó al usuario la lista de datos y comandos para crear su `.env`, sin leer ni tocar el archivo.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `CLAUDE.md` | Registra la decisión y que los commits se hacen cuando el usuario avise |

**Decisiones y por qué**
- **Los contenedores siguen corriendo como root (KISS).** Es lo estándar en Docker, funciona igual en
  Ubuntu, Windows (Docker Desktop no aplica permisos de Linux a las carpetas montadas) y cualquier
  servidor. Además, Ollama usa una imagen oficial que igual escribe como root en `modelos/ollama`:
  cambiar solo `core` no resolvería nada y sumaría variables `UID`/`GID` y casos especiales por sistema.
  Costo aceptado: en Ubuntu, borrar a mano algo de `datos/` o `modelos/` requiere `sudo`.
- **Commits al final:** el usuario avisará cuándo hacer el commit de todo.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| No existe bóveda ni está instalado Syncthing en la PC de casa | Crear `~/Boveda` para empezar; Syncthing se instala con la sección 2.5 de la GUIA (pendiente del día 1) |

**Resultado:** sin cambios de código; las pruebas siguen como en la entrada anterior (48 pasan).

**Cómo probarlo:** `ls -l datos/ modelos/` muestra carpetas de `root` creadas por los contenedores; es lo esperado.

**Qué aprendiste: KISS en infraestructura.** "Keep it simple" no significa la solución más
elegante, sino la que tiene menos piezas que puedan fallar al mover el sistema de sitio. Una
configuración que es igual en todos los equipos vale más que otra más "correcta" que necesita
ajustes distintos en cada uno.

---

## 2026-09-27 — Stack en marcha y día 4: imágenes

**Qué se hizo**
- Se levantó el stack por primera vez (`core` + `ollama` con GPU) y se descargó qwen2.5 3B. El bot
  quedó activo en Telegram con el router entrenado.
- Se investigó en la documentación actual si ChatGPT Plus sirve para generar imágenes y cómo es la API de tensor.art.
- Se implementó el día 4: cadena de imágenes con failover, Cloudflare, tensor.art, prompt mejorado
  por el LLM local, guardado en la bóveda, `/img`, `/diagnostico` y generación desde texto libre y botones.
- Se detectó y corrigió la lentitud de la primera llamada al LLM local.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/proveedores/cadena.py` | `Imagen`, `ErrorProveedor`, `SinProveedores`; `CadenaImagenes` prueba en orden y reúne los motivos de fallo; `crear_cadena()` lee `config.yaml` |
| `core/app/proveedores/cloudflare_img.py` | FLUX schnell (JPEG en base64); el diagnóstico verifica el token sin gastar neuronas |
| `core/app/proveedores/tensorart_img.py` | API TAMS con firma RSA: crear trabajo → consultar hasta SUCCESS → descargar; el diagnóstico pide solo el costo |
| `core/app/proveedores/chatgpt_img.py` (nuevo) | Hueco para ChatGPT por OAuth vía OpenClaw; se conecta el día 5 |
| `core/app/proveedores/local_img.py`, `openai_img.py` | **Eliminados** (sin Stable Diffusion local ni `/img+`) |
| `core/app/acciones/imagenes.py` | Idea → prompt en inglés y título (LLM local) → cadena → imagen + nota hermana → diario |
| `core/app/entradas/telegram_bot.py` | `/img`, `/diagnostico`; "imagen" del router genera directo; el botón "Imagen" registra y genera; mensaje de fallo |
| `core/app/proveedores/ollama.py` | `precargar()`: carga y calienta el modelo al arrancar |
| `core/app/main.py` | Crea el generador de imágenes y lanza la precarga |
| `config.yaml` | Cadena `chatgpt → cloudflare → tensorart` con sus opciones |
| `docker-compose.yml` | `OLLAMA_KEEP_ALIVE: "-1"` |
| `core/requirements.txt` | `cryptography==50.0.1` (firma RSA) |
| `.env.example` | Variables de Cloudflare y tensor.art; se quitó `OPENAI_API_KEY` |
| `core/tests/test_imagenes.py` (nuevo), `test_bot.py`, `test_router_local.py` | 21 pruebas nuevas |
| `CLAUDE.md`, `README.md`, `core/scripts/descargar_modelos.py` | Decisión 5 actualizada, comandos y hoja de ruta |

**Decisiones y por qué**
- **Cadena ChatGPT → Cloudflare → tensor.art (decisión del usuario).** Primero lo que ya se paga
  (ChatGPT Plus por OAuth de Codex, vía OpenClaw), luego lo gratis a diario (Cloudflare) y al final
  tensor.art, que solo regala 1.000 créditos una vez y después cobra (0,003 USD por crédito, compra mínima de 10.000).
- **Sin Stable Diffusion local, sin cola y sin `/img+`.** No se sobrecarga el equipo con modelos
  locales cuando ya hay servicios pagados. Si todo falla, el bot responde con el mensaje, el
  diagnóstico queda en los logs y en `/diagnostico`, y la idea se guarda como nota para no perderla.
- **El diagnóstico nunca genera imágenes:** Cloudflare usa `tokens/verify` y tensor.art `/v1/jobs/credits`. Así no gasta cuota.
- **ChatGPT queda como hueco** hasta el día 5: la documentación de OpenClaw confirma que genera con
  `gpt-image-2` por OAuth, pero no explica cómo recibe la imagen un cliente externo. Hay que probarlo con OpenClaw configurado.
- **La extensión se detecta por el contenido** (Cloudflare devuelve JPEG, no PNG).
- **Ollama mantiene el modelo cargado siempre** (`KEEP_ALIVE=-1`): sin Stable Diffusion local, nada compite por la VRAM.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| El stack parecía colgado y no mostraba nada | No lo estaba: la imagen de Ollama es grande y tardó unos 13 min en descargarse (se confirmó en `journalctl -u docker`) |
| La documentación de TAMS dice `appid=`, pero el ejemplo oficial usa `app_id=` | Se usa `app_id=`, lo que hace el código oficial; la prueba verifica la firma con la clave pública |
| La primera llamada al LLM tardó 46 s y superaba el límite de 15 s del router | Dos causas: cargar el modelo y la primera respuesta con esquema JSON. Solución: `KEEP_ALIVE=-1` y precarga con una llamada JSON real al arrancar. Resultado: 1,3 s en la primera llamada |
| La imagen de `core` se había construido antes del código del día 4 | Se reconstruyó con `./hub.sh arrancar` |
| Una prueba esperaba "imagen llega el día 4" | Se cambió por una consulta (día 5) |

**Resultado**
- 69 pruebas pasan en `.venv` y en el contenedor; 1 lenta se salta.
- Integración real con Ollama en la GTX 1650:
  - segunda opinión con sentido (nota, imagen y consulta) en unos 0,4 s;
  - prompt en inglés con título en español en 1,3 s;
  - el modelo usa 2,2 GB de VRAM, 100% en GPU.
- Todavía no hay imágenes reales porque faltan las claves de Cloudflare y tensor.art.

**Cómo probarlo**
```bash
cd core && ../.venv/bin/python -m pytest -q
# Con las claves en .env:
./hub.sh reiniciar
# En Telegram: /diagnostico  →  cloudflare "ok: token active"
#              /proyecto Webtoon  y  /img la villana con máscara de zorro bajo la lluvia
#              "genera una imagen del templo de noche" (texto libre)
# En Obsidian: Proyectos/Webtoon/Imagenes/<fecha>-<titulo>.jpg + .md con la idea y el prompt
```

**Qué aprendiste: failover con diagnóstico separado.** Una cadena de proveedores prueba uno tras
otro y se queda con el primero que responde, así un servicio caído no deja al usuario sin
resultado. El diagnóstico va aparte y usa endpoints que no gastan cuota (verificar el token,
pedir el costo), porque para diagnosticar un fallo no deberías pagar otra imagen.

---

## 2026-09-27 — Nuevo orden del MVP y paso A: notas de voz → órdenes

**Qué se hizo**
- Se acordó un nuevo orden del MVP: (A) notas de voz → transcripción → órdenes; (B) OpenClaw con
  lo de pago; (C) respuesta con voz. Las medidas ante fallos quedan para después del MVP.
- Se implementó el paso A: servicio de transcripción local con faster-whisper, cliente en `core`,
  órdenes habladas y el flujo completo en el bot.
- Se apagó el LLM local en el MVP con un interruptor en `config.yaml`.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `voz/servidor.py` | `POST /transcribir` (faster-whisper `small` int8 en CPU, español, filtro de silencios); borra el audio siempre; rechaza audios de más de 120 s; carga el modelo al arrancar; registra los tiempos |
| `voz/Dockerfile`, `voz/requirements.txt` (nuevo) | Imagen solo CPU de 793 MB con `faster-whisper==1.2.1` (trae PyAV: no hace falta ffmpeg para leer OGG) |
| `voz/tests/test_servidor.py` (nuevo) | 3 pruebas con un modelo falso: texto, audio largo, audio dañado; el temporal siempre se borra |
| `core/app/voz/cliente.py` | `ClienteVoz.transcribir()` y `estado()`; los fallos llegan como `ErrorVoz` legible |
| `core/app/router/reglas.py` | `orden_hablada()`: "nota idea, …", "tarea: …", "crea un proyecto nuevo llamado …", "cambia al proyecto …", "mis tareas", "estado", "genera una imagen de …" |
| `core/app/entradas/telegram_bot.py` | Notas de voz: transcribir → "Entendí: «…»" → orden directa o router; los comandos se separaron en funciones reutilizables; `origen: voz` en las notas; voz y LLM en `/estado` y `/diagnostico` |
| `core/app/main.py`, `core/app/ajustes.py` | `ClienteVoz` (`VOZ_URL`); el interruptor `llm_local.activo` apaga router LLM, mejora de prompts y precarga |
| `config.yaml`, `core/app/config.py` | `llm_local.activo: false` |
| `docker-compose.yml`, `docker-compose.gpu.yml` | `voz` siempre activo (sin perfil) y en CPU; `core` recibe `VOZ_URL` |
| `core/tests/test_voz.py` (nuevo), `test_bot.py` | 23 pruebas nuevas (cliente, 17 órdenes habladas, 4 flujos del bot) |
| `CLAUDE.md` | Decisiones 2, 3 y 5 actualizadas, decisión 9 (voz local) y el orden del MVP |

**Decisiones y por qué**
- **Voz 100 % local y en espejo** (decisión del usuario): si hablas, el bot responde con voz (paso C);
  si escribes, con texto. Con voz, frases cortas y sin describir ("aquí está la imagen que pediste").
- **Lo de pago primero y los respaldos al final:** consulta con ChatGPT mini → Haiku sin pensamiento;
  OpenRouter, qwen y tensor.art después del MVP. Cloudflare se mantiene como respaldo de imágenes.
- **Qwen apagado con un interruptor, sin borrar código:** el router sigue con SetFit y reglas, que son
  los que deciden de verdad. La GPU queda libre.
- **Whisper en CPU para empezar:** imagen liviana y portable a cualquier servidor. Se decide la GPU
  con los tiempos reales de las notas del usuario. Por eso se quitó `voz` de `docker-compose.gpu.yml`,
  porque pedía CUDA a una imagen que no lo trae.
- **Órdenes habladas con reglas y no con un modelo:** son frases fijas, las reglas cuestan 0 ms y se
  prueban una por una. Lo demás va al router, igual que el texto.
- **El bot repite lo que entendió** ("Entendí: «…»") mientras las respuestas sean de texto. En el paso C,
  con respuesta por voz, se revisará.
- **Los comandos se separaron en funciones:** una orden hablada ejecuta exactamente lo mismo que el comando escrito.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| "Dibújame" no se reconocía (la tilde rompía el patrón) | Clases con tilde: `dib[uú]ja`, `gen[eé]ra`, `cr[eé]a` |
| `docker-compose.gpu.yml` pedía CUDA para `voz` | Se quitó hasta medir; queda anotado cómo activarlo |
| qwen seguía ocupando VRAM ("Forever") | `ollama stop`; con `activo: false` no se vuelve a cargar |
| Una prueba preparaba dos notas de voz y ambas "decían" la segunda frase | La transcripción falsa se fijaba al construir el mensaje; se separaron las llamadas |

**Resultado:** 92 pruebas pasan en `core` y 3 en `voz`. En el stack real, Whisper `small` cargó en CPU
(la primera vez tardó 149 s porque incluía la descarga de 464 MB), `/estado` muestra "Voz: listo" y la
GPU quedó libre (283 MiB). Pendiente: tiempos con notas de voz reales del usuario.

**Cómo probarlo**
```bash
cd core && ../.venv/bin/python -m pytest -q
cd ../voz && ../.venv/bin/python -m pytest -q tests
./hub.sh arrancar
# En Telegram, notas de voz: "crea un proyecto nuevo llamado Webtoon", "nota idea, la villana usa
# una máscara de zorro", "tarea: comprar tinta", "¿cuáles son mis tareas?", "la villana es la hermana
# del protagonista" (esta última pasa por el router)
docker compose logs voz | grep Transcritos     # duración del audio vs. tiempo de transcripción
```

**Qué aprendiste: separar la entrada de la acción.** El bot no tiene un "modo voz": la voz se
convierte en texto en la frontera (el servicio `voz`) y a partir de ahí recorre el mismo camino que un
mensaje escrito. Por eso bastan pocas líneas nuevas en el bot y todo lo que ya estaba probado sigue
sirviendo. Es el mismo principio de los adaptadores: cada entrada distinta se traduce a un formato común.

---

## 2026-09-27 — Prueba de voces anime para la respuesta (TTS) y checkpoint

**Qué se hizo**
- Se creó `docs/CHECKPOINT.md` y una indicación al inicio de `CLAUDE.md` para que cada sesión nueva
  continúe desde ahí sin leer el chat anterior.
- Se buscaron voces TTS gratuitas y locales con estilo "chica anime japonesa" y se generaron 8
  muestras (4 de Kokoro y 4 de VOICEVOX) que se enviaron por Telegram para que el usuario elija.
- Tras un apagón de la PC, se rehízo la prueba en una carpeta persistente.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `docs/CHECKPOINT.md` (nuevo) | Dónde quedamos, qué falta probar y los próximos pasos; se actualiza al cerrar cada sesión |
| `CLAUDE.md` | Indica leer primero el checkpoint |
| `datos/tts_prueba/` (no se sube) | Entorno de prueba: modelo Kokoro, scripts y muestras OGG; se borra al elegir la voz |

No hubo cambios en el código del hub.

**Decisiones y por qué**
- **Whisper no genera voz:** solo transcribe. Para responder hace falta un TTS; el plan decía Piper,
  pero Piper no tiene voces anime.
- **Kokoro** (Apache 2.0, 82M, CPU) tiene voces femeninas japonesas y también habla español: una voz
  japonesa leyendo español da el efecto "chica japonesa hablando español". Mezclarla con la voz
  española `ef_dora` mejora la pronunciación. El tono se sube sin librerías extra: generar más lento
  y reproducir más rápido.
- **VOICEVOX** (voces anime auténticas) solo habla japonés: el español se escribió en katakana. Se
  probó porque el usuario lo pidió, aunque se entiende peor.
- **Whisper como juez:** si Whisper transcribe bien la muestra, una persona también la entiende. Es
  una medida objetiva para comparar voces.
- Las pruebas se hicieron **fuera del hub**: no se tocaron dependencias ni imágenes del proyecto hasta
  que el usuario elija.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| `kokoro-onnx` fallaba con `.../home/runner/.../phontab: No such file` | Se instaló `phonemizer-fork` en lugar de `phonemizer` y `espeakng-loader==0.2.3`, porque la 0.2.4 trae la ruta grabada |
| Las muestras de VOICEVOX duraban el doble | Cada espacio o 「、」 entre palabras es una pausa; se escribió la frase en katakana todo junto |
| La PC se apagó y `/tmp` (scratchpad) se borró con las muestras y la descarga a medias | Se rehízo en `datos/tts_prueba/`, que es persistente; el stack volvió solo por `restart: unless-stopped` |

**Resultado**
- Las 8 muestras se enviaron a Telegram.
- Según Whisper, Kokoro 2, 3 y 4 se entienden bien y la 4 es la más clara; Kokoro 1 y las de VOICEVOX se entienden a medias.
- Tiempos: Kokoro int8 tarda ~11 s por ~9 s de audio en CPU; VOICEVOX ~1,5 s.
- La imagen de VOICEVOX pesa 4,31 GB.
- Pendiente: que el usuario elija.

**Cómo probarlo:** escuchar las notas numeradas en Telegram. Para regenerarlas:
`cd datos/tts_prueba && venv/bin/python muestras.py` (Kokoro) o, con el motor en marcha
(`docker run --rm -p 127.0.0.1:50021:50021 voicevox/voicevox_engine:cpu-latest`), `venv/bin/python voicevox.py`.

**Qué aprendiste: dónde guardar el trabajo temporal.** `/tmp` se vacía al reiniciar, así que sirve
para archivos que se pueden regenerar en segundos, no para descargas de gigas ni pruebas largas. Lo
que debe sobrevivir a un apagón va en una carpeta persistente fuera del repositorio, como `datos/`.
Así, el costo de un corte es reiniciar un proceso y no rehacer el trabajo.

---

## 2026-09-27 — Voz de respuesta elegida: Kokoro `jf_tebukuro`

**Qué se hizo**
- El usuario eligió la muestra 3 (Kokoro `jf_tebukuro`).
- Se guardó solo lo necesario para el paso C y se borró el resto de la prueba.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `modelos/kokoro/kokoro-v1.0.int8.onnx` (no se sube) | Modelo Kokoro int8 (114 MB) |
| `modelos/kokoro/voces_jf_tebukuro.npz` (no se sube) | Solo la voz elegida (0,5 MB en vez de 28 MB con las 54 voces) |
| `datos/tts_prueba/` | **Borrada** (entorno, scripts y muestras) |
| Imagen `voicevox/voicevox_engine:cpu-latest` | **Borrada** (4,31 GB) |
| `CLAUDE.md` | Decisión 9: Kokoro `jf_tebukuro` en lugar de Piper |
| `docs/CHECKPOINT.md` | Receta de Kokoro lista para el paso C |

**Decisiones y por qué**
- **Kokoro `jf_tebukuro`** (elección del usuario): suena a chica japonesa y Whisper la entiende bien.
  Queda fuera Piper, que no tiene voces de este estilo.
- **Archivo de voces reducido a una sola voz:** es 56 veces más chico y deja claro qué voz usa el hub.

**Problemas encontrados:** ninguno. Se comprobó que el archivo reducido genera audio antes de borrar el original.

**Resultado:** el modelo y la voz quedaron listos en `modelos/kokoro/`. Se liberaron unos 4,5 GB de disco.

**Cómo probarlo:** en el paso C, `POST /hablar` del servicio `voz` usará estos archivos.

**Qué aprendiste: quedarse solo con lo que se usa.** Un archivo de voces con 54 voces es cómodo
para probar, pero en producción cada byte extra es algo más que descargar, copiar y entender. Recortar
al final de una prueba (guardar la voz elegida y borrar el resto) deja el sistema más liviano y
hace evidente qué decisión se tomó.

## 2026-09-27 — Cierre del paso A: prueba con notas de voz reales

**Qué se hizo**
- El usuario probó 6 notas de voz reales en Telegram. Se midieron los tiempos y se revisó en la bóveda
  qué hizo el bot con cada una.
- Se corrigió la limpieza de tareas: "Añade la tarea practicar dos horas al día" se guardaba con la
  orden incluida.
- Se agregó una pista de vocabulario para Whisper: el usuario habla español latinoamericano (seseo) y
  "zorro" se transcribía "sorro".

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/reglas.py` | `_VERBO_GUARDAR` (agrega, añade, anota, apunta, pon, crea, guarda, con o sin "me"): lo usan las órdenes habladas de tarea y nota y `limpiar_tarea()`, que además quita el punto final |
| `core/app/voz/cliente.py` | `ClienteVoz(vocabulario=…)` manda la pista como parámetro `pista` (solo si hay) |
| `voz/servidor.py` | `POST /transcribir?pista=…` → `initial_prompt` de Whisper, recortado a 400 caracteres |
| `config.yaml`, `core/app/config.py`, `core/app/main.py` | Nueva sección `voz.vocabulario`, editable sin tocar código |
| `core/tests/test_voz.py`, `voz/tests/test_servidor.py` | 15 pruebas nuevas: órdenes con verbos y artículos, frases que no son órdenes, `limpiar_tarea()` y la pista en ambos lados |

**Decisiones y por qué**
- **Whisper se queda en CPU.** Tiempos reales: 12,8 s de audio en 1,54 s; 8,3 s en 1,13 s; 1,7 s en 0,95 s.
  Transcribir cuesta casi 1 s fijo más muy poco por segundo de audio. Con GPU se ganaría menos de 1 s
  a cambio de una imagen CUDA pesada y de competir por los 4 GB de VRAM.
- **El artículo ("la", "una") solo se acepta después de un verbo.** "La tarea de hoy es difícil" no es
  una orden; "añade la tarea…" sí.
- **La pista va en `config.yaml` y la manda `core`.** Así el usuario agrega personajes y términos sin
  reconstruir imágenes, y `voz` sigue sin saber nada de proyectos.
- **Los botones cuando el bot duda se quedan** (el usuario los aprobó). La respuesta por voz para cada
  orden se hará en el paso C.
- **Paso C con acento latinoamericano:** espeak con `lang="es"` es español de España (la z suena "th").
  Kokoro debe usar `es-419`.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| "Añade la tarea practicar dos horas al día." quedó con ese texto en `tareas.md` | La orden hablada solo conocía "nueva/agrega tarea" y la frase fue al router. El router acertó la acción, pero `limpiar_tarea()` tampoco conocía "añade la tarea". Se agregaron verbos y artículos en los dos sitios |
| "máscara de sorro" | Seseo: el audio no distingue z y s. `initial_prompt` con el vocabulario del proyecto orienta la ortografía |
| `core` no registra el texto transcrito ni la acción elegida | Se revisó en la bóveda (archivos modificados después de la hora de arranque). Queda como idea para `/diagnostico`, no se implementó |

**Resultado:** 107 pruebas pasan en `core` (1 omitida, la lenta) y 4 en `voz`. Imágenes reconstruidas
y stack reiniciado. Pendiente: que el usuario confirme que "zorro" y "añade la tarea…" salen bien.

**Cómo probarlo**
```bash
cd core && ../.venv/bin/python -m pytest -q
cd ../voz && ../.venv/bin/python -m pytest -q tests
docker compose build core voz && ./hub.sh arrancar
# En Telegram, notas de voz: "nota idea, la villana usa una máscara de zorro",
# "añade la tarea practicar dos horas al día", "apúntame una tarea: llamar al editor"
docker compose logs voz | grep Transcritos
```

**Qué aprendiste: el contexto previo también es una entrada del modelo.** Whisper no solo escucha:
predice el texto palabra por palabra y usa lo que "ya se dijo" para decidir. Con `initial_prompt` se le da
un texto previo inventado con las palabras del proyecto. Cuando el sonido es ambiguo (s/z con seseo,
nombres como Zamael), elige la ortografía que ya vio, sin reentrenar nada.

## 2026-09-27 — Notas acumuladas por tipo y fichas de personaje desde texto o voz

**Qué se hizo**
- Por pedido del usuario, las notas ya no crean un archivo cada una: se agregan al final de
  `Ideas.md`, `Historia.md` o `Produccion.md` del proyecto (sin proyecto, `00-Bandeja/Notas.md`).
- Archivo propio solo si se pide: "crea un archivo sobre…", "nota aparte: …", "…en un archivo aparte",
  `/nota aparte: …`.
- Si la nota nombra a un único personaje con ficha, va a "## Notas" de esa ficha.
- "Crea un personaje (llamado X)…" crea `Historia/Personajes/X.md` con la descripción. Sin nombre,
  el bot pregunta "¿Cómo se llama el personaje?" y toma el siguiente mensaje (texto o voz) como respuesta.
- Se actualizó la decisión fija 6 de `CLAUDE.md` (aprobada por el usuario).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/boveda/proyectos.py` | `guardar_nota()` agrega con encabezado `## fecha hora · voz\|texto`; `aparte=True` conserva el archivo único; `archivo_notas()` y `enlace()` (enlace con ruta para el diario) |
| `core/app/acciones/notas.py` | `guardar()`: decide archivo propio → ficha de personaje → archivo del tipo |
| `core/app/acciones/personajes.py` (nuevo) | `mencionado()` (nombre o alias con mayúscula, uno solo), `anotar()`, `crear_o_anotar()` |
| `core/app/acciones/referencias.py` | `insertar_en_seccion()` generalizada (la usan imágenes y notas); la plantilla de ficha trae "## Notas" y la descripción |
| `core/app/router/reglas.py` | `archivo_aparte()`, `pedido_personaje()`, `nombre_respondido()`; `orden_hablada()` reconoce "nota aparte" |
| `core/app/entradas/telegram_bot.py` | `orden_directa()` y `respuesta_de_nombre()` antes del router (texto y voz); botones "Guardar como idea" / "Cancelar" al preguntar el nombre; mensajes "agregada a…", "archivo propio…", "ficha de…"; ayuda actualizada |
| `core/tests/*` | 31 pruebas nuevas; las del bot y la bóveda se adaptaron al nuevo destino |
| `CLAUDE.md` | Decisión 6 actualizada |

**Decisiones y por qué**
- **Agregar al final mantiene la seguridad de antes.** Es la misma técnica de `tareas.md` (escritura atómica
  a un temporal y renombrado). El único riesgo es que edites ese mismo archivo en otro equipo justo
  cuando el bot escribe. En ese caso Syncthing guarda una copia `.sync-conflict` y no se pierde nada.
- **Un archivo por tipo y no uno solo:** se lee mejor en Obsidian y no crece tan rápido.
- **Encabezado con fecha, hora y origen:** cada nota queda enlazable desde el diario
  (`[[Proyectos/webtoon/Ideas#2026-09-27 10:12 · voz|Ideas de webtoon]]`). Se enlaza con la ruta porque
  todos los proyectos tienen su `Ideas.md`.
- **Personaje mencionado solo si hay uno y con mayúscula.** "Luz odia la lluvia" va a la ficha de Luz,
  pero "la luz del templo" no. Si se nombran dos personajes, la nota va a `Historia.md`, para no elegir mal.
- **"Crea un personaje" y "archivo aparte" no pasan por el router.** Son frases fijas: las reglas cuestan
  0 ms y no se mezclan con las correcciones del clasificador.
- **Si la respuesta al "¿cómo se llama?" no parece un nombre** (más de 4 palabras), la descripción se guarda
  como idea en `Historia.md` y el mensaje sigue su camino normal. Nada se pierde y el bot no se queda esperando.
- **Pedir otra vez un personaje que ya existe** no pisa su ficha: la descripción nueva va a sus notas.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| "la nota del capítulo está en otro archivo" se tomaba como pedido de archivo aparte | Al final de la frase se exige "un/una" + adjetivo (aparte, nuevo, separado, propio) |
| "llamado Bruno que sea carnicero" tomaba todo como nombre | `re.I` global hacía que `[A-Z]` aceptara minúsculas; se limitó a las palabras clave con `(?i:…)` |
| "Nuevo personaje, Kira." no detectaba el nombre | Patrón para el nombre al inicio: mayúscula seguida de coma o fin de frase |
| La plantilla de ficha dejaba líneas en blanco dobles | Una sola línea entre secciones; la descripción solo si hay |

**Resultado:** 138 pruebas pasan en `core` (1 omitida, la lenta). `core` reconstruido y reiniciado. Las notas
de prueba anteriores (un archivo por nota) siguen en la bóveda. El bot no las borra; si sobran, se borran a mano.

**Cómo probarlo**
```bash
cd core && ../.venv/bin/python -m pytest -q
docker compose build core && docker compose up -d core
# En Telegram (texto o voz), con el proyecto activo:
#   "nota idea, el mercado flota sobre el río"  -> Proyectos/webtoon/Ideas.md
#   "crea un archivo sobre el templo en ruinas" -> archivo propio en Ideas/
#   "crea un personaje que sea un carnicero"    -> "¿Cómo se llama?" -> "Bruno" -> Personajes/Bruno.md
#   "Bruno tiene miedo a los perros"            -> ficha de Bruno, sección Notas
```

**Qué aprendiste: una conversación de dos pasos necesita estado.** Para preguntar "¿cómo se llama?" el bot
tiene que recordar qué estaba haciendo cuando llegue la respuesta. Aquí se guarda por chat una clave que
apunta al pendiente, con vencimiento de 10 minutos. Cada mensaje nuevo revisa primero si respondía a una
pregunta. Si la respuesta no encaja, se libera la espera para que el bot no quede "trabado".

## 2026-09-27 — Ajuste tras la prueba real: el nombre del personaje en frases completas

**Qué se hizo**
- En la prueba real, "Crea un personaje que sea una elfo albina de ojos rojos" hizo la pregunta
  correctamente, pero la respuesta hablada "El nombre del personaje será Aeli" no se reconoció como nombre.
  La descripción quedó como idea en `Historia.md` y no se creó la ficha.
- `nombre_respondido()` ahora busca el nombre dentro de la frase.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/reglas.py` | `_NOMBRE_EN_FRASE`: "el nombre (del personaje) es/será X", "se (va a) llama(r/rá) X", "llámala X", "ponle X", "le vamos a poner X"; sin esas expresiones, se acepta una respuesta de hasta 3 palabras |
| `core/tests/test_voz.py`, `test_bot.py` | 6 casos nuevos con las frases reales del usuario; el flujo del bot responde con frase completa |

**Decisiones y por qué**
- **Buscar el nombre después de una expresión conocida, no adivinar.** Así "Se va a llamar Ana Luz y es una
  bruja" da "Ana Luz". Igual que en `pedido_personaje()`, las palabras siguientes del nombre deben ir
  en mayúscula, para no llevarse "y es una bruja".

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| La respuesta hablada tenía 6 palabras y superaba el límite de 4 | Se extrae el nombre de la frase; el límite queda solo para respuestas sin expresión (3 palabras) |

**Resultado:** 144 pruebas pasan en `core`. `core` reconstruido y reiniciado; en el contenedor,
`nombre_respondido("El nombre del personaje será Aeli.")` devuelve `Aeli`.

**Cómo probarlo:** en Telegram, "crea un personaje que sea una elfo albina de ojos rojos" y responder
"el nombre del personaje será Aeli" → `Historia/Personajes/Aeli.md` con la descripción.

**Qué aprendiste: las pruebas con usuarios reales encuentran lo que las pruebas escritas no.** En las
pruebas imaginamos respuestas cortas ("Se llama Bruno"), pero al hablar la gente contesta con frases
completas. Por eso cada fallo real se convierte en un caso de prueba con la frase literal: así no vuelve
a romperse.

## 2026-09-27 — El router aprende de la IA y nueva cascada para las dudas

**Qué se hizo**
- Se acordó con el usuario la cascada del router para cuando SetFit duda: ChatGPT mini → Claude Haiku
  → qwen en GPU a demanda (`keep_alive` corto) → botones. Nada en CPU. Se actualizó la decisión 2.
  Se implementa en el paso B, porque necesita OpenClaw.
- Se implementó ya el aprendizaje: cuando el clasificador duda, la IA confirma la acción y esta se
  ejecuta sin preguntar, la frase se guarda como ejemplo para el próximo `/reentrenar`.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/ejemplos.py` | `aprendidos.yaml`: `guardar_aprendido()` (sin repetir frases ya aprendidas o corregidas) y `leer_aprendidos()`; `unir()` con el orden ejemplos → aprendidos → correcciones |
| `core/app/router/cascada.py` | `Router.aprender()`: solo si participó la IA (motor `clasificador+…`) y el nivel es "ejecutar"; `reentrenar()` y `/estado` cuentan los aprendidos |
| `core/app/entradas/telegram_bot.py` | `resolver()` llama a `aprender()` antes de ejecutar nota, tarea o imagen; mensajes de `/reentrenar` y ayuda |
| `core/scripts/entrenar_router.py`, `hub.sh`, `hub.ps1` | Textos con los aprendidos |
| `core/tests/test_router_local.py`, `test_bot.py` | 3 pruebas nuevas (prioridad y duplicados, cuándo se aprende y cuándo no, flujo del bot) y 2 ajustadas |
| `CLAUDE.md`, `docs/CHECKPOINT.md` | Decisión 2 actualizada; el router del paso B queda descrito |

**Decisiones y por qué**
- **El modelo grande enseña al chico.** Cada duda que resuelve la IA le cuesta tokens una vez. Después
  de reentrenar, SetFit resuelve esa forma de hablar solo, así que el gasto baja con el uso.
- **Archivo aparte y prioridad para el usuario.** Los aprendidos no se mezclan con `correcciones.yaml`.
  Al unir, las correcciones van al final y ganan: si la IA se equivocó y el usuario lo corrige, manda el usuario.
- **Solo se aprende lo que se ejecutó sin preguntar.** Si la IA no está de acuerdo con SetFit, el bot
  pregunta, y el botón que elija el usuario ya se guarda como corrección, que es mejor fuente.
- **Qwen en GPU con `keep_alive` corto y no en CPU** (pedido del usuario): en CPU compite con Whisper y
  Kokoro. Con `keep_alive`, Ollama descarga el modelo solo y la GPU queda libre la mayor parte del tiempo.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| "Falta el layout." y "falta el layout" se guardaban como frases distintas | `normalizar()` no quita la puntuación; para los duplicados se compara también sin los signos de los extremos |

**Resultado:** 147 pruebas pasan en `core` (1 omitida, la lenta).

**Cómo probarlo**
```bash
cd core && ../.venv/bin/python -m pytest -q tests/test_router_local.py tests/test_bot.py
# Con la IA conectada (paso B): cuando el bot ejecute algo que SetFit dudaba, aparece en
cat datos/router/aprendidos.yaml     # y /estado muestra "N aprendidos de la IA"; luego /reentrenar
```

**Qué aprendiste: destilación.** Un modelo grande y caro etiqueta ejemplos y uno pequeño y barato
aprende de esas etiquetas. Es la misma idea con la que se entrenan modelos chicos a partir de grandes.
Aquí se aplica a escala casera: la IA solo se consulta cuando SetFit duda, y cada consulta deja un
ejemplo que reduce las siguientes.

## 2026-09-27 — Paso B (en curso): OpenClaw instalado, conectado y adelgazado

**Qué se hizo**
- Se construyó la imagen de OpenClaw (2026.9.6, 5,04 GB) con Claude Code 2.1.283.
- Se hizo el onboarding sin preguntas, sin canales ni Telegram, con el token leído desde `.env`
  (`--gateway-token-ref-env`).
- El usuario inició sesión en ChatGPT (código de dispositivo) y en Claude Code (`/login`, cuenta Pro).
- Modelos: `openai/gpt-6-luna` como principal, con razonamiento `off`, y `claude-cli/claude-haiku-4-5`
  como respaldo. Haiku probado directo: 1 s.
- Endpoint `/v1/chat/completions` activo y probado desde `core` (HTTP 200).
- Se redujo lo que carga OpenClaw: de 18.113 a 5.694 tokens de entrada por llamada, y de 12,4 a 3,4 s.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `openclaw/Dockerfile` | Ejecuta `install.cjs` de Claude Code (el postinstall no bajaba el binario) y comprueba `claude --version`; crea `/home/node/.claude` con dueño `node` |
| `docker-compose.yml` | `CLAUDE_CONFIG_DIR=/home/node/.claude` en `openclaw`: `.claude.json` queda dentro del volumen |
| `openclaw/fragmento-config.json5` | Configuración verificada: endpoint, sin herramientas, plugins bloqueados, sin skills ni bootstrap, razonamiento `off`, sin latido; cómo aplicarla en dos partes |

**Decisiones y por qué**
- **Onboarding sin preguntas y los inicios de sesión aparte.** El usuario solo hace lo que exige un
  navegador (ChatGPT y Claude). El resto es repetible con un comando.
- **`gpt-6-luna`:** en la suscripción no hay modelo "mini"; "luna" es la gama barata de la generación actual.
- **OpenClaw con lo mínimo (pedido del usuario).** Por defecto carga 14 plugins, herramientas, memoria
  ("dreaming") y un latido, que consumen tokens y hasta consultan al modelo por su cuenta. Se dejaron solo
  `codex` y `anthropic`, sin herramientas ni skills, y sin latido.
- **qwen no va en la cadena de OpenClaw:** `core` lo llamará directo a Ollama con `keep_alive` corto.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| "claude native binary not installed" | `node $(npm root -g)/@anthropic-ai/claude-code/install.cjs` en el Dockerfile |
| El `/login` de Claude no se guardaba | El volumen se creó como root (la carpeta no existía en la imagen); `chown` al volumen y `mkdir` + `chown` en el Dockerfile |
| `~/.claude.json` se perdía en cada ejecución | `CLAUDE_CONFIG_DIR` apuntando al volumen |
| El primer onboarding interactivo del usuario no guardó nada | Se repitió sin preguntas (`--non-interactive --auth-choice skip`) y el inicio de sesión se hizo con `models auth login --provider openai --device-code` |
| `EAI_AGAIN auth.openai.com` | Fallo momentáneo del DNS de la VPN del usuario; al reintentar funcionó |
| `config patch` fallaba al validar el modelo ("Cannot find package 'openclaw'") | Error de OpenClaw 2026.9.6; los modelos se fijan con `models set` y `models fallbacks add` |
| `core` no tenía el token | Se creó antes de editar `.env`; `docker compose up -d --force-recreate core` |
| 18.113 tokens para responder "listo" | Perfil minimal, `plugins.deny`, `tools.allow: []`, `skills: []`, `heartbeat.every: "0m"` → 5.694 |

**Resultado:** OpenClaw responde en ~3,5 s con `gpt-6-luna`. 147 pruebas de `core` sin cambios (no se tocó
código). Pendiente: bajar más los ~5.700 tokens del prompt base, que siguen siendo mucho para el router.

**Cómo probarlo**
```bash
docker compose up -d openclaw
docker compose exec -T openclaw node dist/index.js models status   # luna + haiku, openai usable
docker compose logs openclaw | grep -E "plugins:|heartbeat"        # 2 plugins, heartbeat disabled
```

**Qué aprendiste: un agente no es un modelo.** Llamar a un agente como OpenClaw arrastra su prompt de
sistema, sus herramientas y sus tareas de fondo, aunque solo le pidas una palabra. Por eso "pocos tokens"
depende tanto de lo que carga el intermediario como de tu mensaje. Hay que medir el campo `usage` y
recortar lo que no se usa.

## 2026-09-27 — Paso B: plugin puente (134 tokens en vez de 5.694) y cliente de OpenClaw en core

**Qué se hizo**
- Se investigó qué ocupa los ~5.700 tokens del agente: es su prompt fijo (seguridad, ejecución,
  runtime de Codex). `localModelLean` solo quita herramientas (ya estaban quitadas) y `decisionModel`
  solo acepta clasificadores ONNX: ninguno sirve.
- Se encontró la llamada "cruda" de OpenClaw (`openclaw infer model run`): manda al modelo solo
  `"You are a helpful assistant."` + nuestro texto, pero solo existe por CLI (7 s por el arranque de Node).
- Se probaron tres vías con la misma duda del router y se eligió (con el usuario) un **plugin propio**,
  `hub-puente`, que expone esa llamada por HTTP dentro del gateway ya levantado.
- Cliente `proveedores/openclaw.py` en core: ChatGPT directo → Haiku aislado, historial, JSON.
- El agente HTTP (`/v1/chat/completions`) quedó apagado: core ya no lo usa.
- `./hub.sh chequeo` comprueba el puente sin gastar tokens.

| Vía (misma frase) | Tokens de entrada | Tiempo |
| --- | --- | --- |
| Agente `/v1/chat/completions` | 5.694 | 3,4 s |
| Herramienta `llm-task` por `/tools/invoke` (modo aislado de Codex) | 2.835 | 3,3–7,6 s |
| **Plugin puente, ChatGPT directo** | **134** (53 con historial corto) | **1,3–1,6 s** |
| Plugin puente, Haiku aislado | ~3.700 | 2 s |

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `openclaw/plugins/hub-puente/index.js` | Ruta `POST /hub/completar` (token del gateway): valida el cuerpo, llama a `api.runtime.llm.complete` directo o aislado y devuelve texto, modelo y uso de tokens |
| `openclaw/plugins/hub-puente/openclaw.plugin.json`, `package.json` | Manifiesto y paquete del plugin (JS plano, sin compilar) |
| `openclaw/fragmento-config.json5` | Carga el plugin (`plugins.load.paths`), le permite solo luna y Haiku, apaga `/v1/chat/completions` |
| `docker-compose.yml` | Monta `openclaw/plugins/hub-puente` en solo lectura en el contenedor |
| `core/app/proveedores/openclaw.py` | Cliente: cadena de modelos, historial (aplanado para Haiku), `completar_json` que quita ```` ``` ````; nunca lanza |
| `config.yaml`, `core/app/config.py` | `proveedores.consulta` con el formato nuevo (`modelo`, `razonamiento`, `aislado`) |
| `core/scripts/chequeo.py` | Comprueba el puente con una petición vacía (400 = bien, 401 = token, 404 = sin plugin) |
| `core/tests/test_openclaw.py` | 10 pruebas con `httpx.MockTransport` |
| `openclaw/README.md` | Reescrito con los comandos verificados, la tabla de tokens y problemas conocidos |
| `core/app/acciones/consulta.py`, `CLAUDE.md` | La consulta irá por el puente con historial en SQLite |

**Decisiones y por qué**
- **Plugin propio en vez del agente o de `llm-task`** (decidido por el usuario tras ver los números):
  40 veces menos tokens y la mitad de tiempo. El precio es depender de la API de plugins, que es
  experimental: la versión de OpenClaw queda fijada y el README pide repetir la prueba al actualizar.
- **Consulta también por el puente, con el historial en core** (SQLite, estado operativo): con el agente,
  cada pregunta pagaría otra vez los ~5.700 tokens.
- **`razonamiento: low` para luna:** es el mínimo que acepta (`off` da error). Haiku va con `off`.
- **Haiku en modo aislado:** `claude-cli` es un programa, no una API; en modo directo devuelve vacío.
  El aislado admite un solo mensaje, así que el historial se le manda aplanado en un texto.
- **Se apagó `/v1/chat/completions`:** si core no lo usa, es superficie abierta de más.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| `Thinking level "off" is not supported for openai/gpt-6-luna` | Usar `low` |
| `llm-task` gastaba 2.835 tokens | Su modo aislado pasa por el runtime de Codex, que agrega sus instrucciones; el puente usa el modo directo |
| Haiku devolvía texto vacío en modo directo | Modo aislado para modelos por CLI (`aislado: true` en `config.yaml`) |
| Haiku envuelve el JSON en ```` ```json ```` | `quitar_cercas()` en el cliente |
| Aviso "can't verify where this plugin came from" | Informativo: el plugin carga igual (`3 plugins: anthropic, codex, hub-puente`) |
| `off` en YAML se lee como `false` | Entre comillas en `config.yaml` |

**Resultado:** 157 pruebas pasan (147 + 10 nuevas), 1 omitida (la lenta de SetFit). Prueba real desde un
contenedor `core` contra el gateway: consulta con historial por ChatGPT (53 tokens, 1,4 s), duda del router
en JSON (`imagen`, 0,99), y solo Haiku (3.636 tokens, 2 s). El chequeo muestra `OpenClaw y el plugin
hub-puente responden`.

**Cómo probarlo**
```bash
docker compose --profile consulta up -d --force-recreate openclaw
docker compose exec -T openclaw node dist/index.js config patch --stdin < openclaw/fragmento-config.json5
docker compose logs openclaw | grep "plugins:"     # 3 plugins: anthropic, codex, hub-puente
./hub.sh chequeo                                   # OpenClaw y el plugin hub-puente responden
cd core && ../.venv/bin/python -m pytest -q tests/test_openclaw.py
```
La prueba real (unos 150 tokens) está en `openclaw/README.md`, paso 6.

**Qué aprendiste: medir antes de elegir la arquitectura.** Las tres vías llamaban al mismo modelo con la
misma frase, pero costaban 5.694, 2.835 y 134 tokens. La diferencia no está en el modelo sino en lo que
agrega cada intermediario. Un prototipo desechable de media hora dio números reales para decidir, en vez
de suponer.

## 2026-09-27 — Revisión de pruebas del usuario y consulta por OpenClaw

**Qué se hizo**
- Revisión de 3 mensajes que el usuario mandó al bot:
  - "…vamos a crear una elfo… llamada a Ellie" (voz) → quedó como nota en `Ideas.md` en vez de ficha.
  - Paleta cobre/tierra (voz) → `Produccion.md`. Correcto.
  - "En la ficha de personajes anota…" (texto) → `Ideas.md`; mejor en `Historia.md`.
- Mejoras simples para el MVP: plurales en los tipos de nota, pedido de personaje con introducción,
  una línea de log por mensaje y `/estado` que comprueba el plugin puente.
- **Consulta (paso B):** `/consulta <pregunta>` y texto libre. Se responde directo si el router está seguro
  y con el botón "Consulta" si duda. Guarda un historial corto en SQLite; `/nuevo` lo borra.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/reglas.py` | Tipos con plurales (`personajes`, `capítulos`, `viñetas`…) y `paleta` → producción; "crees" como verbo; `pedido_personaje` acepta introducciones ("vamos a", "quiero que"…) y oraciones previas |
| `core/app/estado/db.py` | Tabla `conversacion`: `agregar_vuelta` (deja los últimos 6 mensajes), `historial` (solo las últimas 12 h); `nueva_sesion` borra la anterior |
| `core/app/acciones/consulta.py` | Arma historial + pregunta, llama a OpenClaw, guarda la vuelta, suma el gasto por modelo y recorta a 4.000 caracteres; aviso si nadie responde |
| `core/app/entradas/telegram_bot.py` | `/consulta`, respuesta directa o por botón, "escribiendo…", log por mensaje sin contenido, `/estado` con el puente; "consulta" ya no dice "llega el día 5" si hay OpenClaw |
| `core/app/main.py` | Crea el cliente de OpenClaw si hay `OPENCLAW_GATEWAY_TOKEN` |
| `core/tests/test_bot.py`, `test_estado.py`, `test_voz.py` | 13 pruebas nuevas: consulta con historial y `/nuevo`, botón, fallo, sin token; historial en SQLite; personaje con introducción; plurales |

**Decisiones y por qué**
- **Historial corto (6 mensajes, 12 h):** basta para repreguntar ("¿y por viñeta?") sin gastar tokens en
  conversaciones viejas. Es estado operativo, no notas (decisión 1).
- **El log registra la decisión del router, no el texto:** sirve para revisar pruebas sin copiar las
  notas fuera de la bóveda.
- **La frase de la elfo sigue sin crear ficha:** es muy libre ("crear un archivo llamado personajes…
  crear una elfo… llamada a Ellie") y una regla que la acepte crearía fichas por error. La resolverá el
  router cuando duda (siguiente paso), preguntándole a ChatGPT.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| "personajes" no enviaba la nota a `Historia.md` | La regla buscaba la palabra en singular; se agregaron plurales |
| `hub.log` no decía qué hizo el router | Línea `Mensaje (voz, N caracteres): acción/tipo por motor, confianza -> nivel` |
| `/estado` diría "responde" con OpenClaw a medias | Consultaba `/v1/models` (ahora apagado) y aceptaba cualquier código < 500; ahora usa el puente (400 = bien) |
| La sesión falsa de Telegram rechazaba el "escribiendo…" | Acepta `SendChatAction` |

**Resultado:** 170 pruebas pasan, 1 omitida (la lenta). `core` reconstruido y en marcha con la consulta.

**Cómo probarlo** (en Telegram)
- `/consulta ¿qué es un storyboard?` y después `/consulta ¿y se hace por viñeta?`: la segunda respuesta
  tiene en cuenta la primera. `/nuevo` y otra pregunta: empieza de cero.
- "¿cómo se entinta con pincel?" sin comando: responde directo o pregunta con el botón "Consulta".
- "Bueno, vamos a crear un personaje llamado Kira. Es una espadachina." → ficha `Kira.md`.
- `./hub.sh logs`: una línea `Mensaje (...)` por cada mensaje.

**Qué aprendiste: el historial lo pone quien llama.** Los modelos no recuerdan nada entre llamadas: la
"memoria" de un chat es reenviar las vueltas anteriores en cada petición. Por eso cada mensaje de historial
cuesta tokens, y conviene guardarlo acotado (en número y en tiempo) y dejar que el usuario lo borre (`/nuevo`).

## 2026-09-27 — Router: ChatGPT decide cuando SetFit duda o se contradice

**Qué se hizo**
- Análisis de las pruebas del usuario: SetFit no solo duda, también se equivoca **seguro**.
  - "Y se hace por viñeta?" → nota con 0,95.
  - "…vamos a crear una elfo… llamada a Ellie" → nota con 1,00.
- Si SetFit duda (< 0,80) **o se contradice**, opina ChatGPT (→ Haiku por el puente, con tope de 15 s).
  Se consideran contradicción una pregunta tomada por nota o tarea, y "crear" junto a "personaje" o
  "llamado/a" tomado por nota.
- **Si ChatGPT está seguro (≥ 0,85), se ejecuta directo** (decisión del usuario), tanto si coincide con
  SetFit como si no. Con menos seguridad, botones.
- ChatGPT también reconoce "crear personaje" y devuelve nombre y descripción (ficha directa, o botones
  [Crear ficha] [Guardar como nota]), además del tipo de nota.
- Lo que resuelve la IA se guarda en `aprendidos.yaml` y entra en `/reentrenar`.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/llm_openclaw.py` | `OpinionIA`: prompt con acciones + "personaje" + tipos de nota, mensaje enviado como JSON, salida validada; `confiable = True` |
| `core/app/router/cascada.py` | `contradice()`, `umbral_ia_ejecutar`, `combinar()` que ejecuta a la IA confiable y segura y usa su tipo de nota |
| `core/app/router/llm_local.py` | `confiable = False`: qwen nunca se ejecuta sin confirmar |
| `core/app/router/reglas.py` | "ahora" e "y" como introducción ("Bueno, ahora vamos a crear un personaje…") |
| `core/app/entradas/telegram_bot.py` | Acción "personaje" de la IA: ficha directa o botones (`pf:`) |
| `core/app/main.py` | Opinión: ChatGPT si hay OpenClaw (tope `llm_timeout_s`); si no, qwen si está activo |
| `config.yaml` | `router.umbral_ia_ejecutar: 0.85` y comentario de la segunda opinión |
| `core/tests/test_router_ia.py`, `test_bot.py` | 21 pruebas nuevas |

**Decisiones y por qué**
- **Contradicciones además de dudas:** un modelo chico puede estar muy seguro y equivocado; dos señales
  baratas (signo de pregunta; "crear… llamado/a") mandan esos casos a ChatGPT sin consultarlo en cada mensaje.
- **Ejecución directa si ChatGPT está seguro:** menos toques; las notas solo se agregan, así que un error
  se corrige a mano fácilmente.
- **qwen no se ejecuta solo:** un modelo de 3B se equivoca más.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| La elfo nunca llegaba a ChatGPT (SetFit 1,00) | Contradicción "crear… llamado/a/personaje" |
| Tarea obvia pedía botones aunque ChatGPT coincidía (0,75) | Si coincide y está seguro, se ejecuta |
| 60 s de espera posibles por modelo | Cliente aparte para el router con `llm_timeout_s` (15 s) |

**Resultado:** 191 pruebas pasan, 1 omitida. Prueba real con el SetFit entrenado y ChatGPT:
- viñeta → consulta (2 s, ~290 tokens);
- elfo → personaje "Ellie" con "Elfa albina de ojos rojos." (2,1 s);
- "mañana le tengo que mandar los bocetos…" → tarea (1,6 s);
- paleta y storyboard → sin llamar a la IA.

**Cómo probarlo** (en Telegram, con un proyecto activo)
- "Y se hace por viñeta?" → responde como consulta.
- "vamos a crear una elfa albina de ojos rojos llamada Aeli" → crea `Historia/Personajes/Aeli.md`.
- `./hub.sh logs` → `Mensaje (...): ... por clasificador+ia ...` en los casos dudosos.

**Qué aprendiste: la confianza de un modelo no es su acierto.** Un clasificador puede decir 1,00 y
equivocarse, sobre todo con frases distintas a sus ejemplos. Por eso, además de "si duda, pregunta",
conviene detectar señales baratas de que puede estar equivocado y pedir una segunda opinión solo entonces.

## 2026-09-27 — Paso C: respuesta con voz (Kokoro `jf_tebukuro`, en espejo)

**Qué se hizo**
- `voz` tiene `POST /hablar`: Kokoro con la voz `jf_tebukuro` en español latinoamericano (`es-419`),
  tono ×1,15, salida OGG/Opus 48 kHz mono (lo que Telegram muestra como nota de voz).
- **Respuesta en espejo (decisión 9):** si el usuario manda una nota de voz, el bot responde **solo con voz**.
  Esto vale también para los botones que se pulsan sobre una respuesta hablada. Si escribe, solo con texto.
  Se quitó el eco "Entendí: «…»".
- Lo hablado es breve y sin rutas: "Nota agregada a Ideas", "Personaje Kira creado". Las consultas por voz
  piden dos o tres frases, y la imagen va sin texto, con "Aquí está la imagen que pediste".
- Si Kokoro falla, la respuesta sale en texto (no se pierde).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `voz/servidor.py` | Carga Kokoro al arrancar (junto a Whisper), `sintetizar()` con el truco del tono, `a_opus()` con PyAV, `POST /hablar` (400 vacío, 413 largo, 503 si falla) |
| `voz/Dockerfile`, `voz/requirements.txt` | `libespeak-ng1` y `espeak-ng-data` del sistema con enlaces a rutas fijas; `kokoro-onnx==0.6.1` |
| `voz/tests/test_servidor.py` | 5 pruebas nuevas, incluida una codificación Opus real |
| `core/app/voz/cliente.py` | `hablar()` y `para_hablar()` (quita rutas, paréntesis y formato; corta lo largo); `estado()` dice si hay voz |
| `core/app/entradas/telegram_bot.py` | `ModoVoz` (middleware con `ContextVar`), `decir()` para todas las respuestas, botones sobre audios (se quitan y se responde con voz), imagen y consulta en modo voz |
| `core/app/acciones/consulta.py` | `SISTEMA_VOZ` y `breve=True`: dos o tres frases, un tercio de tokens de salida |
| `core/tests/test_bot.py`, `test_voz.py` | Pruebas de voz reescritas para el espejo + 14 nuevas |
| `modelos/kokoro/kokoro-v1.0.fp16.onnx` (no se sube) | Modelo fp16 (177 MB) |

**Decisiones y por qué**
- **fp16 en lugar de int8:** medido en esta CPU (12 hilos), para 14 s de audio: int8 17,5 s, fp32 3,2 s,
  **fp16 2,9 s**. En CPU, int8 no siempre es más rápido: depende de qué operaciones tengan versión
  cuantizada. Por HTTP: 0,8 s una frase corta, 3,2 s una respuesta de consulta.
- **Un solo punto de salida (`decir`) y un `ContextVar`:** en vez de pasar "¿es voz?" por cada función, el
  middleware marca el modo al recibir el mensaje y `decir()` elige texto o voz. En modo texto hace lo mismo
  que antes, así que el cambio fue mecánico (49 reemplazos) y lo cubren las pruebas existentes.
- **Botones sobre una respuesta hablada:** un audio no tiene texto que editar; se quitan los botones y se
  responde con otro audio.
- **Espejo estricto, sin eco de la transcripción** (decisión 9). El log registra que hubo una nota
  transcrita, sin su contenido.

**Problemas encontrados**

| Problema | Resolución |
| --- | --- |
| `kokoro-onnx 0.6.1` exige `espeakng-loader>=0.2.4`, que falla por una ruta grabada | espeak-ng del sistema (apt) y `EspeakConfig(lib_path, data_path)` con enlaces a rutas fijas |
| int8 tardaba 2,2 veces la duración del audio | fp16: 6 veces más rápido |
| `para_hablar` se comía palabras ("servicio de voz" → "servicio voz") | La regla del nombre repetido solo aplica a nombres propios tras "en", "a" o ":" |
| Las pruebas de `voz` usaban la copia de la imagen | Se montan `tests/` y `servidor.py` al ejecutarlas |

**Resultado:** 203 pruebas en `core` y 9 en `voz` pasan (1 omitida, la lenta). Ida y vuelta: Whisper
transcribe bien la voz generada ("Zamael" → "Samael" por el seseo, algo esperable). Stack reconstruido y en marcha.

**Cómo probarlo** (en Telegram)
- Nota de voz "Nota idea, la villana usa una máscara de zorro" → responde con voz "Nota agregada a Ideas", sin texto.
- Nota de voz "¿qué es un storyboard?" → respuesta hablada de dos o tres frases.
- Nota de voz ambigua → audio con botones; al pulsar, se quitan los botones y responde con voz.
- Texto escrito → respuesta en texto, como siempre.
- Pruebas de `voz`: `docker compose run --rm --no-deps -T -v ./voz/tests:/app/tests:ro -v ./voz/servidor.py:/app/servidor.py:ro voz python -m pytest -q tests`

**Qué aprendiste: medir antes de optimizar, también con la cuantización.** La intuición dice que un modelo
int8 es más rápido que uno fp16 o fp32, pero en esta CPU fue 6 veces más lento: los modelos cuantizados
solo aceleran si el motor tiene versiones rápidas de sus operaciones. Tres mediciones de un minuto
cambiaron una respuesta de 25 s en una de 3 s.

## 2026-09-27 — Imágenes con ChatGPT (`gpt-image-2`) por el plugin puente

**Qué se hizo**
- Se resolvió la duda del día 5 ("¿cómo devuelve el gateway la imagen?"): la API de plugins
  `api.runtime.imageGeneration.generate` devuelve la imagen **en memoria** (`images[].buffer`), sin
  guardarla en disco.
- Nueva ruta `POST /hub/imagen` en el plugin `hub-puente`: prompt, modelo, calidad y tamaño; responde
  con la imagen en base64. `autoProviderFallback: false`, para que OpenClaw no salte a otro proveedor por su cuenta.
- `proveedores/chatgpt_img.py` implementado: es el primero de la cadena (antes se saltaba).
- Prueba real: 1024×1536 PNG (2,6 MB) en 54 s, con calidad `low`. Una hoja de personaje del zorro
  enmascarado con la paleta cobre.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `openclaw/plugins/hub-puente/index.js` | Ruta `/hub/imagen` (token del gateway; 400 sin prompt, 502 con el motivo del fallo) |
| `core/app/proveedores/chatgpt_img.py` | `generar()` por el puente, `diagnosticar()` con petición vacía (no genera ni gasta cuota) |
| `config.yaml` | `tamano: 1024x1536` para ChatGPT (vertical, como un webtoon) |
| `core/tests/test_imagenes.py` | 8 pruebas: petición, fallos legibles, sin red o token, diagnóstico sin gastar |
| `openclaw/README.md`, `CLAUDE.md` | Documentan la ruta y el estado |

**Decisiones y por qué**
- **Por el puente y no por `/tools/invoke`:** `image_generate` como herramienta obligaba a habilitarla en
  la política de herramientas (hoy `allow: []`), y su formato de salida no estaba claro. La API de plugins
  devuelve los bytes directamente, y el puente ya existe y está protegido.
- **Calidad `low`** (config.yaml): basta para ideas y referencias (decisión 5: nunca para las páginas del
  cómic) y consume menos cuota.

**Problemas encontrados:** ninguno. La API funcionó a la primera con el inicio de sesión de ChatGPT que
ya tenía OpenClaw.

**Resultado:** 211 pruebas pasan (1 omitida). `/diagnostico` real: `chatgpt: ok`. Cloudflare y
tensor.art siguen sin claves.

**Cómo probarlo:** en Telegram, `/img un zorro con máscara de kitsune, paleta cobre` (tarda ~1 min), o
por voz "genera una imagen de…" (responde "Aquí está la imagen que pediste" + la imagen). `/diagnostico`
no gasta cuota.

**Qué aprendiste: busca la puerta de servicio antes de usar la principal.** El agente de OpenClaw también
podía generar imágenes, pero con un turno de conversación completo, herramientas y miles de tokens. La API
interna para plugins hace solo esa tarea y devuelve los bytes. A menudo las plataformas tienen una capa
más baja, pensada para integraciones, que es más simple y barata que la interfaz "inteligente".

## 2026-09-27 — qwen/Ollama dormido: fuera del arranque para no competir por recursos

**Qué se hizo**
- Revisión del proyecto contra la regla "qwen no se usa en el MVP": `core` ya no lo llamaba
  (`llm_local.activo: false`), pero el servicio `ollama` seguía arrancando con el stack y con
  `OLLAMA_KEEP_ALIVE: "-1"` (cualquier llamada dejaba qwen cargado para siempre).
- `ollama` pasa al perfil `llm-local` (solo arranca si se pide), con `KEEP_ALIVE` de 30 s, y `core`
  ya no depende de él.
- `./hub.sh chequeo` (y `hub.ps1`) con `--no-deps`: el chequeo solo mira; antes levantaba las
  dependencias y recreó Ollama sin la GPU.
- `./hub.sh modelos` ya no levanta Ollama; `descargar_modelos.py` solo baja qwen si está activo.
- Valor por defecto de `llm_local.activo` en `config.py`: `false`.
- Documentación al día (README, GUIA, `.env.example`, `CLAUDE.md`).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `docker-compose.yml` | `ollama` en el perfil `llm-local`, `KEEP_ALIVE` 30 s; `core` depende solo de `voz` |
| `hub.sh`, `hub.ps1` | `chequeo` con `--no-deps`; `modelos` sin levantar Ollama |
| `core/app/config.py` | `llm_local.activo` por defecto `False` |
| `core/scripts/chequeo.py` | Si qwen está apagado, lo informa como "apagado a propósito" y no lo busca |
| `core/scripts/descargar_modelos.py` | Salta qwen si está apagado; cabecera actualizada (sin Piper) |
| `core/tests/test_router_local.py` | Prueba: sin la clave en `config.yaml`, qwen queda apagado |
| `README.md`, `GUIA.md`, `.env.example`, `CLAUDE.md` | Explican que Ollama/qwen está dormido y cómo se activaría |

**Decisiones y por qué**
- **Dormido y no borrado** (elección del usuario): la voz (Whisper, Kokoro) y el router (SetFit) ya
  corren en local; un tercer modelo de 2 GB compite por CPU, RAM y GPU. El código se conserva por si
  después del MVP hace falta como último respaldo (decisión 2, sin cambios).
- **Perfil de Compose en vez de borrar el servicio:** activarlo de nuevo es una línea en `.env`.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| Al preparar la prueba de imágenes cargué qwen a mano y quedó en CPU con `KEEP_ALIVE=-1` (2,2 GB) | `ollama stop` y quitar el contenedor; ya no se precalientan modelos sin consultar |
| El chequeo recreaba Ollama sin GPU | `--no-deps` |
| El checkpoint decía que el usuario probó las imágenes en Telegram | Solo se probaron desde código; corregido en el checkpoint |

**Resultado:** 212 pruebas pasan (1 omitida). Stack reconstruido: `core`, `voz`, `openclaw`, sin
`ollama`. Chequeo: `[ OK ] Ollama apagado a propósito`, `Resultado: listo`.

**Cómo probarlo:** `./hub.sh estado` (no aparece `ollama`) y `./hub.sh chequeo`. Para despertarlo:
`COMPOSE_PROFILES=consulta,llm-local` en `.env` y `llm_local.activo: true` en `config.yaml`.

**Qué aprendiste: los perfiles de Compose encienden y apagan servicios sin borrarlos.** Un servicio con
`profiles:` existe en el archivo, pero solo arranca si su perfil está en `COMPOSE_PROFILES`. Así una
pieza opcional no gasta recursos mientras no se usa. Ojo: si otro servicio la tiene en `depends_on`,
Compose la exige, así que la dependencia también hay que quitarla.

## 2026-09-27 — Imágenes con nombre simple (`elfa1`, `elfa2`…) y vocabulario de Whisper

**Qué se hizo**
- Prueba del usuario en Telegram: `/img`, texto libre y voz generan con ChatGPT (`gpt-image-2`) y guardan
  imagen + nota. Observaciones: los nombres llevaban la frase entera, Whisper escribió "álimen" por "anime",
  y "la misma elfa" no recibe la imagen anterior.
- **Nombres simples:** la imagen y su nota se llaman `elfa1`, `mercenario1`, `zorro1`…; si ya existe, sube
  el número (sigue al más alto, sin distinguir mayúsculas). Si la idea nombra a un personaje con ficha,
  se usa su nombre (`zamael1`). Se saca con reglas, sin modelos.
- **Nombrar la última imagen:** "la imagen que se acaba de crear será el personaje Aeli" o "renombra la
  imagen como Kira" (texto o voz) renombra la imagen y la nota, y corrige el enlace dentro de la nota.
- `voz.vocabulario`: se agregó "Crea una imagen en estilo anime de una elfa".
- Idea para después del MVP (anotada en el checkpoint): mandar la imagen anterior como referencia.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/acciones/imagenes.py` | `referente()`, `nombre()`, `siguiente()`, `ultima()`, `renombrar()`; `mejorar_prompt` devuelve solo el prompt |
| `core/app/router/reglas.py` | `renombrar_imagen()`: detecta el pedido de nombre (mayúscula, "personaje" o verbo explícito) |
| `core/app/entradas/telegram_bot.py` | Orden directa `nombrar_imagen` (antes del router); línea en la ayuda |
| `config.yaml` | Vocabulario de Whisper con "anime" y "crea una imagen" |
| `core/tests/test_imagenes.py`, `core/tests/test_bot.py` | 17 pruebas nuevas o ajustadas: palabras de las frases reales, numeración, ficha, renombrado, regla y bot por texto y voz |
| `CLAUDE.md`, `docs/CHECKPOINT.md` | Decisión y la idea para después del MVP |

**Decisiones y por qué**
- **Reglas y no IA para el nombre:** se descartan el pedido ("crea una imagen de"), las muletillas ("muy
  bien, ahora vas a"), el estilo ("en estilo X": se salta también la palabra siguiente, así "álimen" mal
  transcrito no importa) y los artículos. Queda la primera palabra con sentido. Las genéricas ("chica") solo
  se usan si no hay otra antes de un corte: "chica anime elfa" → `elfa`, "una chica en la playa" → `chica`.
  Cero tokens y ~0 ms.
- **Siempre con número** (`aeli1`, también al renombrar): mismo formato para todo y sin choques en Windows.
- **Salvaguarda contra renombrar por error:** con "es/será" se exige mayúscula o la palabra "personaje";
  "la imagen es muy bonita" no hace nada.
- **La "última imagen"** es la nota `imagen_ia` más reciente del proyecto activo (por fecha de modificación).
  No depende de la memoria del bot, así que funciona tras un reinicio.
- **El diario solo se agrega:** al renombrar se añade "Imagen elfa1 renombrada a [[aeli1]]"; la línea
  vieja no se reescribe (su enlace queda como texto histórico).
- La idea completa sigue yendo a ChatGPT; solo cambia el nombre del archivo.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| `mejorar_prompt` devolvía un título que ya no se usa | Devuelve solo el prompt; el esquema de qwen (dormido) ya no pide título |
| Riesgo de dejar la nota sin imagen si el renombrado falla a medias | Orden: nota nueva → mover imagen → borrar nota vieja |

**Resultado:** 229 pruebas pasan (1 omitida), en `.venv` y en el contenedor. `core` reconstruido y en marcha.
Las imágenes de hoy conservan su nombre anterior (se crearon antes del cambio).

**Cómo probarlo:** `/img una elfa guerrera con hacha` → `elfa1`; otra elfa → `elfa2`; después
"la imagen que se acaba de crear será el personaje Aeli" → `aeli1`. Por voz: "renombra la imagen como Kira".

**Qué aprendiste: la heurística barata primero.** Para sacar "de qué trata" una frase no siempre hace falta
un modelo: listas cortas de palabras a descartar y una regla de corte resuelven la mayoría de los casos en
microsegundos. Las pruebas con frases reales del usuario (con errores de transcripción incluidos) son las que
dicen si la heurística alcanza.

## 2026-09-28 — MVP solo con suscripciones pagas y limpieza de modelos de voz

**Qué se hizo**
- Decisión del usuario: en el MVP se trabaja **solo con las suscripciones pagas** (OpenAI y Claude). Cloudflare
  Workers AI y tensor.art quedan fuera de la cadena de imágenes hasta después del MVP.
- Se borró `modelos/kokoro/kokoro-v1.0.int8.onnx` (114 MB): lo reemplazó el fp16 y nada lo usaba. El archivo de
  voces ya tenía una sola (`voces_jf_tebukuro.npz` → `['jf_tebukuro']`, verificado dentro del contenedor `voz`).
- Stack levantado (`core`, `voz`, `openclaw`); `ollama` sigue dormido.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `config.yaml` | `cloudflare` y `tensorart` con `activo: false` y comentario del motivo |
| `core/tests/test_imagenes.py` | La prueba de la cadena comprueba el MVP (solo `chatgpt`) y sigue probando orden y `activo` |
| `CLAUDE.md` | Decisión 5 actualizada (2026-09-28) |
| `core/app/acciones/imagenes.py`, `.env.example`, `README.md` | Textos que describían la cadena de tres proveedores |
| `modelos/kokoro/` | Queda solo `kokoro-v1.0.fp16.onnx` + `voces_jf_tebukuro.npz` |

**Decisiones y por qué**
- **Desactivar, no borrar:** `crear_cadena` salta los proveedores con `activo: false`, así que no se cargan ni
  aparecen en `/diagnostico`. Su código y sus pruebas se conservan: después del MVP basta con volver a `true`.
- Con un solo proveedor, si ChatGPT falla se ve el mensaje de siempre ("en este momento no se pueden generar
  imágenes…") y la idea se guarda como nota.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| `test_crear_cadena_respeta_orden_y_activo` leía el `config.yaml` real y esperaba 3 proveedores | Ahora espera `["chatgpt"]` y activa los otros dentro de la prueba para seguir probando la lógica |

**Resultado:** 229 pruebas pasan (1 omitida). `./hub.sh chequeo` → listo; `voz` con Whisper y `jf_tebukuro`
cargados; bot en línea.

**Cómo probarlo:** `/diagnostico` debe listar solo `chatgpt`; `/img una elfa arquera` genera con ChatGPT.

**Qué aprendiste: la configuración como interruptor.** Si cada proveedor tiene un `activo` en la configuración,
quitarlo o devolverlo es cambiar un valor, sin tocar código ni perder sus pruebas. Así una decisión de negocio
("de momento solo lo pago") no obliga a borrar trabajo que quizá se retome.

## 2026-09-28 — Modo análisis, `/modelo` y renombrado de las imágenes de ayer

**Qué se hizo**
- **Modo análisis** (decisión 4): `/analisis <pedido>`, o texto libre que el router reconoce como análisis
  (o el botón "Análisis"). Junta las notas del proyecto activo, estima los tokens, muestra qué entra y ofrece un
  botón por modelo con el total estimado (`✓ Opus 5.5 · ~4.877 tokens`, `Sonnet 5`, `GPT-6 Sol`) y Cancelar.
  Nada se envía antes de pulsar. Resultado: archivo propio en `Proyectos/<p>/Analisis/`, línea en el diario y
  respuesta (por voz, solo "El análisis está listo…").
- **Si el modelo falla**: se explica el motivo (`HTTP 502 …`, `no respondió en 315 s`…) y se ofrecen los otros
  modelos en botones. Nunca se cambia de modelo solo.
- **`/modelo`** (decidido hoy con el usuario): elige el modelo de análisis predeterminado, que va primero y con ✓.
- **Modelos** (decidido hoy): Opus 5.5 (recomendado), Sonnet 5 y GPT-6 Sol, con el menor razonamiento.
- **Imágenes de ayer renombradas** a `elfa1`, `elfa2` y `mercenario1` con `GeneradorImagenes.renombrar()`
  ejecutado en el contenedor `core` (los archivos son de root).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/acciones/analisis.py` | Opciones de config, `preparar` (notas + tope + recorte), textos de confirmación, `analizar` y `guardar` |
| `core/app/entradas/telegram_bot.py` | `/analisis`, `/modelo`, botones `an:` y `mo:`, router y botón "Análisis"; caducidad por pendiente (`ttl`) |
| `core/app/proveedores/openclaw.py` | `completar_con` (un solo modelo), `tiempo_max_s` por llamada y `ultimo_error` |
| `core/app/estado/db.py` | Tabla `preferencia` (chat, clave, valor) para el modelo elegido |
| `openclaw/plugins/hub-puente/index.js` | Campo `tiempo_max_s` (antes 60 s fijos; máx. 900) |
| `openclaw/fragmento-config.json5` | Los tres modelos de análisis en `allowedCompletionModels` (reaplicado) |
| `config.yaml`, `core/app/config.py` | `proveedores.analisis` con ids reales, `max_tokens_salida`, `tiempo_max_s` y valores por defecto |
| `core/tests/test_analisis.py` y pruebas en `test_bot.py`, `test_openclaw.py`, `test_estado.py` | 16 pruebas nuevas |
| `README.md`, `CLAUDE.md` | Comandos y estado del día 5 |

**Decisiones y por qué**
- **Qué notas entran:** todas las del proyecto menos `Analisis/` (los análisis previos inflarían el contexto).
  Si no caben en `tope_tokens_entrada`, primero las que comparten palabras con el pedido y, a igualdad,
  historia → ideas → producción. La que no cabe entera se recorta dejando el final, que es lo más nuevo (las
  notas se agregan al final). Hoy `webtoon` son 9 notas y ~1.200 tokens: entra todo.
- **Tokens estimados por caracteres (÷ 3,5)**: conservador para español y sin gastar nada. En cada botón se suma
  lo que agrega el programa (`extra_tokens: 3700` en los `claude-cli`).
- **Se envía lo que se mostró:** las notas se leen al preparar y se guardan en el pendiente; si cambian en esos
  10 minutos, el modelo recibe lo que el usuario confirmó.
- **Razonamiento mínimo** (decisión 3): `off` en Claude y `low` en GPT-6 Sol (no acepta menos). Se puede subir
  en `config.yaml` si los análisis se quedan cortos.
- **Tiempo propio:** un análisis grande con Opus puede pasar de 60 s; se pide `tiempo_max_s: 300` y core espera
  15 s más para que corte el gateway y llegue su motivo.
- **Preferencia en SQLite, tabla nueva:** es estado operativo (decisión 1). `CREATE TABLE IF NOT EXISTS` evita
  migrar la base existente.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| El plugin cortaba los `claude-cli` a los 60 s fijos | `tiempo_max_s` → `execution.timeoutMs` (aislado) o `AbortSignal.timeout` (normal) |
| `/modelo` no estaba definido en ningún documento | Se preguntó: elegir el modelo de análisis predeterminado |
| Por voz decía "unos 1 mil tokens" | "unos mil tokens" (probado con la bóveda real antes de desplegar) |

**Resultado:** 245 pruebas pasan (1 omitida), en `.venv` y en el contenedor. `core` reconstruido y en marcha;
OpenClaw con los modelos nuevos (verificados en `models list`). **Falta la prueba real en Telegram** (gasta
tokens de la suscripción: ~4.900 con Opus para `webtoon` hoy).

**Cómo probarlo:** `/proyecto webtoon` y luego `/analisis busca contradicciones en la historia` → revisar notas y
tokens → pulsar Opus 5.5 → respuesta y archivo en `Proyectos/webtoon/Analisis/`. Por voz: "Analiza si el ritmo
del arco 2 es muy lento". `/modelo` para cambiar el predeterminado.

**Qué aprendiste: confirmar antes de gastar.** Cuando una acción es cara (un modelo grande), el patrón es
"preparar → mostrar costo → esperar confirmación → ejecutar": la preparación es local y gratis, y el pendiente
guarda exactamente lo que se mostró. Si falla, se devuelve el control al usuario con opciones, en vez de
decidir por él.

## 2026-09-28 — Análisis con Opus y Sonnet corregido; elección de esfuerzo

**Qué se hizo**
- **Diagnóstico** (el usuario probó y solo respondía GPT-6 Sol):
  - **Opus**: `HTTP 502 Thinking level "off" is not supported… Use one of: low, medium, high, xhigh, max`.
    Error mío: copié el `off` que acepta Haiku.
  - **Sonnet**: `Plugin LLM completion failed.`, 9 s después de arrancar Claude Code, sin más detalle en los logs.
    Con el mismo pedido (mismas notas, `off` y `low`) respondió bien: fue un fallo pasajero cuya causa el plugin
    tapaba (OpenClaw la guarda en `error.cause` y el plugin solo devolvía el mensaje de fuera).
- **Corrección**: niveles verificados por modelo en `config.yaml`; el plugin devuelve y registra la cadena de
  causas; tras un fallo se ofrece **"Reintentar con <modelo> · esfuerzo <x>"** además de los otros modelos.
- **Esfuerzo** (pedido del usuario): al pulsar un modelo, el mensaje cambia a botones con los esfuerzos que acepta
  (`✓ Bajo`, `Medio`, `Alto`, `Muy alto`, `Máximo`; Sonnet además `Sin razonamiento`). El análisis empieza al
  elegir el esfuerzo. Se guarda en el archivo (`esfuerzo:` en el frontmatter y en "**Modelo:**") y en el diario.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `config.yaml`, `core/app/config.py` | `esfuerzos` por modelo (el primero es el de por defecto); sin `off` en Opus |
| `core/app/acciones/analisis.py` | `ESFUERZOS`, `Opcion.esfuerzos`, `con_esfuerzo`, `lista_esfuerzos`, `nombre_esfuerzo`; esfuerzo en archivo y diario |
| `core/app/entradas/telegram_bot.py` | Paso de esfuerzo (`ef:`), reintento (`re:`), `reemplazar()` y `empezar_analisis()` |
| `openclaw/plugins/hub-puente/index.js` | `detalle()` recorre `error.cause`; `fallo()` lo devuelve y lo escribe en el log |
| `core/tests/test_analisis.py`, `core/tests/test_bot.py` | Pruebas del esfuerzo, esfuerzo inválido, reintento y voz |

**Decisiones y por qué**
- **Niveles por modelo en la config, no fijos en el código:** cada modelo acepta otros (Sonnet admite `off`, Opus
  no). Se averiguaron gratis pidiendo un nivel inválido: OpenClaw responde con la lista válida sin llamar al
  modelo. Con GPT-6 Sol el truco no sirve (acepta cualquier valor), así que se ofrecen los de OpenAI:
  low, medium, high, xhigh.
- **El menor esfuerzo va primero y marcado** (decisión 3); subirlo es una decisión explícita del usuario.
- **Reintentar no es cambiar de modelo:** un fallo pasajero se resuelve reintentando el mismo; sigue siendo el
  usuario quien lo pide.
- Tras un fallo se ofrecen siempre todos los modelos menos el que falló (`todas` en el pendiente).

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| Opus rechaza `off` | Esfuerzos por modelo; por defecto el menor aceptado (`low`) |
| El motivo real del fallo de Sonnet no llegaba ni a los logs | El plugin devuelve `mensaje <- causa <- causa` y lo escribe con `console.warn` |
| El verificador de Bash no respondió un rato | El usuario ofreció ejecutar los comandos; al volver Bash se leyó todo directo |

**Resultado:** 247 pruebas pasan (1 omitida), en `.venv` y en el contenedor. Prueba real con el código del bot y
las 9 notas de `webtoon` (~1.200 tokens): Opus (bajo) 26 s, Sonnet (sin razonamiento) 15 s, GPT-6 Sol (bajo) 11 s,
los tres OK. Opus `high` y Sonnet `max` también responden. El error provocado (Opus con `off`) llega completo.

**Cómo probarlo:** `/analisis busca contradicciones en la historia` → Opus 5.5 → Alto → respuesta y archivo en
`Analisis/` con "(esfuerzo alto)".

**Qué aprendiste: no tragarse las causas.** Envolver un error en otro más genérico ("completion failed") está bien
para clasificarlo, pero quien lo reporta debe recorrer la cadena (`error.cause`) y mostrarla: sin eso, un fallo
pasajero parece un error de configuración y no hay forma de distinguirlos.

## 2026-09-28 — Kokoro se descarga solo en un equipo nuevo (verificado por SHA-256)

**Qué se hizo**
- Al revisar si el repositorio basta para levantar el servidor en Windows apareció un hueco: Kokoro se había
  sacado a mano durante la prueba de voces y ningún script lo repetía. En un clon limpio, `voz` arrancaba sin voz.
- Ahora `voz`, al cargar Kokoro, llama a `asegurar_kokoro()`: si faltan, descarga `kokoro-v1.0.fp16.onnx` y
  `voices-v1.0.bin` de las publicaciones de kokoro-onnx, comprueba la huella SHA-256 de cada uno, guarda solo
  `jf_tebukuro` en `voces_jf_tebukuro.npz` y borra el paquete de 54 voces.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `voz/servidor.py` | `HUELLAS`, `descargar_verificado()` (temporal, SHA-256, escritura atómica) y `asegurar_kokoro()` |
| `voz/tests/test_servidor.py` | 3 pruebas sin red con URLs `file://`: descarga y extracción, huella distinta, archivo sin huella |
| `voz/Dockerfile`, `GUIA.md`, `README.md` | Explican que Whisper y Kokoro se descargan solos la primera vez |

**Decisiones y por qué**
- **En `voz` y no en `hub modelos`:** igual que Whisper, sin pasos manuales. Si falla la descarga, la
  transcripción sigue funcionando y el bot responde con texto (ya estaba así).
- **Huellas fijas en el código:** lo que baja de internet no se carga si no es exactamente el archivo verificado
  (protege de descargas cortadas o archivos alterados). Un archivo sin huella conocida no se descarga: se pide
  colocarlo a mano.
- **Biblioteca estándar (`urllib`, `hashlib`)**: sin dependencias nuevas.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| ¿La voz extraída es la misma que la elegida? | Comparada con `np.array_equal` contra la actual: idéntica (510×1×256, float32) |
| `grep` del sistema es `ugrep` y no aceptó algunas expresiones al revisar secretos | Escaneo con un script de Python |

**Resultado:** 12 pruebas de `voz` pasan. Prueba real en una carpeta vacía: descarga en 40 s, huella del modelo
igual a la local, voz de 522.516 bytes (igual que la actual) y Kokoro habló con esos archivos. `voz` reconstruido.

**Cómo probarlo:** en un equipo sin `modelos/kokoro/`, `./hub.sh arrancar` y `docker compose logs voz`:
"Descargando kokoro-v1.0.fp16.onnx…", "Voz jf_tebukuro guardada…", "Kokoro cargado…".

**Qué aprendiste: descargas reproducibles y verificadas.** Un archivo que "ya estaba en la carpeta" es una
dependencia invisible: funciona en tu equipo y falla en el siguiente. Automatizar su descarga con una huella
SHA-256 fija lo hace reproducible y seguro: se sabe exactamente qué archivo se usa y se rechaza cualquier otro.

## 2026-09-28 — `core` corre con el usuario del equipo (bóveda editable desde Obsidian y Syncthing)

**Qué se hizo**
- Antes de instalar Syncthing apareció un problema: toda la bóveda era de root (`core` corría como root; carpetas
  755, archivos 644). El usuario podía leerla pero no escribirla: Obsidian en la PC no podría editar las notas del
  bot y Syncthing (que corre como el usuario) fallaría al recibir cambios del móvil, la tablet o la laptop.
- Con el visto bueno del usuario, `core` corre ahora con su UID/GID. Se devolvieron los dueños de la bóveda,
  `datos/` y `modelos/hf` (en la bóveda eran 30 de 31 elementos; ahora ninguno es de root) y se verificó todo con el stack real.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `docker-compose.yml` | `user: "${HUB_UID:-1000}:${HUB_GID:-1000}"` y `HOME: /tmp` en `core` |
| `hub.sh` | Exporta `HUB_UID`/`HUB_GID` desde `id -u`/`id -g`; nuevo `permisos` (chown con Docker, sin `sudo`); `tests` sin caché de pytest |
| `hub.ps1` | `tests` sin caché de pytest (`/app` no es escribible) |
| `core/app/router/clasificador.py` | Entrena en una carpeta temporal dentro de `datos/router` y con `save_strategy="no"` |
| `.env.example` | `HUB_UID`/`HUB_GID` comentados, solo para quien use `docker compose` directo |
| `CLAUDE.md` | La decisión "contenedores como root" pasa a "core con el usuario del equipo" |

**Decisiones y por qué**
- **Solo `core`**: es el único que escribe en la bóveda y en `datos/`. `voz` y `ollama` escriben solo en sus
  carpetas de `modelos/`, que nadie edita a mano.
- **`HUB_UID` y no `UID`**: `$UID` es una variable de bash que no se exporta, así que Docker Compose no la ve.
  `hub.sh` la exporta; sin `hub.sh` se usa 1000, que es el primer usuario en Ubuntu. En Windows da igual: Docker
  Desktop no aplica dueños en las carpetas montadas.
- **`HOME=/tmp`**: el usuario 1000 no existe en la imagen; sin HOME, las librerías intentarían escribir en `/`.
- **`permisos` con Docker y no con `sudo`**: el grupo `docker` ya tiene ese poder; así no hace falta la clave.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| SetFit guarda checkpoints en `./checkpoints` (así apareció `core/checkpoints`, 1,4 GB) y `/app` ya no es escribible | `output_dir` temporal en `datos/router` + `save_strategy="no"`; se borra al terminar |
| pytest intenta crear `.pytest_cache` en `/app` | `-p no:cacheprovider` en `hub tests` |

**Resultado:** `core` corre como `uid=1000`. El latido, la base SQLite y el modelo reentrenado quedan a nombre del
usuario; 0 archivos de root en la bóveda, `datos/` y `modelos/hf`. 247 pruebas pasan (en `.venv` y en el
contenedor), chequeo "listo" y entrenamiento real en 197 s con 132 ejemplos.

**Cómo probarlo:** `ls -la ~/Boveda/_hub/servidor.json` (dueño: tu usuario); editar una nota del bot en Obsidian.

**Qué aprendiste: dueños de archivos y contenedores.** Un contenedor escribe en una carpeta montada con el UID
con el que corre, no con "el usuario de Docker". Si corre como root, todo lo que crea es de root en el equipo.
Fijar `user:` al UID del equipo hace que los archivos sean tuyos, siempre que el contenedor no necesite escribir
fuera de las carpetas montadas (de ahí `HOME=/tmp` y quitar los checkpoints de `/app`).

## 2026-09-29 — Laptop (Windows) preparada como servidor; plugin puente dentro de la imagen

**Qué se hizo**
- Auditoría de solo lectura (`AUDITORIA_ESTADO.md`) y, después, preparación de la laptop siguiendo la GUIA (secciones 3, 5 y 6).
- Windows: `core.autocrlf false` (3.4), suspensión con cargador en "nunca" (3.6, antes 15 min), Docker Desktop
  arrancado y GPU visible desde Docker (RTX 3050, 4 GB) (3.3), Syncthing Windows Setup v2.0.2 instalado por usuario
  con inicio al iniciar sesión (3.5; huella SHA-256 igual a la publicada en GitHub).
- `.env` de la laptop (`SERVIDOR_NOMBRE=laptop`, `VAULT_PATH=C:/Users/micha/Boveda`, `LAN_IP=0.0.0.0`,
  `COMPOSE_PROFILES=consulta`, token del gateway nuevo). Falta `TELEGRAM_TOKEN` y `TELEGRAM_USUARIOS`.
- Imágenes construidas en Windows (`core` 2,4 GB, `voz` 0,9 GB, `openclaw` 5 GB), modelo base descargado, router
  entrenado (120 ejemplos, 308 s), `voz` con Whisper `small` y Kokoro descargado y verificado.
- OpenClaw: onboarding, `config patch` y cadena de modelos (`gpt-6-luna` → `claude-haiku-4-5`). Falta iniciar sesión.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `openclaw/Dockerfile` | Copia `plugins/hub-puente` en la imagen (root, sin escritura para otros) |
| `docker-compose.yml` | Ya no monta `./openclaw/plugins/hub-puente` |
| `openclaw/README.md`, `openclaw/fragmento-config.json5` | Comentarios del montaje actualizados |
| `AUDITORIA_ESTADO.md` (nuevo) | Estado del proyecto antes de preparar la laptop |

**Decisiones y por qué**
- **Plugin copiado y no montado:** Docker Desktop en Windows monta las carpetas con permisos 777 y OpenClaw rechaza
  un plugin escribible por cualquiera ("blocked plugin candidate: world-writable path"). Copiarlo en la imagen da el
  mismo resultado en Ubuntu y en Windows. El precio: tras cambiar el plugin hay que `docker compose build openclaw`.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| OpenClaw bloqueaba `hub-puente` en Windows (modo 777) | Plugin dentro de la imagen; el log dice `3 plugins: anthropic, hub-puente, openai` |
| `modelos/hf` ocupa 4,1 GB y no ~470 MB | El script baja todas las variantes del modelo base; pendiente de revisar (no bloquea) |

**Resultado:** 247 pruebas de `core` (1 omitida) y 12 de `voz` pasan en la laptop. Chequeo: todo OK salvo
`TELEGRAM_TOKEN`. Con el router entrenado, 12 de 15 frases de prueba se resuelven sin tokens (las 15 bien clasificadas).

**Cómo probarlo:** `.\hub.ps1 chequeo` y `docker compose logs openclaw | findstr listening`.

**Qué aprendiste: los permisos no viajan entre sistemas.** NTFS no tiene los permisos de Linux; al montar una carpeta
de Windows en un contenedor, Docker inventa unos (777). Si un programa revisa los permisos por seguridad, lo que se
copia dentro de la imagen es más predecible que lo que se monta.

## 2026-09-29 — Entrenamiento del router compartido por Syncthing y lista de entrenamiento

**Qué se hizo**
- Lo que aprende el router (`correcciones.yaml`, `aprendidos.yaml`) se comparte entre la PC y la laptop con una
  segunda carpeta de Syncthing, `hub-router` (= `datos/router`). El modelo no viaja: cada equipo hace `/reentrenar`.
- Carpeta `hub-router` creada en el Syncthing de la laptop (aún sin compartir: la PC está apagada).
- Se midieron 97 frases candidatas con el router de la laptop (0 tokens, sin IA) y se dejaron en
  `lista_entrenamiento.md` solo las 29 que confunde o duda, más 3 que no se deben enviar.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `datos/router/.stignore` (nuevo) | Syncthing ignora `modelo` y los temporales del entrenamiento |
| `.gitignore` | Excepción para subir solo ese `.stignore` de `datos/` (así llega a la PC por git) |
| `lista_entrenamiento.md` (nuevo) | Frases por prioridad, respuesta esperada y qué cuesta cada botón |
| `README.md` | §2: carpeta `hub-router` |

**Decisiones y por qué**
- **Carpeta aparte y no la bóveda:** la bóveda va al móvil, y el router solo lo usan la PC y la laptop.
- **Sin cambios de código:** solo un equipo es servidor a la vez (latido y 409), así que nunca escriben los dos
  los mismos archivos. Solo hay riesgo de choque la primera vez, si los dos equipos ya tienen su propio archivo.
- **La lista se midió antes de escribirla:** de las frases "obvias", casi todas ya se clasificaban con > 0,9 y no
  enseñarían nada. Los fallos se concentran en consultas sin signo de pregunta ("me puedes decir…", "quisiera
  saber…"), análisis en forma de opinión ("crees que encaja…") y frases cortas de solo sustantivos.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| Si el router ejecuta con seguridad, no hay botones para corregirlo | Esas 3 frases van a la sección 4 de la lista: hay que añadirlas a `ejemplos.yaml` a mano. "Máscaras de zorro" generaría una imagen |

**Primera unión PC ↔ laptop (una sola vez).** En la laptop, **antes** de aceptar `hub-router` desde la PC:
```powershell
Rename-Item datos\router\aprendidos.yaml aprendidos-laptop.yaml
if (Test-Path datos\router\correcciones.yaml) { Rename-Item datos\router\correcciones.yaml correcciones-laptop.yaml }
```
Aceptar la carpeta, esperar *Actualizada* y unir (las repetidas no se duplican):
```powershell
@'
from pathlib import Path
from app.router import ejemplos as e
c = Path("/datos/router")
for x in e.leer_correcciones(c, "correcciones-laptop.yaml"): e.guardar_correccion(c, x["texto"], x["accion"])
for x in e.leer_correcciones(c, "aprendidos-laptop.yaml"): e.guardar_aprendido(c, x["texto"], x["accion"])
print(len(e.leer_correcciones(c)), "correcciones,", len(e.leer_aprendidos(c)), "aprendidos")
'@ | docker compose exec -T core python -
Remove-Item datos\router\*-laptop.yaml
```
Y `/reentrenar`. Probado sobre una copia temporal: une y no repite.

**Resultado:** `git check-ignore` confirma que solo sube `datos/router/.stignore`; Syncthing indexa en
`hub-router` únicamente `aprendidos.yaml` (192 bytes), no el modelo.

**Cómo probarlo:** en Syncthing, `hub-router` → *Archivos locales*: solo los `.yaml`.

**Qué aprendiste: medir antes de entrenar.** Un ejemplo que el modelo ya acierta con seguridad no le aporta nada.
Probar primero las frases sin gastar tokens muestra dónde está el hueco de verdad, y ahí se concentra el
esfuerzo (y los tokens).

## 2026-09-29 — Syncthing con PC, laptop, móvil y tablet: conflictos resueltos

**Qué se hizo**
- Bóveda compartida entre PC (`3vil4n0n`), laptop, móvil (Pixel 10 Pro XL) y tablet (SM-X920), y carpeta del router
  solo entre PC y laptop (ID `axe3j-2cugq`, creado por la PC; da igual que no sea `hub-router`).
- Conflictos revisados uno a uno antes de borrar nada:
  - router: los aprendidos de la PC (4) quedaron en una copia de conflicto porque no se renombraron antes de compartir;
    se unieron con `guardar_aprendido` (5 en total, sin repetidos) y luego se borró la copia;
  - `_hub/servidor.json` (×3): latido viejo de la PC; `.obsidian/core-plugins.json`: el móvil añadía `"webviewer": false`;
  - `.obsidian/workspace-mobile.json`: móvil y tablet escriben cada uno sus pestañas abiertas.
- El `.stignore` de la bóveda pasa a ignorar también las copias de conflicto de esos archivos de interfaz.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/boveda/proyectos.py` | `STIGNORE`: `.obsidian/workspace.*` y `.obsidian/workspace-mobile*` (antes, el nombre exacto) |

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| La copia `workspace-mobile.sync-conflict-….json` no coincidía con `.obsidian/workspace-mobile.json` y viajaba a todos | Patrón con `*`. `workspaces.json` (plugin Workspaces) sigue sincronizándose |
| Si se ignora un archivo antes de borrarlo, el borrado no se propaga | Primero borrar y esperar 100 % en todos los equipos; después cambiar el `.stignore` |
| `core` solo crea el `.stignore` si no existe | En equipos que ya lo tienen hay que editarlo a mano (laptop hecho; PC pendiente) |

**Resultado:** 0 conflictos; bóveda al 100 % en PC, móvil y tablet. 50 pruebas (`test_boveda`, `test_bot`) pasan con
el código nuevo montado en el contenedor.

**Qué aprendiste: un conflicto de Syncthing también es un archivo.** Su nombre cambia (`.sync-conflict-…`), así que
un patrón exacto no lo cubre y se sincroniza como cualquier otro. Y los archivos de estado de cada dispositivo
(pestañas abiertas) no deberían viajar: cada equipo tiene el suyo.

## 2026-09-29 — Día 6 (parte 1): cortacircuitos en la cadena de imágenes; Syncthing emparejado

**Qué se hizo**
- Syncthing emparejado por el usuario entre la PC, el móvil y la tablet, con Obsidian abierto en ambos
  dispositivos. Verificado en la PC: el servicio está activo, arranca solo, sigue corriendo sin sesión (*linger*)
  y `.stfolder` está en la bóveda. La laptop queda para el despliegue.
- Cortacircuitos en `proveedores/cadena.py`. Tras 3 fallos seguidos (`cortacircuitos` en `config.yaml`), un
  proveedor de imágenes queda en pausa 5 minutos y la cadena lo salta sin llamarlo. Pasada la pausa se prueba
  una vez: si vuelve a fallar, otra pausa; si responde, la cuenta vuelve a cero. `/diagnostico` y los motivos de
  `SinProveedores` muestran "en pausa hasta las HH:MM tras N fallos seguidos (último: …)".

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/estado/db.py` | Tabla `proveedor_estado` (fallos seguidos, pausa hasta, último motivo) y sus dos métodos |
| `core/app/proveedores/cadena.py` | Clase `Cortacircuitos`; `CadenaImagenes` la usa si se la pasan; `crear_cadena(..., estado=)` la arma desde `config.yaml` |
| `core/app/main.py` | Pasa el estado SQLite a `crear_cadena` |
| `core/tests/test_imagenes.py` | 4 pruebas: pausa y salto, motivo y reinicio tras un éxito, "falta configurar" no cuenta, lectura de `config.yaml` |

**Decisiones y por qué**
- **Estado en SQLite y no en memoria:** si el bot se reinicia mientras un proveedor está caído, la pausa se
  mantiene. Es estado operativo, no contenido: cumple la decisión 1.
- **Tabla con nombre genérico (`proveedor_estado`):** la cuota diaria agotada (pausa hasta 00:00 UTC) y el saldo
  agotado (pausa hasta `/reactivar`) se guardarán ahí mismo en la próxima parte.
- **"Falta configurar" no cuenta como fallo:** no es culpa del proveedor, y pausarlo ocultaría el motivo real.
- **El cortacircuitos es opcional (`None` por defecto):** la cadena sin estado se comporta como antes, así que
  las pruebas existentes no cambiaron.
- **Solo imágenes por ahora:** la consulta por OpenClaw ya tiene su propia cadena (ChatGPT mini → Haiku) dentro
  del plugin. Llevar el cortacircuitos ahí queda para la próxima parte, y en el análisis nunca se cambia de
  modelo solo (decisión 4).
- **Conflictos de Syncthing en `Ideas.md` y compañía:** el usuario decidió crear después del MVP una función que
  los evite y detecte. La sección "Conflictos" de `GUIA.md` está desactualizada: dice que el bot siempre crea
  archivos nuevos, y hoy agrega al final de archivos por tipo.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| Probar una pausa de 5 minutos sin esperarlos | Reloj inyectable (`reloj=`) y un reloj falso en las pruebas que se adelanta a mano |

**Resultado:** 251 pruebas de `core` pasan (1 omitida; antes eran 247). La advertencia de `starlette.testclient`
viene de la librería y ya estaba. **Falta reconstruir `core`** para que el bot en marcha use el cambio.

**Cómo probarlo:** `docker compose build core && docker compose up -d core`. Para ver el cortacircuitos sin gastar
cuota: parar OpenClaw (`docker compose stop openclaw`), pedir `/img gato` tres veces (falla rápido y guarda la idea como nota en la bóveda) y una cuarta:
`./hub.sh logs` muestra "Cortacircuitos: chatgpt en pausa 5 min" y `/diagnostico`, "en pausa hasta las …".
Al terminar, `docker compose start openclaw`.

**Qué aprendiste: el cortacircuitos (*circuit breaker*).** Cuando un servicio está caído, insistir solo hace
esperar al usuario y carga más al servicio. El cortacircuitos "salta" tras varios fallos seguidos: durante un
tiempo ni se intenta y se falla al instante. Después deja pasar una prueba (estado "semiabierto"): si funciona,
se cierra; si no, vuelve a abrirse. El nombre viene de los interruptores eléctricos.

## 2026-09-29 — Rama `laptop-servidor` integrada en la PC; prueba de sincronización entre los 4 equipos

**Qué se hizo**
- Se trajo la rama `laptop-servidor` (4 commits de la laptop: plugin puente dentro de la imagen, carpeta `hub-router`,
  `lista_entrenamiento.md`, `AUDITORIA_ESTADO.md` y el `.stignore` con `*`). Salía de `84e0523`, igual que `main`,
  así que `main` avanzó con *fast-forward* (sin commit de fusión).
- El cortacircuitos (sin confirmar en la PC) se guardó en un *stash* antes y se recuperó después.
- `.stignore` de la bóveda de la PC actualizado a mano con el texto nuevo de `proyectos.py` (pendiente según la
  entrada de Syncthing), tras comprobar que no quedaba ningún `.sync-conflict`.
- El usuario confirma que la laptop ya funciona como servidor: tiene el token de Telegram y los inicios de sesión de
  ChatGPT y Claude (OAuth) en OpenClaw, y lo probó con el bot.
- **Prueba de sincronización** desde la PC, con `syncthing cli` (sin leer la clave de la API):
  - Conexiones: laptop, tablet y móvil conectados directo por la red local, sin errores. La PC usa Syncthing 1.27;
    los otros, 2.1 (son compatibles).
  - Se creó `_hub/prueba-sync.md` en la bóveda y `prueba-sync.txt` en `datos/router`. La bóveda llegó a laptop y
    tablet en segundos y al móvil en 1-2 min (Android agrupa los cambios para ahorrar batería). El del router llegó
    solo a la laptop: es lo correcto, esa carpeta no se comparte con los móviles.
  - Se borraron los dos archivos: el borrado llegó a todos en 20 s.
  - Dirección contraria: en la PC hay archivos cuya última versión viene del móvil (`.obsidian/core-plugins.json`)
    y de la laptop (`_hub/servidor.json`), y la PC no está desfasada en ninguno.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `docs/BITACORA.md` | Conflicto resuelto: las 3 entradas de la laptop y después la del cortacircuitos |
| `~/Boveda/.stignore` (fuera del repo) | Ignora `.obsidian/workspace.*` y `.obsidian/workspace-mobile*` |
| Syncthing de la PC (`gui debugging`) | Se encendió solo durante la prueba y se volvió a apagar |

**Decisiones y por qué**
- **`--ff-only` y no `merge` normal:** si la rama hubiera divergido, el comando falla en vez de crear un commit de
  fusión sin permiso. Aquí no divergía.
- **Depuración de Syncthing encendida un rato en vez de usar su API REST:** la API pide la clave de `config.xml`
  y la regla del proyecto es no leer claves. `syncthing cli` se autentica solo; `cli debug file` (que dice qué
  equipos tienen la versión actual de un archivo, `availability`) necesita el modo depuración, así que se encendió
  para la prueba y se apagó al terminar.
- **La entrada del cortacircuitos va al final:** se confirma después de los commits de la laptop, y así el orden de la
  bitácora coincide con el de git.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| `docs/BITACORA.md` cambiado en los dos lados (ambos agregaban al final) | Se tomó la versión de la rama y se le agregó la entrada local; sin marcas de conflicto |
| `syncthing cli debug file` respondía 403 ("Debugging disabled") y la primera prueba parecía no sincronizar | Era la consulta, no la sincronización: `syncthing cli config gui debugging set true` y después `false` |

**Resultado:** 251 pruebas de `core` pasan (1 omitida) con el código de la rama y el cortacircuitos juntos.

**Confirmar y subir (lo ejecuta el usuario):**
```bash
git status -sb                      # qué cambió y cuántos commits vamos por delante de GitHub
git add core/app/estado/db.py core/app/proveedores/cadena.py core/app/main.py \
        core/tests/test_imagenes.py docs/BITACORA.md
git diff --cached --stat            # revisar lo que entra en el commit (solo esos 5 archivos)
git commit -m "Cortacircuitos en la cadena de imágenes (día 6, parte 1)" \
  -m "Integra la rama laptop-servidor en la bitácora y registra la prueba de sincronización." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push                            # sube los 4 commits de la laptop y este
git push origin --delete laptop-servidor   # opcional: la rama remota ya está dentro de main
```
- `git add` elige qué cambios entran en el próximo commit (el "área de preparación"). Se nombran los archivos uno
  por uno para no subir nada por accidente.
- `git commit` guarda esa foto en el historial local. Cada `-m` es un párrafo del mensaje; el último, la autoría.
- `git push` envía a GitHub los commits locales que aún no tiene. Como `main` avanzó por *fast-forward*, no hace
  falta forzar nada.
- `git push origin --delete laptop-servidor` borra la rama en GitHub. No se pierde nada, porque sus commits ya
  están en `main`.

En la laptop, después: `git switch main`, `git pull` y `git branch -d laptop-servidor` (`-d` se niega a borrar si
la rama tuviera algo que no está en `main`). Luego `.\hub.ps1 arrancar` para reconstruir `core` con el cortacircuitos.

**Cómo probarlo:** `git log --oneline -6` muestra los 4 commits de la laptop sobre `84e0523`. Al arrancar,
`./hub.sh arrancar` reconstruye OpenClaw con el plugin dentro; `docker compose logs openclaw | grep hub-puente` debe
listarlo entre los 3 plugins.

**Qué aprendiste: *fast-forward*.** Si tu rama no tiene commits propios desde que salió la otra, fusionar es solo mover
la etiqueta `main` hacia adelante: no hay nada que combinar ni commit nuevo. Los conflictos vienen de los cambios sin
confirmar, por eso se guardan antes en un *stash* y se reaplican después.

## 2026-09-29 — Bóveda vaciada tras las pruebas; diagnóstico de las notas mal ubicadas

**Qué se hizo**
- Revisión de las últimas notas: el router **acertó** la acción (las 4 eran notas); lo que falló fue el destino y el
  contenido. "Anota en el archivo referencia elfa…" terminó en `Ideas.md`/`Historia.md` con la orden completa como
  texto, y "no la agregues a historia, agrégala a referencia elfa" se guardó como otra nota (y quedó en
  `aprendidos.yaml` como ejemplo de `nota`). Causas: el bot no sabe escribir en un archivo existente que se le nombra,
  no separa la orden del contenido y no entiende correcciones de destino. `Referencia elfa.md` la creó el usuario en
  Obsidian, en la raíz (ubicación por defecto de las notas nuevas).
- A pedido del usuario, bóveda vaciada: se borraron `Proyectos/` (webtoon), `Diario/`, `Referencia elfa.md`, la imagen
  suelta de la raíz y `.stversions`. Respaldo previo en `~/Respaldos/boveda-pruebas-2026-09-29.tar.gz` (65 entradas).
- Borrado confirmado por los 4 equipos con `syncthing cli debug file` (modo depuración encendido y apagado).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `~/Boveda` (fuera del repo) | Solo quedan `.stfolder`, `.stignore`, `.obsidian`, `_hub/` (latido y plantillas) y `00-Bandeja/` vacía |
| `~/Respaldos/boveda-pruebas-2026-09-29.tar.gz` | Copia completa anterior a la limpieza |

**Decisiones y por qué**
- **Se conservan `.stfolder`, `.stignore`, `.obsidian` y `_hub/`:** sin el primero Syncthing deja de sincronizar la
  carpeta; `.obsidian` es la configuración de Obsidian en todos los equipos; `_hub/servidor.json` es el latido que
  impide dos servidores a la vez.
- **Respaldo antes de borrar:** el borrado se propaga a todos los equipos y no tiene vuelta atrás desde Syncthing.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| El bot en la laptop recuerda "webtoon" como proyecto activo; una nota lo recrearía a medias | Empezar con `/proyecto nuevo <nombre>` |

**Resultado:** bóveda vacía en los 4 equipos; ninguna prueba de código afectada (no hubo cambios de código).

**Cómo probarlo:** en Obsidian de cualquier equipo, solo se ve `00-Bandeja` (y `_hub`).

**Qué aprendiste: en una carpeta sincronizada, borrar es global.** Syncthing no distingue entre "limpiar mi copia" y
"borrar para todos": propaga el borrado como cualquier otro cambio. Por eso el respaldo se hace fuera de la carpeta
sincronizada, y se conservan los archivos que la hacen funcionar (`.stfolder`).

## 2026-09-29 — Router: medición honesta, 600 ejemplos en el estilo del usuario y pruebas en GPU

**Qué se hizo**
- Conjunto de **prueba** (`prueba.yaml`, 150 frases: reales de la bóveda, las de `lista_entrenamiento.md` y nuevas) y,
  después de ajustar con él, una **prueba ciega** (`prueba_ciega.yaml`, 120 frases más difíciles) que no se usó para
  decidir nada. Ninguna frase de prueba se entrena (lo vigila una prueba automática).
- `scripts/evaluar_router.py`: mide reglas + SetFit sin IA. Además de los aciertos cuenta **"ejecuta mal"** (seguro,
  equivocado y sin preguntar: el peor error) y **"duda"** (botones o IA). Entrena candidatos en
  `datos/router-candidatos/` sin tocar el modelo del bot ni la carpeta que comparte Syncthing.
- `ejemplos.yaml` de 20 a **100 frases por acción**, escritas como habla el usuario: dictado, muletillas, sin tildes
  ni puntuación, errores de Whisper, notas que nombran un archivo, consultas sin "?", análisis como opinión.
- Entorno aparte `.venv-gpu` (torch 2.14.0+cu130) solo para experimentar en la PC; la imagen de `core` sigue en CPU.

**Resultados (prueba ciega, 120 frases)**

| Modelo | Ejemplos | Acierta | Ejecuta mal | Duda | Entrena | Responde (CPU) |
| --- | --- | --- | --- | --- | --- | --- |
| Actual (MiniLM) | 132 | 70,8 % | 12 | 41 | 197 s CPU | ~18 ms |
| C1 MiniLM | 375 | 87,5 % | 11 | 11 | 583 s CPU | — |
| C2 MiniLM | 615 | 90,8 % | 9 | 7 | 180 s GPU | 20 ms |
| C4 MiniLM, 40 iteraciones | 615 | 91,7 % | 8 | 4 | 363 s GPU | ~20 ms |
| **C3 mpnet, vocabulario congelado** | 615 | **94,2 %** | **7** | 2 | 392 s GPU | 43 ms |
| C5 mpnet, 40 iteraciones | 615 | 95,0 % | 6 | 1 | 784 s GPU | 43 ms |

En la primera prueba (150 frases) el actual acertaba el 76,7 % y C2 a C5, entre el 98,7 y el 99,3 %.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/datos/ejemplos.yaml` | 600 ejemplos (100 por acción) |
| `core/app/router/datos/prueba.yaml`, `prueba_ciega.yaml` (nuevos) | Frases de evaluación; nunca se entrenan |
| `core/scripts/evaluar_router.py` (nuevo) | Mide el router y entrena candidatos |
| `core/app/router/clasificador.py` | `entrenar()`: `epocas`, `congelar_vocabulario`; los metadatos guardan iteraciones, épocas y dispositivo |
| `core/tests/test_evaluar_router.py` (nuevo) | Pruebas y ejemplos no se solapan; cálculo de "ejecuta mal" y "duda" |
| `.gitignore` | Ignora `.venv-gpu/` |

**Decisiones y por qué**
- **Dos pruebas y no una:** al corregir los errores de una prueba se le termina "enseñando el examen". La ciega mide de
  verdad; por eso da números más bajos.
- **Vocabulario congelado en mpnet:** su tabla de palabras (250.000 × 768) son ~190 de sus 278 M de parámetros; el
  optimizador guarda varias copias y no cabe en 4 GB. Con 600 frases no hay nada que aprenderle a esa tabla.
- **Los datos pesaron más que el modelo:** de 132 a 615 ejemplos, +20 puntos; de MiniLM a mpnet, +3,4; duplicar
  iteraciones, +1.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| El índice cu128 de PyTorch llega solo hasta 2.11 | Índice cu130 (CUDA 13.0, igual que el driver 580; la GTX 1650 es Turing, 7.5) |
| Memoria llena en la GPU con mpnet | Vocabulario congelado y `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` |
| Memoria llena al evaluar tras entrenar, y con MiniLM a 40 iteraciones | El script ya no carga el modelo del bot cuando evalúa un candidato y libera la GPU antes de evaluar |
| Reinicio de la sesión a mitad del entrenamiento | Los procesos en segundo plano siguieron; resultados en `datos/router-candidatos/*/evaluacion.json` |

**Temperaturas (PC, entrenando en GPU, 17:18-17:25):** GPU máx. 77 °C (99 % de uso, limitada por potencia a 75 W,
no por calor); CPU (paquete) máx. 85 °C con un solo núcleo ocupado; sensor de la placa máx. 84 °C. En reposo:
GPU 50 °C, CPU 59 °C. Sin riesgo, pero el calor de la GPU se queda en la caja.

**Resultado:** 257 pruebas de `core` pasan (1 omitida; 6 nuevas). El modelo del bot no se cambió todavía.

**Cómo probarlo:**
```bash
cd core && HF_HOME=../modelos/hf ../.venv/bin/python -m scripts.evaluar_router --carpeta ../datos/router \
  --config ../config.yaml --prueba app/router/datos/prueba_ciega.yaml --modelo ../datos/router-candidatos/c3-mpnet-gpu --errores
```

**Qué aprendiste: el conjunto de prueba debe ser ciego.** Si miras los errores de una prueba y escribes ejemplos para
corregirlos, el modelo mejora en esa prueba aunque no mejore de verdad. Por eso se separa una prueba que nunca se mira
al ajustar: es la única que dice cómo le irá con frases nuevas.

## 2026-09-29 — Reentreno seguro: configuración elegida, prueba real en CPU y control de calidad

**Qué se hizo**
- mpnet con **10 iteraciones** (en vez de 20) rinde lo mismo en la prueba ciega (93,3 % y 5 errores graves en GPU,
  contra 94,2 % y 7) y tarda la mitad. Queda como configuración en `config.yaml` (`router.entrenamiento`).
- **Prueba real en CPU** (como `/reentrenar` en el contenedor): **13 min 48 s**, 92,5 % en la prueba ciega, 6 errores
  graves. Congelar el vocabulario también acelera la CPU (la estimación previa de 40-50 min era mala).
- **Control de calidad del reentreno:** antes de reemplazar el modelo, el nuevo se mide con las ~270 frases de prueba
  y se compara con el que tiene cargado el bot. Si acierta más de 2 puntos menos o tiene más de 2 errores graves de más
  (o, sin modelo previo, acierta menos del 80 %), se descarta y el bot sigue con el anterior. El bot informa
  "acierta el 93 % (antes, 71 %)" o el motivo del descarte.
- `./hub.sh modelos` baja el modelo base que diga `config.yaml`.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/evaluacion.py` (nuevo) | Mide un modelo (aciertos, errores graves) y decide si es aceptable |
| `core/app/router/clasificador.py` | `ModeloRechazado`; `entrenar(control=)` mide el nuevo antes del cambio; usa el modelo en memoria |
| `core/app/router/cascada.py` | `reentrenar()` con la configuración de `config.yaml` y el control; saca de la medición las frases de prueba que el usuario corrigió |
| `config.yaml`, `core/app/config.py` | `router.entrenamiento`: mpnet, 10 iteraciones, 1 época, vocabulario congelado |
| `core/app/entradas/telegram_bot.py` | `/reentrenar` informa la calidad o el descarte (también por voz) |
| `core/scripts/entrenar_router.py`, `descargar_modelos.py`, `evaluar_router.py` | Misma configuración; resultado de la medición |
| `core/tests/test_evaluar_router.py`, `test_router_local.py`, `test_bot.py` | 7 pruebas nuevas del control y de los mensajes |

**Decisiones y por qué**
- **Tolerancia de 2 puntos y 2 errores graves:** entre dos entrenamientos iguales el azar mueve una o dos frases; sin
  tolerancia se descartarían modelos buenos.
- **Comparar con el modelo cargado y no con un número guardado:** si cambian las frases de prueba, la comparación
  sigue siendo justa (los dos se miden con las mismas).
- **Frases de prueba corregidas por el usuario salen de la medición:** si no, el modelo "se sabría el examen".

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| Entrenando en CPU, el i5-12400F llegó a **100 °C** (media 90 °C, 6 de 42 lecturas ≥ 95 °C); en reposo, 57-60 °C | El procesador se frena solo y no se daña, pero el disipador parece justo. Pendiente: limitar los hilos del entrenamiento |

**Resultado:** 264 pruebas de `core` pasan (1 omitida). El modelo del bot todavía no se cambió.

**Qué aprendiste: una puerta de calidad antes de desplegar.** Entrenar produce un modelo distinto cada vez, y no siempre
mejor. Medirlo con un examen fijo antes de ponerlo en uso (y quedarse con el anterior si empeora) convierte el
reentrenamiento en algo que se puede hacer sin miedo.

## 2026-09-29 — Intérprete con GPT como prioridad; SetFit para lo rígido y de respaldo

**Qué se hizo**
- Prueba del usuario con el bot (mpnet ya instalado): el router **acertó casi siempre la acción**, pero falló en
  **entender**: "dentro de la ficha de *Carito* vas a colocar…" fue a `Historia.md` con la orden entera (la ficha
  era *Karito*: Whisper escribe distinto), "esa imagen no me gusta, hazla anime" se guardó como nota, "vamos a crear
  un proyecto nuevo…" como tarea, la ficha de un personaje nuevo quedó sin descripción y la imagen se llamó
  "ensename1". Son problemas de comprensión (destino, contenido, contexto, nombres), no de clasificación.
- Decisión del usuario: **GPT con prioridad** para interpretar los mensajes libres y **SetFit con los comandos
  rígidos** y como respaldo. Nuevo `router/interprete.py`: ChatGPT (`gpt-6-luna`, solo ese modelo) recibe el mensaje
  y un contexto corto (proyecto, nombres de archivos, fichas con un resumen, última acción del bot) y devuelve JSON
  con acción, confianza, contenido sin la orden, destino, tipo, personaje, descripción, prompt y nombre de imagen,
  proyecto. Acciones nuevas: `rehacer_imagen`, `personaje`, `proyecto`, `mover_nota`.
- En el bot: rígido (local, sin tokens) → intérprete → si GPT no responde, router local **sin IA** → botones.
  Confianza de GPT < 0,6 → botones. Lo que GPT decide donde SetFit fallaba o dudaba se guarda como aprendido.
- "No ahí, ponla en X" **copia** la última nota a X y avisa dónde quedó la anterior: el bot nunca borra (decisión 6).
- Limpieza: bóveda vaciada otra vez (respaldo `~/Respaldos/boveda-pruebas-2026-09-29-b.tar.gz`); quitados de
  `aprendidos.yaml` "crear un proyecto…" → tarea y "no la agregues a historia…" → nota; borrados los modelos
  candidatos (~5 GB; quedan sus mediciones y el respaldo del MiniLM).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/interprete.py` (nuevo) | Contexto, llamada a GPT, extracción del JSON (un reintento), validación de destinos |
| `core/app/entradas/telegram_bot.py` | `orden_rigida`, `por_interprete`, `aplicar`, `guardar_interpretada`, `mover_nota`; contexto de la última acción; `/estado` y `/ayuda` |
| `core/app/boveda/proyectos.py` | `agregar_a_archivo()` (solo agrega, dentro de la bóveda); archivo propio con título |
| `core/app/acciones/personajes.py` | `fichas()` del proyecto |
| `core/app/acciones/imagenes.py` | `crear(prompt=, nombre=)` con lo que decide GPT |
| `core/app/router/cascada.py` | `decidir(sin_ia=)`, `aprender_de()` |
| `core/app/main.py`, `config.yaml`, `core/app/config.py` | `router.interprete` (activo, timeout 20 s, 400 tokens de salida) |
| `CLAUDE.md` | Decisión 2 actualizada |
| `core/tests/test_interprete.py` (nuevo) | 19 pruebas: validación, contexto, gateway, y el bot de punta a punta |

**Decisiones y por qué**
- **Solo ChatGPT, sin Haiku de respaldo:** Haiku por Claude Code cuesta ~3.600 tokens por mensaje; para eso está SetFit.
- **El destino se elige de una lista real:** el modelo nunca da una ruta; si nombra algo que no está, se ignora.
- **La ficha solo sirve para los prompts de imagen:** en las notas, GPT omitía datos que ya estaban en la ficha y
  agregaba otros de la ficha. Se le prohibió: el contenido sale solo del mensaje, completo.
- **Copiar en vez de mover:** la decisión 6 (nunca se borra) se mantiene sin excepciones.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| Una respuesta de GPT no fue JSON válido | Se extrae el `{…}` aunque venga con texto; si no hay, un reintento |
| "¿Te parece bien que la villana…?" salía como consulta | Descripciones: análisis = opinión sobre *su* historia (lee sus notas); consulta = pregunta general |
| Instrucciones de ~600 tokens | Reescritas: ~500 tokens de entrada por mensaje (antes ~700) |
| GPT perdía "tiene 200 años" (ya estaba en la ficha) e inventaba la edad en otra descripción | "Solo del mensaje, sin omitir aunque esté en la ficha, sin agregar de la ficha" |
| La consulta respondía dentro de `contenido` | En consulta y análisis, contenido vacío |
| GPT eligió la ficha como archivo | El bot la trata como ficha (va a "## Notas") |

**Resultado:** 283 pruebas de `core` pasan (1 omitida). Con ChatGPT real y las 11 frases del usuario de hoy: 11 de 11
bien, en dos repeticiones; ~500 tokens de entrada y 40-100 de salida (170 al escribir un prompt de imagen), 2-4 s.

**Cómo probarlo:** `/proyecto nuevo Webtoon`, "crea un personaje llamado Karito, una villana zorro", "en la ficha de
Carito anota que tiene 200 años", "enséñame cómo sería con armadura corta", "no me gusta, hazla estilo anime".
`./hub.sh logs` muestra por mensaje: acción de GPT, lo que habría dicho SetFit y el tipo de destino (sin el texto).

**Qué aprendiste: clasificar no es entender.** Un clasificador elige entre unas pocas cajas; el usuario, en cambio,
habla de *dónde*, *qué*, *a quién* y *lo de antes*. Para eso hace falta un modelo de lenguaje con contexto, pero
atado: salida en JSON, destinos elegidos de una lista real y validación de todo lo que devuelve.

## 2026-09-29 — Intérprete más inteligente: `gpt-6-sol` e instrucciones de rutas y notas

**Qué se hizo**
- Revisión de la segunda prueba del usuario (historia de Kael): la trama iba a `Ideas.md` en vez de `Historia.md`,
  "el protagonista se va a llamar Kael…" era una nota y no una ficha, "crea la ficha de Kael" la dejaba sin
  descripción (los datos estaban en el mensaje anterior), la descripción de una ficha existente iba a "## Notas" y
  "el estilo del webtoon…" terminó al final de `_proyecto.md` (el índice del proyecto).
- **Instrucciones:** definición de cada tipo de nota (historia = trama, personajes, mundo; producción = estilo de
  dibujo, formato, publicación…); presentar un personaje con nombre crea su ficha; "crea su ficha" usa la última acción.
- **Código:** `_proyecto.md` y `tareas.md` ya no se ofrecen como destino; si la ficha existe y su "## Descripción"
  está vacía, la descripción va ahí (`personajes.descripcion_vacia`).
- **Modelo configurable** (`router.interprete.modelo` y `razonamiento`) y **comparación** con 24 frases reales del
  usuario (acción, destino y datos que no se pueden perder):

| Configuración | Bien | Tokens por mensaje | Espera |
| --- | --- | --- | --- |
| `gpt-6-luna` bajo (anterior) | 23/24 | 672 + 63 | 2,8 s |
| `gpt-6-luna` medio | 24/24 | 672 + 128 | 6,0 s |
| **`gpt-6-sol` bajo (elegido)** | **24/24 y 24/24** | 672 + 65-71 | 3,6-5,0 s |
| `gpt-6-sol` medio | 24/24 | 672 + 127 | 5,9 s |

  ("Bien" cuenta como acierto elegir `Historia.md` por nombre en vez del tipo "historia": es el mismo archivo.)

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/interprete.py` | Tipos definidos, personajes presentados, referencias a lo anterior; sin `_proyecto.md` ni `tareas.md` |
| `core/app/acciones/personajes.py` | La descripción completa una "## Descripción" vacía |
| `core/app/main.py`, `config.yaml`, `core/app/config.py` | Modelo y razonamiento del intérprete: `gpt-6-sol`, bajo, 30 s, 500 tokens |
| `core/tests/test_interprete.py` | Pruebas de la descripción y de los destinos excluidos |

**Decisiones y por qué**
- **`gpt-6-sol` bajo y no razonamiento medio:** acierta igual o más con casi los mismos tokens; el razonamiento medio
  duplica los tokens de salida y la espera sin mejorar.
- **Claude descartado para cada mensaje:** por Claude Code suma ~3.700 tokens de instrucciones propias.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| `./hub.sh arrancar` no recreó `core` tras cambiar `config.yaml` | `docker compose up -d --no-deps --force-recreate core` |

**Resultado:** 284 pruebas de `core` pasan (1 omitida). Bot en marcha con `gpt-6-sol`. Costo de la comparación:
~120 llamadas, unos 90.000 tokens de la suscripción de ChatGPT.

**Qué aprendiste: primero las instrucciones, después el modelo.** La mayoría de los fallos venían de que el modelo no
sabía qué significa "historia" o "producción" para el usuario, ni que `_proyecto.md` es un índice. Con eso aclarado,
hasta el modelo chico acertaba 23 de 24; el grande cierra la diferencia y da margen para frases más raras.

## 2026-09-29 — Resumen: dónde quedó el router y qué funciones tiene

Entrada de referencia (cierre del día): cómo decide hoy el bot qué hacer con cada mensaje, dónde vive cada pieza y
qué queda pendiente. Reemplaza, como descripción del router, a las entradas anteriores del día 3 y del día 5.

**Recorrido de un mensaje** (texto o nota de voz ya transcrita por Whisper):

| Paso | Qué hace | Dónde | Tokens |
| --- | --- | --- | --- |
| 1. Comandos | `/nota`, `/tarea`, `/proyecto`, `/img`, `/analisis`… se ejecutan tal cual | `entradas/telegram_bot.py` | 0 |
| 2. Órdenes rígidas | Respuesta a una pregunta del bot (nombre de un personaje), "la imagen que se acaba de crear será X" | `orden_rigida()`, `reglas.renombrar_imagen` | 0 |
| 3. Órdenes habladas de prefijo fijo | "nota idea, …", "tarea: …", "cambia al proyecto X", "crea un proyecto nuevo…", "tareas", "estado" | `reglas.orden_hablada` | 0 |
| 4. **Intérprete (prioridad)** | `gpt-6-sol` (razonamiento bajo) entiende acción, destino, contenido sin la orden, personaje, prompt de imagen | `router/interprete.py`, `por_interprete()` | ~670 + ~70 |
| 5. Respaldo local | Si GPT no responde: reglas + SetFit (mpnet), **sin volver a llamar a la IA**; crear personaje o archivo propio por reglas | `router/cascada.py` (`decidir(sin_ia=True)`), `orden_directa()` | 0 |
| 6. Botones | Confianza baja (GPT < 0,6 o SetFit dudoso): el usuario elige; su elección se guarda como corrección | `resolver()`, `teclado_acciones()` | 0 |

**Acciones que entiende el intérprete**

| Acción | Qué hace el bot |
| --- | --- |
| `nota` | Guarda solo el contenido: en la ficha de un personaje ("## Notas"), en un archivo existente que se nombra, en un archivo nuevo si se pide, o por tipo (`Ideas.md`, `Historia.md`, `Produccion.md`) |
| `tarea` | Agrega a `tareas.md` |
| `consulta` | Responde con ChatGPT (con historial corto) |
| `analisis` | Modo análisis con botones (modelo y esfuerzo; decisión 4) |
| `imagen` | Genera con el prompt de GPT (rasgos de la ficha) y un nombre con sentido (`karito1`) |
| `rehacer_imagen` | "Esa imagen no me gusta, hazla…": nuevo prompt a partir del anterior |
| `personaje` | Crea la ficha con su descripción (o completa una "## Descripción" vacía) |
| `proyecto` | Crea o cambia de proyecto |
| `mover_nota` | "No ahí, ponla en X": copia la última nota a X; la anterior no se borra (decisión 6) |
| `busqueda` | Responde que llega en la fase 3 y ofrece guardarlo |

**Contexto que recibe GPT en cada mensaje:** proyecto activo, nombres de sus notas (sin imágenes, análisis,
`_proyecto.md` ni `tareas.md`) y de las notas sueltas de la raíz, fichas de personajes con un resumen de 200
caracteres, y la última acción del bot en ese chat (válida 30 min: nota con su contenido, o imagen con su prompt).
El mensaje va dentro del JSON como dato. **Salida validada:** acción conocida, destino elegido de la lista real
(nunca una ruta del modelo), confianza acotada; si la respuesta no es JSON, un solo reintento.

**SetFit (el "chico")**
- Modelo: `paraphrase-multilingual-mpnet-base-v2` con vocabulario congelado, 10 iteraciones, 615 ejemplos
  (100 por acción en el estilo del usuario + correcciones + aprendidos). Instalado en `datos/router/modelo`.
- Medido con frases que nunca se entrenan: 92,5 % en la prueba ciega (antes 70,8 %).
- Papel actual: respaldo si GPT falla, y comparación en el log de cada mensaje ("setfit: nota 0,98").
- **Aprende de GPT** solo donde fallaba o dudaba (`aprender_de` → `datos/router/aprendidos.yaml`).
- `/reentrenar` (~14 min en CPU; la CPU de la PC llega a 100 °C) con **control de calidad**: el modelo nuevo se
  mide antes del cambio y, si sale peor, se descarta.

**Configuración** (`config.yaml`, sección `router`): `interprete` (activo, modelo, razonamiento, timeout,
max_tokens), `entrenamiento` (base, iteraciones, épocas, congelar_vocabulario), umbrales de ejecutar/confirmar.
Cambiarla exige recrear `core` (`docker compose up -d --no-deps --force-recreate core`).

**Herramientas:** `scripts/evaluar_router.py` (mide o entrena candidatos en `datos/router-candidatos/`, fuera de
Syncthing), `./hub.sh entrenar`, `./hub.sh modelos` (baja la base de `config.yaml`), `.venv-gpu` (solo PC, para
experimentar con la GTX 1650).

**Registro:** por cada mensaje, `./hub.sh logs` muestra la acción de GPT, su confianza, lo que habría dicho SetFit
y el tipo de destino; nunca el texto del usuario.

**Pendiente**
- Desplegar en la laptop (`git pull`, `.\hub.ps1 modelos`, reentrenar o copiar el modelo) y probar allí.
- Decidir si SetFit sigue en el camino de cada mensaje o solo como respaldo (hoy suma ~45 ms por mensaje para el log).
- Limitar los hilos de `/reentrenar` para que la CPU no llegue a 100 °C.
- "La misma elfa pero…" con la imagen anterior como referencia visual (hoy se rehace desde el prompt).
- Día 6 (resto) y día 7: `/estado` con gasto y pausas, README y guion de la demo.

**Resultado:** 284 pruebas de `core` pasan (1 omitida). Bot en marcha en la PC con `gpt-6-sol`.

**Qué aprendiste: cada pieza en lo que hace mejor.** Las reglas son exactas y gratis para lo que tiene forma fija;
SetFit es rápido y local para clasificar; el LLM entiende el lenguaje real (nombres mal transcritos, "eso de antes",
dónde va cada cosa). Un buen sistema no elige uno: los ordena, usa el más barato que alcanza y deja que el grande
enseñe al chico.

## 2026-09-30 — Redactor con LLM, proyectos sin esqueleto y lo concreto en local

El usuario probó el bot y lo encontró "muy tonto para crear las notas": guardaba cada mensaje tal cual y en un
solo lugar, y creaba carpetas y secciones vacías que nadie pidió. Pedido: creación simple (el proyecto es solo su
carpeta y el bot pregunta qué va dentro), archivos y fichas solo cuando hay algo que poner, más LLM para decidir y
el router local solo para funciones concretas. Se aceptó gastar más tokens a cambio de calidad.

**Qué se hizo**
- **Redactor** (`acciones/redactor.py`): con el mensaje, la pista del intérprete, la última acción y el contenido
  real del proyecto (lo más relacionado primero, hasta 12.000 tokens), `gpt-6-sol` devuelve operaciones
  `agregar` (al final o dentro de una sección) y `crear` (archivo o ficha), una respuesta corta, avisos de
  contradicción y, si falta algo, una pregunta. Reparte un mensaje entre historia y fichas y enlaza con `[[…]]`.
- **El código impone las reglas de la bóveda:** solo agregar (crear sobre algo existente pasa a agregar), rutas
  dentro del proyecto con nombres válidos en Windows, `Imagenes/`, `Analisis/` y `tareas.md` fuera de su alcance,
  fichas nuevas en la carpeta de personajes con `tipo: personaje`, y **cobertura**: si lo propuesto deja fuera
  más del 40 % de las palabras con contenido del mensaje, no se aplica y el mensaje se guarda tal cual.
- **Sin esqueletos:** `crear_proyecto` hace solo la carpeta y `_proyecto.md` y pregunta "¿De qué trata…?"; la
  respuesta llega como mensaje normal y el redactor la ubica. Fichas nuevas con solo lo que se sabe (las
  secciones aparecen al usarse). Fichas nuevas en `Personajes/`; las de `Historia/Personajes/` siguen valiendo.
  Una ficha es cualquier nota con `tipo: personaje`.
- **Lo concreto en local, por texto y voz:** `procesar()` une los dos caminos; órdenes de frase fija nuevas:
  diario ("anota en mi diario que…", `/diario`), limpiar, diagnóstico, modelo, ayuda y conversación nueva.
- **Contexto:** el bot recuerda las 3 últimas acciones (30 min) y las consultas guardan pregunta y respuesta,
  así "anota esto" después de una consulta (aunque en medio se cree un proyecto) guarda la respuesta. La
  consulta lee las notas del proyecto. "Así será Aely" (acción `nombrar_imagen`) renombra la última imagen y la
  pone en su ficha. El intérprete reintenta una vez si GPT devuelve vacío rápido; sin corte de 400 caracteres.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/acciones/redactor.py` | Nuevo: contexto del proyecto, prompt, validación, cobertura y escritura de las operaciones |
| `core/app/entradas/telegram_bot.py` | `procesar`, `ejecutar_orden`, `redactar`, `escribiendo`, `/diario`, proyecto con pregunta, 3 últimas acciones, consulta con notas, `nombrar_imagen` en la ficha |
| `core/app/boveda/proyectos.py` | Proyecto sin subcarpetas ni `tareas.md`; notas aparte en la raíz del proyecto |
| `core/app/acciones/referencias.py` | `carpeta_personajes` (nueva o la anterior), `fichas_de`, `nombres_de`, ficha sin esqueleto, párrafos separados en secciones |
| `core/app/acciones/personajes.py` | Fichas por `tipo: personaje`; descripción bajo el título en fichas sin secciones |
| `core/app/acciones/consulta.py` | `notas_del_proyecto` y notas en el prompt de sistema |
| `core/app/router/interprete.py` | Acción `nombrar_imagen`, "anota esto", respuesta a una pregunta, reintento, consulta vs. análisis |
| `core/app/router/reglas.py` | Órdenes fijas: diario, limpiar, diagnóstico, modelo, ayuda, nuevo |
| `core/app/boveda/escritor.py` | `sin_frontmatter` compartido |
| `core/app/main.py`, `core/app/config.py`, `config.yaml` | `proveedores.redactor`, `consulta_notas_tokens`, `boveda.personajes` (sale `subcarpetas`) |
| `core/tests/test_redactor.py` | Nuevo: 23 pruebas (validación, aplicar, cobertura, contexto, modelo simulado y el bot) |
| `README.md`, `GUIA.md` | Recorrido nuevo (sección 7) y primer arranque sin esqueleto |

**Decisiones y por qué**
- **Dos pasos (intérprete + redactor) y no uno:** el intérprete sigue rápido y barato para consultas, imágenes y
  proyectos; solo lo que se guarda paga el contexto grande. Si el redactor falla, queda el camino anterior.
- **El modelo propone, el código dispone:** las reglas de la bóveda (solo agregar, dentro del proyecto, nombres
  válidos, no perder palabras) no dependen de que el modelo obedezca.
- **Razonamiento bajo:** medido con 9 mensajes reales del usuario, organiza igual que el medio y tarda 2-7 s
  (medio: 3-13 s). Queda en `config.yaml` por si hace falta subirlo.
- **Preguntas sin estados especiales:** la pregunta del bot se guarda como última acción y la respuesta pasa por
  el camino normal; intérprete y redactor la unen con el mensaje original.

**Problemas encontrados**
- Primera prueba real: toda la trama iba a `_proyecto.md` (era el único archivo y "prefiere los existentes") y
  "¿y la historia?" se tomaba como análisis. Se ajustaron las instrucciones: `_proyecto.md` solo para la premisa;
  consulta incluye preguntas sobre sus notas, análisis solo si pide analizar o revisar.
- Mensaje real de las 01:10 ("Anota esto dentro de la idea principal…"): "esto" era la respuesta de una consulta
  anterior y en medio se creó el proyecto. El bot solo recordaba la última acción y no las consultas: ahora
  recuerda 3 y las consultas guardan su respuesta.
- Un archivo grande que no cabía en el contexto se recortaba y dejaba fuera a los chicos: ahora entran primero
  los que caben enteros. El resumen hablado leía rutas de los enlaces: ahora usa el nombre visible. El aviso
  "escribiendo…" podía cancelarse antes de salir: el primero se manda de inmediato. Párrafos pegados al agregar
  dentro de una sección: ahora van separados por una línea en blanco (las viñetas, seguidas).
- A las 01:13 la bóveda de pruebas quedó vacía: lo hizo el usuario desde el explorador (está en la papelera);
  las pruebas usan bóvedas temporales.

**Resultado de las pruebas:** 308 pasan (1 omitida) en `.venv` y en la imagen reconstruida. Pruebas reales con
OpenClaw: 9 mensajes del día anterior (dos niveles de razonamiento) y el bot completo con Telegram simulado y los
mensajes del usuario de las 01:07-01:10: la consulta, el proyecto por voz, "anota esto…" (guardó la respuesta
completa como idea principal), tarea y lista de tareas sin tokens (0,0 s), fichas de Elías y Marta enlazadas y
"¿de qué trata mi proyecto?" respondido con sus notas.

**Cómo probarlo:** `docker compose up -d --no-deps --force-recreate core`; luego `/proyecto nuevo Prueba`,
responder de qué trata, "Kael es un cazador de monstruos que perdona a Aely, una elfa albina", "ella pelea con
dos hachas", "crea un personaje herrero" (pregunta el nombre), "crea dentro del proyecto un archivo Mundo y anota
que…", "tarea: …", "dime mis tareas", "anota en mi diario que…" y "¿de qué trata mi proyecto?". Revisar en
Obsidian que no haya carpetas ni secciones vacías.

**Qué aprendiste: el modelo propone, el código dispone.** Un LLM decide mejor que cualquier regla dónde va una
idea, pero no se le confían las garantías: se le pide un plan en JSON y el código lo valida (solo agregar, dentro
del proyecto, sin perder palabras) antes de tocar un archivo. Así se gana criterio sin perder seguridad, y si el
modelo falla o se equivoca, el camino anterior sigue ahí.

## 2026-09-30 — Voz: cobertura que no descarta, nombres del proyecto para Whisper e imagen a la ficha

El usuario notó que con audios "le cuesta un poco". Los registros mostraron la causa: de 4 notas de voz, 3 se
descartaron por el control de cobertura (29 %, 47 % y 57 %; mínimo 60 %) y se guardaron crudas, aunque el redactor
las había organizado bien. Al hablar se usan futuros ("medirá, estará, será") que el redactor pasa a presente, y más
relleno ("vale, vas a crear…"); para la cuenta de palabras eso parecía contenido perdido. También Whisper escribió
"Dikon" por "Deacon", y una imagen pedida "para su ficha" quedó solo en `Imagenes/`.

**Qué se hizo**
- **Cobertura que no descarta:** si lo escrito deja fuera muchas palabras del mensaje, se guarda lo organizado y,
  junto a lo primero que se escribe, el mensaje original en un callout plegable de Obsidian
  (`> [!quote]- Tu audio transcrito original (fecha)`). En el chat se avisa. Umbral 50 % en voz y 60 % en texto;
  los auxiliares del habla (será, estará, tendrá, podremos, llamar…) no cuentan como contenido y el nombre del
  proyecto cuenta como escrito.
- **Pista de Whisper por audio** (`voz/cliente.componer_pista`): proyecto activo, sus personajes (con alias) y los
  demás proyectos, delante del vocabulario de `config.yaml`, sin pasar de 400 caracteres ni cortar una frase.
- **Imagen a la ficha si se pide:** si el pedido menciona la ficha y la imagen es de un personaje con ficha, se
  inserta en "## Referencias visuales" (`en_ficha`). Sin mencionarla, solo en `Imagenes/`.
- **Fichas:** el redactor usa siempre una sección en las fichas (antes "maneja una moto" quedó como bloque suelto
  con fecha al final).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/acciones/redactor.py` | `Plan.cobertura`/`Plan.original`, `bloque_original`, umbral por origen, palabras del habla, regla de secciones en fichas |
| `core/app/voz/cliente.py` | `componer_pista`; `transcribir(pista=)` |
| `core/app/entradas/telegram_bot.py` | `pista_voz` en cada audio, `en_ficha` al generar imágenes, sin `SinCobertura` |
| `core/tests/test_redactor.py`, `core/tests/test_voz.py`, `core/tests/test_bot.py` | 6 pruebas nuevas; la voz falsa registra la pista |
| `config.yaml`, `GUIA.md` | Comentarios del vocabulario y de la cobertura |

**Decisiones y por qué**
- **No descartar nunca lo organizado:** descartar protegía contra ideas perdidas, pero tiraba también el orden, que
  es lo que el usuario quiere. Guardar las dos cosas (la versión ordenada y el original plegado) cumple ambos fines.
- **Nombres primero en la pista:** Whisper solo usa ~224 tokens de contexto previo y lo que más falla son los
  nombres propios; el vocabulario general va detrás y se corta si no cabe.
- **Imagen a la ficha solo si se pide:** el usuario no quiere que el bot haga cosas que no dijo.

**Problemas encontrados**
- La prueba "si pierde palabras" esperaba un bloque con título en `Historia.md`, pero el archivo no existía y el
  redactor lo creó: la prueba se corrigió (el comportamiento era el correcto).

**Resultado de las pruebas:** 314 pasan (1 omitida) en `.venv` y en la imagen reconstruida. Reales: (1) Kokoro dijo
tres frases con "Díkon" y Whisper las transcribió sin y con la pista: la que salía "Dickon" pasó a "Deacon"; las
otras dos ya salían bien. (2) El bot completo con los audios del usuario (el de "Días del futuro pasado" literal,
los de Deacon reconstruidos): cobertura 100 %, 67 % y 67-75 %, nada descartado; premisa en `_proyecto.md`, ideas de
la consulta en `Historia.md`, fichas de Deacon (familia, apariencia, otros datos) y Shirley enlazadas, "personaje
femenino sin nombre" anotado en la historia y "¿cómo es Deacon?" respondido con sus notas. Scripts en
`datos/pruebas/` (fuera de git).

**Cómo probarlo:** recrear `core`; con un proyecto activo que tenga fichas, mandar audios describiendo personajes
en futuro ("será…, medirá…"); revisar en Obsidian que todo quede ordenado y, si aparece un bloque "Tu audio
transcrito original", que esté plegado junto a lo escrito. Pedir "una imagen de X para su ficha" y comprobar que
aparece en "## Referencias visuales".

**Qué aprendiste: una red de seguridad no debe romper lo que protege.** El control de cobertura evitaba perder
ideas, pero al descartar el plan entero perdía el orden, que era el objetivo. La versión buena conserva ambos:
aplica lo organizado y guarda el original a un lado, plegado. Medir con datos reales (los registros de cobertura)
mostró el problema sin adivinar.

## 2026-09-30 — `/tokens` y `/estado` nuevo: registro de uso de cada modelo

Pedido del usuario (punto 2 del plan): una función `/tokens` con los tokens gastados hasta el momento y un `/estado`
más completo. Antes solo se contaban las llamadas de la consulta y del análisis (tabla `gasto`), sin tokens; el
intérprete, el redactor, el router y las imágenes no se registraban.

**Qué se hizo**
- **Registro central:** todas las llamadas a modelos pasan por `OpenClaw._pedir`; cada respuesta se entrega a un
  `contador(funcion, respuesta)` que la suma en SQLite (tabla nueva `uso`: fecha, función, modelo, llamadas,
  entrada, salida, estimadas). Cada cliente tiene su función (`consulta`, `router`, `interprete`, `redactor`) y
  el análisis marca la suya en la llamada (usa el cliente de la consulta). Las imágenes se cuentan sin tokens.
- **Salida estimada:** Claude por Claude Code informó "2 tokens de salida" en un análisis largo. Si lo informado es
  menos de un cuarto de lo que mide el texto (3,5 caracteres por token), se registra la estimación y se marca con
  `~`; `/tokens` explica que además su entrada no incluye el prompt propio del programa (~3.700).
- **`/tokens`** (y "cuántos tokens llevo", "tokens de hoy"… como orden fija, sin tokens): hoy por función y modelo,
  con entrada y salida; desde el primer día registrado, por modelo; notas de las estimaciones y de lo que no gasta
  (voz local, comandos, órdenes fijas). Por voz, una frase ("Hoy llevas 3 mil tokens en 4 llamadas…").
- **`/estado`:** intérprete y redactor con modelo y razonamiento, respaldo local (reglas + SetFit), cadena de la
  consulta, OpenClaw, voz, imágenes (lista, falta configurar o "en pausa hasta las HH:MM tras N fallos") y "Uso de
  hoy". Salen la cola (no se usa, decisión 5) y la web "fase 2". Por voz: "El servidor X está activo. Todo
  responde." o "Ojo: …" con lo que falla, y los tokens de hoy.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/acciones/uso.py` | Nuevo: texto y voz de `/tokens`, línea de uso de `/estado`, números legibles |
| `core/app/proveedores/openclaw.py` | `funcion` y `contador` por cliente o por llamada; `Respuesta.salida_estimada` |
| `core/app/estado/db.py` | Tabla `uso`, `sumar_uso`, `uso(desde, hasta, por)`, `primer_dia_de_uso`, `contador_de_uso`; sale `sumar_gasto` |
| `core/app/entradas/telegram_bot.py` | `/estado` nuevo, `estado_imagenes`, `/tokens`, registro de imágenes, `_modelo`, `_cuantos` |
| `core/app/main.py` | Conecta el contador a los cuatro clientes de OpenClaw |
| `core/app/acciones/analisis.py`, `core/app/acciones/consulta.py` | El análisis marca su función; la consulta ya no suma aparte |
| `core/app/router/reglas.py` | Orden fija `tokens` |
| `core/tests/test_uso.py`, `core/tests/test_estado.py` | 14 pruebas nuevas; la del gasto pasa a la de `uso` |

**Decisiones y por qué**
- **Contar en el cliente y no en cada acción:** es el único lugar por donde pasan todas las llamadas; así no se
  olvida ninguna función nueva. El contador nunca rompe una respuesta: si falla, se registra en el log y sigue.
- **Tabla nueva `uso`** en vez de cambiar `gasto`: SQLite no agrega columnas a una clave primaria; `gasto` queda
  por compatibilidad con bases existentes (decisión 1: es estado operativo, no contenido).
- **Estimar solo lo absurdo:** los tokens informados por GPT son buenos (incluyen el razonamiento); solo se corrige
  cuando el número es imposible, y se marca para no presentar una estimación como dato.
- **Sin "panel de ahorro":** está fuera de alcance; `/tokens` muestra lo gastado, no porcentajes de ahorro.

**Problemas encontrados**
- La prueba de uso por modelo esperaba el orden equivocado (el que más tokens suma va primero): se corrigió la
  prueba. En la prueba real, `/estado` decía "razonamiento sin razonamiento" para Haiku y "de 1 proyectos": se
  corrigió la redacción (`_modelo`, `_cuantos`).

**Resultado de las pruebas:** 329 pasan (1 omitida) en `.venv` y en la imagen reconstruida. Real (bot completo con
modelos reales y contador como en `main.py`): proyecto nuevo, audio de Deacon (ficha creada), consulta, `/estado`
(todo responde; "Uso de hoy: 4 llamadas, 3.249 tokens"), "estado" por voz, `/tokens` (intérprete 1.865, redactor
1.161, consulta 223) y "cuántos tokens llevo" por voz resuelto sin tokens.

**Cómo probarlo:** recrear `core`, usar el bot un rato y mandar `/tokens`, "cuántos tokens llevo" (texto o voz) y
`/estado`. El registro empieza al recrear `core`: lo anterior no se cuenta.

**Qué aprendiste: medir en el único punto de paso.** Si cada función registrara su propio uso, bastaría olvidar una
para que los números mientan. Contar donde pasan todas las llamadas (el cliente) hace el registro completo por
construcción, y marcar lo estimado evita confundir una aproximación con un dato.

## 2026-09-30 — Conflictos de Syncthing: aviso, sugerencia y resolución con botones; latido por servidor

El usuario preguntó cómo resuelve Syncthing los conflictos. Al revisar apareció uno real en la bóveda
(`_hub/servidor.sync-conflict-20260930-021810-YEYNFXT.json`: la laptop escribió su latido sin conexión y al
reconectarse chocó con el de la PC) y un error en la guía: decía que el bot "crea siempre archivos nuevos", pero
desde el 2026-09-27 agrega a archivos existentes (`Historia.md`, fichas, `tareas.md`, el diario). Pedido: borrar
esa copia, evitar el conflicto del latido si no rompe nada, corregir la guía y, como prioridad, que el bot detecte
los conflictos, sugiera cómo resolverlos y pueda hacerlo.

**Qué se hizo**
- Copia de conflicto del latido revisada y borrada (el borrado se propagó a los 4 equipos).
- **Conflictos** (`boveda/conflictos.py`): cada 60 s (`boveda.revisar_conflictos_s`) se buscan copias
  `*.sync-conflict-*` (sin `.stversions`, `.stfolder`, `.trash`); se avisa solo de las que siguen en la revisión
  siguiente (Syncthing puede estar copiándolas) y una sola vez. El aviso por Telegram dice qué líneas tiene solo
  cada versión, una sugerencia con su motivo y botones: **Unir** (lo de la copia se inserta en su lugar en la
  actual; si un fragmento cambió en las dos quedan ambas, primero la copia, que es la más vieja), **Quedarme con la
  actual**, **Usar la copia** (o restaurar un original borrado) y **Después**. Antes de tocar nada, las dos versiones
  se copian a `datos/conflictos/<fecha-hora>/`. `/conflictos` (y "hay conflictos", por texto o voz) los lista. Las
  copias del latido se borran solas. Los archivos que no son `.md`/`.txt` no se unen (un JSON quedaría roto).
- **Latido por servidor** (`estado/latido.py`): cada equipo escribe `_hub/servidor-<nombre>.json`; el arranque lee
  todos, incluido el `servidor.json` anterior, e ignora copias de conflicto y archivos rotos.
- **Documentación:** sección "Conflictos" de `GUIA.md` reescrita (cómo decide Syncthing, dónde puede pasar aquí, qué
  hace el bot), latido en `GUIA.md` y `README.md`, y tabla de comandos del README (`/diario`, `/tokens`,
  `/conflictos`, proyectos sin esqueleto, redactor).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/boveda/conflictos.py` | Nuevo: buscar, analizar, unir (difflib), resolver con respaldo, `Vigilante` |
| `core/app/entradas/telegram_bot.py` | `mensaje_conflicto`, `revisar_conflictos`, `vigilar_conflictos`, `/conflictos`, botones `cf:` |
| `core/app/estado/latido.py` | Un archivo por servidor; `leer_todos`; `leer` = el más reciente |
| `core/app/main.py`, `core/app/config.py`, `config.yaml` | Tarea de vigilancia; `boveda.revisar_conflictos_s` |
| `core/app/router/reglas.py` | Orden fija `conflictos` |
| `core/tests/test_conflictos.py`, `core/tests/test_estado.py` | 14 pruebas nuevas |
| `GUIA.md`, `README.md` | Conflictos, latido y comandos |

**Decisiones y por qué**
- **Siempre con botones y respaldo:** resolver un conflicto es reescribir o borrar lo del usuario (decisión 6); se
  hace solo si él elige y con las dos versiones guardadas fuera de la bóveda. La excepción es el latido, que es del bot.
- **Unir por líneas sin versión común:** Syncthing no guarda el ancestro, así que donde las dos cambiaron no se sabe
  cuál es la buena: se conservan ambas en orden cronológico y se avisa. Lo típico aquí (el bot agrega un bloque y el
  usuario edita otra parte) se une limpio.
- **Latido compatible:** el código nuevo lee también el archivo viejo; si un equipo aún tiene el código viejo, el
  error 409 de Telegram sigue impidiendo dos servidores a la vez. Conviene actualizar los dos equipos.

**Problemas encontrados**
- Dos pruebas esperaban la variante actual antes que la de la copia; se decidió el orden cronológico (la copia es
  la más vieja) y se ajustó el código y la prueba.
- Una prueba de uso esperaba mal el orden por tokens (tarea anterior): corregida.

**Resultado de las pruebas:** 343 pasan (1 omitida) en `.venv` y en la imagen reconstruida. Real (solo lectura sobre
la bóveda): con el latido viejo de la PC, el código nuevo deja arrancar a `pc-casa` y bloquea a `laptop`.

**Cómo probarlo:** recrear `core`. Con el móvil en modo avión, editar `Historia.md` de un proyecto en Obsidian; desde
Telegram, mandar una nota que el redactor agregue a ese mismo archivo; quitar el modo avión. En uno o dos minutos
llega el aviso con la sugerencia; probar "Unir" y revisar en Obsidian y en `datos/conflictos/`.

**Qué aprendiste: sin ancestro común no hay fusión perfecta.** Git une bien porque conoce la versión de la que
partieron los dos cambios; Syncthing solo tiene las dos versiones finales. Sin esa base, donde ambas difieren no se
puede saber cuál cambió: lo honesto es conservar las dos y avisar, y dejar que el usuario decida con un respaldo.

## 2026-09-29 — `/reentrenar` en Windows: soltar el modelo antes de reemplazarlo

**Qué se hizo**
- Con la laptop como servidor, `/reentrenar` entrenó bien (133 ejemplos) pero falló al final:
  `PermissionError: '/datos/router/modelo' -> '/datos/router/.modelo.viejo'`. Se instaló a mano esa vez
  (parar `core`, cambiar las carpetas, arrancar).
- Arreglo: el reemplazo del modelo pasa a `clasificador.instalar()`. Si renombrar la carpeta falla por permisos,
  llama a `liberar` (el router suelta el modelo y usa las reglas un instante), ejecuta el recolector de basura y
  reintenta. Si aun así falla, el router vuelve a cargar el modelo viejo.

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/router/clasificador.py` | `instalar()`: reemplazo con reintento solo si hay `PermissionError`; si falla a medias, devuelve el modelo viejo a su sitio |
| `core/app/router/cascada.py` | `reentrenar()` pasa `liberar=_soltar_modelo` y recarga el modelo viejo si el reemplazo falla tras soltarlo |
| `core/tests/test_router_local.py` | 4 pruebas: Linux no suelta el modelo, Windows lo suelta y reintenta, bloqueo sin remedio conserva el viejo, recarga tras fallo |

**Decisiones y por qué**
- **Se activa por el error, no detectando el sistema:** `core` corre en un contenedor Linux también en Windows, así
  que el sistema operativo no se ve desde dentro. Lo que cambia es el montaje: en Linux la carpeta se renombra
  aunque el modelo esté cargado y el código hace lo mismo que antes; solo en Windows aparece el `PermissionError`.
- **Reintentos cortos (5 × 0,5 s):** una predicción en curso puede retener el modelo unos milisegundos.

**Problemas encontrados**

| Problema | Solución |
| --- | --- |
| Windows no deja renombrar una carpeta con archivos abiertos (el modelo cargado usa `model.safetensors`) | Comprobado en el montaje real: cargado → `PermissionError`; soltado + `gc.collect()` → rename OK |

**Resultado:** 255 pruebas pasan (1 omitida). Prueba real en la laptop sobre una copia: sin el arreglo se reproduce
el error; con él el modelo se instala, se recarga y no quedan `.modelo.*`. `core` reconstruido con el arreglo.

**Cómo probarlo:** en la laptop como servidor, `/reentrenar`; el log dice "La carpeta del modelo está en uso
(servidor en Windows): se suelta y se reintenta" y `/estado` muestra 0 pendientes.

**Qué aprendiste: el mismo código, distinto sistema de archivos.** Un contenedor Linux sobre una carpeta de Windows
hereda las reglas de NTFS: una carpeta con archivos abiertos no se renombra. Por eso las pruebas en Ubuntu no lo
veían: el fallo no estaba en el código sino en el montaje.

## 2026-09-30 — Relevo entre servidores: la PC de guardia cede el bot a la laptop y lo retoma sola

Para la presentación del 2026-10-01 el usuario quiere dejar la PC de casa encendida como servidor, levantar el
stack en la laptop delante del público y que la PC deje de atender (solo sincronizando con Syncthing) hasta que la
laptop se apague, momento en que vuelve sola. Antes, el segundo equipo se negaba a arrancar (latido o 409) y había
que parar la PC a mano. Se planificó primero (dos señales, estados, riesgos) y el usuario aprobó el enfoque tras
desplegar y probar la laptop con `c46e035`.

**Qué se hizo**
- **Estados en el latido** (`estado/latido.py`): `activo`, `espera` o `apagado`, `desde`, `cede` (equipo de guardia)
  y `proyectos` (proyecto activo de cada chat). Un latido sin `estado` (código anterior) cuenta como `activo`.
  `conflicto()` ya no bloquea por equipos en espera, apagados o de guardia. `por_servidor()`: el último de cada equipo.
- **Relevo** (`estado/relevo.py`, nuevo): supervisor que alterna entre leer el bot y esperar, sin reiniciar el
  proceso.
  - El de guardia (`relevo.ceden`) cede ante el **409** (un middleware de la sesión de aiogram lo detecta en
    `getUpdates`) o ante un latido reciente de otro equipo `activo`.
  - En espera solo late; vuelve cuando el otro dice `apagado` o deja de latir 3 min, **tras un sondeo** de 8 s
    (`getUpdates` largo: si otro lee, llega un 409).
  - Si el sondeo choca sin latido que lo explique, pausa de 3, 6, 12… hasta 30 min. Tras un `apagado`, hasta
    3 reintentos cortos (12 s).
  - Quien toma el bot adopta el proyecto activo del otro si es más reciente. Avisa por Telegram ("Ahora atiende
    laptop…" / "Vuelve a atender pc-casa: laptop se apagó.").
  - La orden de apagado de Docker (SIGTERM) deja el latido en `apagado`, incluso a mitad de un sondeo.
- **Bot**: `preparar(comprobar_lector=False)` con relevo; `/estado` con "de guardia" y "Otros servidores: …"; el aviso
  de conflictos de Syncthing se pausa en espera.
- **Terminal**: `./hub.sh servidores` (tabla de latidos) y `parar`, que después de `down` espera a que el de guardia
  retome el bot y lo confirma con ✓ (`scripts/relevo.py`); `chequeo` avisa del desfase de reloj con Telegram (encabezado
  `Date`), del papel del equipo en el relevo y de un nombre de guardia sin latido.
- **Documentación**: README (función, comandos, "Mover el servidor…", problemas comunes, árbol) y GUIA (sección 8
  reescrita: estados, dos señales, sondeo, reloj propio; ejercicio 5).

**Archivos**

| Archivo | Qué hace |
| --- | --- |
| `core/app/estado/relevo.py` | Nuevo: `Relevo` (ciclo atender/esperar), `Observador`, `a_quien_ceder`, `VigiaConflicto`, `adoptar_en` |
| `core/app/estado/latido.py` | Estados, `cede`, `proyectos`, `por_servidor`, `estado_de`; `conflicto(ceden=)` |
| `core/app/estado/db.py` | `proyectos_activos()` para el latido |
| `core/app/main.py` | Crea y conecta el relevo si `relevo.activo`; sin él, el arranque de siempre |
| `core/app/entradas/telegram_bot.py` | `Contexto.relevo`, `/estado`, conflictos en pausa, `preparar(comprobar_lector=)` |
| `core/app/config.py`, `config.yaml` | Sección `relevo` (apagada por defecto en código; activa con `ceden: [pc-casa]`) |
| `core/scripts/relevo.py` | Nuevo: tabla de servidores y espera del relevo tras `parar` |
| `core/scripts/chequeo.py` | Desfase de reloj, papel en el relevo, guardia sin latido |
| `hub.sh`, `hub.ps1` | `parar` espera al de guardia; `servidores` |
| `core/tests/test_relevo.py` | 17 pruebas: reglas, reloj, proyectos, ciclo completo con Telegram falso, terminal |
| `README.md`, `GUIA.md` | Relevo explicado |
| `datos/pruebas/simular_relevo.py` | Fuera de git: dos relevos reales de aiogram contra una API de Telegram falsa por HTTP |

**Decisiones y por qué**
- **El 409 como candado y el latido como tablón:** el 409 reacciona en un segundo y no depende de Syncthing (que en la
  sala irá por relé, ~10-30 s); el latido da lo que el 409 no sabe: quién es el otro y cuándo se apagó.
- **Solo cede el de guardia; la laptop nunca:** si la PC se reinicia en medio de la demo, arranca en espera y no le
  quita el bot a la laptop. Entre dos de guardia atiende el de nombre menor (sin cederse el bot mutuamente).
- **Sondeo largo antes de volver:** una petición instantánea siempre "gana" y no detecta a otro lector.
- **Edad del latido con el reloj propio** (cuánto hace que *cambió*): Docker Desktop puede desfasar la hora de la
  laptop tras suspenderla.
- **Proyecto activo en el latido** (opción recomendada en el plan): el chat queda en `_hub/`, que llega también al
  móvil y la tablet (son del usuario). Solo se adopta si es más reciente que el propio y el proyecto existe.
- **Sin relevo = lo de antes:** `relevo.activo: false` recupera el arranque anterior sin tocar código.

**Problemas encontrados**
- Simulando la regla inversa de Telegram (gana la lectura vieja), la lectura pendiente de la laptop seguía viva unos
  segundos tras apagarse: el primer sondeo de la PC chocaba y caía en la pausa de 3 min. Se agregaron reintentos
  cortos tras un `apagado` recién visto. La PC retoma el bot en 14 s en ese caso y en 2,5 s en el normal.
- Un error 5xx de Telegram durante el sondeo tumbaba `core`: ahora cuenta como "sin red" y se reintenta en 30 s.
- La orden de apagado a mitad de un sondeo de 8 s podía no dejar escribir `apagado` antes del SIGKILL (Docker da
  10 s): el sondeo se corta en cuanto llega la orden.

**Resultado de las pruebas:** 360 pasan (1 omitida) en `.venv` y en la imagen reconstruida. Simulación con aiogram
real contra la API falsa: la PC cede en 0,1 s (409) y retoma en 2,5 s; con la regla inversa, cede por el latido en
0,5 s y retoma en 14 s. En los dos casos cada mensaje lo procesó una sola vez el servidor correcto. Falta la prueba con
el token real y Syncthing entre los dos equipos (ensayo).

**Cómo probarlo:** en la PC, recrear `core` con el código nuevo (usa el token real). En la laptop, `git pull`,
`docker compose build core` y `.\hub.ps1 arrancar`. Seguir `./hub.sh logs` en la PC: "Relevo: … pasa a espera".
Mandar mensajes, `/estado` (ver "Otros servidores"), `.\hub.ps1 parar` y esperar el ✓. Repetir con la laptop en el
hotspot del móvil (relé de Syncthing) y una vez apagando la laptop de golpe (la PC vuelve a los ~3 min).
`.venv/bin/python datos/pruebas/simular_relevo.py [nueva|vieja]` repite la simulación sin token.

**Qué aprendiste: un candado y un tablón no son lo mismo.** El 409 de Telegram es un candado: garantiza que solo uno
lea el bot y avisa al instante, pero no dice quién es el otro ni cuándo se va. El latido es un tablón: cuenta el
estado de cada equipo, pero llega tarde y puede mentir (relojes, Syncthing caído). Juntos se cubren: se actúa con
el candado y se decide con el tablón, y antes de retomar el candado se comprueba de verdad (el sondeo).
