# Guía paso a paso: montar el hub y entender qué estás haciendo

Esta guía sigue el mismo orden que el README, pero en cada paso explica **qué haces**,
**por qué** se hace así y **cómo comprobar** que salió bien. La idea es que al terminar
puedas explicar cada pieza del sistema, no solo que funcione.

Formato de cada paso:

> **Qué haces:** la acción concreta.
> **Por qué:** el motivo técnico.
> **Comprueba:** cómo saber que salió bien.

Índice:

0. [El mapa completo antes de empezar](#0-el-mapa-completo-antes-de-empezar)
1. [Conceptos que vas a usar](#1-conceptos-que-vas-a-usar)
2. [Preparar la PC de casa (Ubuntu)](#2-preparar-la-pc-de-casa-ubuntu)
3. [Preparar la laptop (Windows)](#3-preparar-la-laptop-windows)
4. [Sincronizar la bóveda con Syncthing](#4-sincronizar-la-bóveda-con-syncthing)
5. [El repositorio y los secretos](#5-el-repositorio-y-los-secretos)
6. [Primer arranque](#6-primer-arranque)
7. [Qué pasa por dentro cuando envías un mensaje](#7-qué-pasa-por-dentro-cuando-envías-un-mensaje)
8. [Mover el servidor a la laptop](#8-mover-el-servidor-a-la-laptop)
9. [Pruebas y registros](#9-pruebas-y-registros)
10. [Ejercicios para afianzar](#10-ejercicios-para-afianzar)

---

## 0. El mapa completo antes de empezar

Antes de instalar nada, conviene tener claro el recorrido de un mensaje:

```
Móvil (Telegram) ──> servidores de Telegram <── core (pregunta: ¿hay mensajes?)
                                                  │
                                                  ├─ decide qué hacer (router)
                                                  ├─ escribe un .md en la bóveda
                                                  │
                          Bóveda en disco <───────┘
                                │
                        Syncthing la copia
                                │
               PC de casa · laptop · móvil (Obsidian la muestra)
```

Tres ideas sostienen todo el diseño:

1. **La bóveda de Obsidian es la única base de datos.** Todo lo que importa termina
   como archivo `.md` o imagen. Lo demás es temporal y se puede borrar.
2. **El equipo donde levantas Docker es el servidor.** PC o laptop, mismo código,
   mismo comando. Solo cambia el archivo `.env` de cada uno.
3. **Primero lo gratis y local, después lo de pago.** Reglas y modelos locales antes
   que cualquier API externa.

---

## 1. Conceptos que vas a usar

No hace falta memorizarlos ahora; vuelve aquí cuando un paso los mencione.

### Docker: imagen, contenedor y Compose

- **Imagen:** una "receta congelada" con un sistema mínimo, Python, las librerías y tu
  código. Se construye a partir de un `Dockerfile`. Es de solo lectura.
- **Contenedor:** una imagen en ejecución. Puedes crear varios contenedores de la
  misma imagen, borrarlos y recrearlos sin perder nada de la imagen.
- **Docker Compose:** describe en un solo archivo (`docker-compose.yml`) varios
  contenedores que trabajan juntos, sus conexiones y sus carpetas. Con
  `docker compose up` se levantan todos.

**Por qué Docker en este proyecto:** Ubuntu y Windows son sistemas distintos, pero los
contenedores son siempre Linux. El mismo código corre igual en la PC, en la laptop y,
más adelante, en un servidor rentado. Sin Docker tendrías que instalar Python, las
librerías y Ollama a mano en cada equipo y rezar para que las versiones coincidan.

### Volúmenes: dónde vive lo que no debe perderse

Un contenedor se borra y se recrea cada vez que actualizas el código. Lo que escribe
dentro desaparece con él. Para conservar datos se "montan" carpetas:

- **Bind mount** (`./datos:/datos`): una carpeta real de tu equipo aparece dentro del
  contenedor. La usamos para la bóveda, `datos/` y `modelos/`, porque quieres ver esos
  archivos desde fuera.
- **Volumen con nombre** (`openclaw_estado:`): Docker guarda la carpeta en su propio
  espacio. La usamos para las credenciales de OpenClaw, porque no quieres que estén a la
  vista ni que Syncthing o Git las toquen.

### Puertos

`"127.0.0.1:8080:8080"` significa: *la dirección 127.0.0.1, puerto 8080 de tu equipo,
lleva al puerto 8080 del contenedor*. La primera parte (la IP) decide **quién** puede
entrar: `127.0.0.1` solo tu propio equipo; la IP local (por ejemplo `192.168.1.50`)
cualquiera en tu red wifi; `0.0.0.0` cualquier interfaz del equipo.

Ollama y OpenClaw **no** publican puertos: solo `core` habla con ellos por la red
interna que Compose crea entre contenedores. Menos puertas abiertas, menos riesgo.

### Long polling: por qué el bot no necesita IP pública

El bot no espera a que Telegram lo llame. Es al revés: `core` pregunta a Telegram
"¿hay mensajes nuevos?" y Telegram mantiene esa conexión abierta hasta que llega uno.
Como la conexión **sale** de tu equipo, no necesitas abrir puertos en el router ni tener
IP pública. Por eso el bot funciona igual en casa, en la universidad o con el hotspot
del móvil.

La consecuencia: **solo un proceso puede preguntar a la vez por el mismo bot**. Si dos
lo hacen, Telegram responde con el error **409 Conflict**. Por eso nunca pueden estar
activos la PC y la laptop al mismo tiempo.

### Variables de entorno y el archivo `.env`

El código no lleva escritas las claves ni las rutas. Las lee de variables de entorno,
que Compose carga desde `.env`. Así:

- el mismo código sirve en la PC y en la laptop (cada una con su `.env`);
- las claves nunca llegan a GitHub (`.env` está en `.gitignore`).

---

## 2. Preparar la PC de casa (Ubuntu)

### 2.1 Instalar Docker Engine

```bash
sudo apt update && sudo apt install -y git curl
curl -fsSL https://get.docker.com | sh
```

> **Qué haces:** descargas y ejecutas el instalador oficial de Docker.
> **Por qué:** los paquetes `docker.io` de Ubuntu suelen ir atrasados y a veces no
> traen el plugin `docker compose` moderno. El script oficial instala ambos.
> **Comprueba:** `docker --version` y `docker compose version` muestran versiones.

### 2.2 Usar Docker sin `sudo`

```bash
sudo usermod -aG docker $USER
```

Cierra la sesión y vuelve a entrar.

> **Qué haces:** agregas tu usuario al grupo `docker`.
> **Por qué:** Docker se controla por un "socket" (`/var/run/docker.sock`) al que solo
> acceden root y el grupo `docker`. Sin esto tendrías que escribir `sudo` en cada comando.
> **Importante:** estar en ese grupo equivale en la práctica a tener permisos de
> administrador, porque un contenedor puede montar cualquier carpeta del sistema. Es
> aceptable en tu equipo personal, no en uno compartido.
> **Comprueba:** `docker run --rm hello-world` funciona sin `sudo`.

### 2.3 Driver de NVIDIA

```bash
nvidia-smi
```

Si no muestra una tabla con la GPU:

```bash
sudo ubuntu-drivers install
sudo reboot
```

> **Qué haces:** instalas el driver propietario de NVIDIA recomendado para tu tarjeta.
> **Por qué:** sin driver, el sistema no puede usar la GPU para cálculo; Ollama correría
> solo en CPU, varias veces más lento.
> **Comprueba:** `nvidia-smi` muestra la tarjeta, la versión del driver y la memoria (4 GB).

### 2.4 NVIDIA Container Toolkit

(Comandos de la guía oficial de NVIDIA; si fallan, revisa si cambiaron.)

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

> **Qué haces:** agregas el repositorio de NVIDIA (las dos primeras órdenes: la clave
> que firma los paquetes y la dirección del repositorio), instalas el toolkit y le dices a
> Docker que lo use.
> **Por qué:** un contenedor está aislado y, por defecto, no ve la GPU. El toolkit
> permite que Docker "inyecte" la tarjeta y las librerías del driver dentro del
> contenedor cuando se lo pides (`--gpus all` o la sección `deploy` de
> `docker-compose.gpu.yml`). `nvidia-ctk runtime configure` edita
> `/etc/docker/daemon.json` para registrar ese mecanismo.
> **Comprueba:** `./hub.sh gpu` (cuando tengas el repositorio) o directamente
> `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
> muestra la misma tabla que en el paso 2.3, pero **desde dentro de un contenedor**.

### 2.5 Syncthing como servicio

```bash
sudo apt install -y syncthing
systemctl --user enable --now syncthing
sudo loginctl enable-linger $USER
```

> **Qué haces:** instalas Syncthing y lo registras como servicio de tu usuario
> (`enable` = arrancar siempre, `--now` = arrancar ya).
> **Por qué `enable-linger`:** los servicios de usuario normalmente solo corren mientras
> tienes la sesión iniciada. Con *linger*, siguen corriendo aunque la PC esté en la
> pantalla de inicio de sesión. Para un equipo que hace de servidor, eso es lo que quieres.
> **Por qué fuera de Docker:** si Syncthing viviera dentro del stack, al hacer
> `docker compose down` para mover el servidor a la laptop dejaría de sincronizar
> justo cuando más lo necesitas.
> **Comprueba:** abre http://127.0.0.1:8384 en el navegador de la PC: ves la interfaz.

---

## 3. Preparar la laptop (Windows)

### 3.1 WSL2

En PowerShell **como administrador**:

```powershell
wsl --install
```

Reinicia.

> **Qué haces:** activas el Subsistema de Windows para Linux, versión 2.
> **Por qué:** los contenedores son Linux. WSL2 es una máquina virtual Linux ligera,
> integrada en Windows, donde Docker Desktop ejecuta de verdad los contenedores.
> **Comprueba:** `wsl --status` indica versión predeterminada 2.

### 3.2 Driver de NVIDIA

Instala el driver más reciente desde la web de NVIDIA o GeForce Experience.

> **Por qué en Windows no hace falta el Container Toolkit:** el driver de Windows ya
> incluye el soporte para que WSL2 use la GPU ("CUDA en WSL"), y Docker Desktop lo
> aprovecha automáticamente. Es la principal diferencia con Ubuntu.
> **Comprueba:** `nvidia-smi` en PowerShell muestra la RTX 3050.

### 3.3 Docker Desktop

Instálalo y en *Settings → General* deja marcado **Use the WSL 2 based engine**.

> **Comprueba:** `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
> muestra la RTX 3050. **Haz esta prueba cuanto antes:** es lo que más suele fallar en
> Windows y quieres descubrirlo días antes de la demo, no esa mañana.

### 3.4 Git sin conversión de saltos de línea

Instala Git for Windows y luego:

```powershell
git config --global core.autocrlf false
```

> **Qué haces:** le dices a Git que no cambie los saltos de línea de los archivos.
> **Por qué:** Windows usa CRLF (`\r\n`) al final de cada línea; Linux usa LF (`\n`).
> Si Git convierte los archivos a CRLF al clonarlos, un script dentro de un contenedor
> Linux falla con errores tan raros como `bash\r: No such file or directory`. El
> repositorio además trae `.gitattributes` con `eol=lf`, que obliga a LF pase lo que pase:
> son dos capas de protección.
> **Comprueba:** después de clonar, `git ls-files --eol hub.sh` muestra `i/lf w/lf`.

### 3.5 Syncthing

Usa el instalador *Syncthing Windows Setup* (enlazado desde la página de descargas de
syncthing.net).

> **Por qué este instalador y no el zip oficial:** el zip solo trae el programa; tendrías
> que configurar a mano que arranque con Windows. El instalador lo deja como tarea
> automática.
> **Comprueba:** http://127.0.0.1:8384 abre la interfaz en la laptop.

### 3.6 Energía

Con la laptop conectada, perfil de *máximo rendimiento* y suspensión desactivada
mientras sea servidor.

> **Por qué:** si Windows suspende la laptop, el bot deja de responder y Syncthing deja
> de sincronizar. En modo ahorro, además, la GPU baja su rendimiento.

---

## 4. Sincronizar la bóveda con Syncthing

### Cómo funciona Syncthing (lo mínimo)

- Cada equipo tiene un **ID de dispositivo** (una cadena larga) derivado de un
  certificado propio. Emparejar dos equipos es decirle a cada uno "confía en este ID".
- La conexión es **directa entre tus equipos** (P2P), cifrada. Si no se ven
  directamente (por ejemplo, estás fuera de casa), usan servidores de retransmisión que
  solo pasan datos cifrados que no pueden leer.
- Una **carpeta compartida** es cualquier carpeta que decides sincronizar. Syncthing
  deja en ella un archivo oculto `.stfolder` como marca.

### 4.1 Crear la bóveda en la PC

Crea una carpeta vacía, por ejemplo `/home/<usuario>/Boveda`.

> **Por qué una carpeta nueva:** empezar limpia evita sincronizar basura antigua y te
> deja ver exactamente qué crea el hub.

### 4.2 Emparejar los equipos

En la PC: *Acciones → Mostrar ID*. En la laptop: *Agregar dispositivo remoto* y pega ese
ID. Acepta la solicitud en la PC. Repite con el móvil.

> **Comprueba:** en la interfaz de cada equipo, los otros aparecen como *Conectado*.

### 4.3 Compartir la carpeta

En la PC: *Agregar carpeta*, ruta de la bóveda, pestaña *Compartir*: marca la laptop y el
móvil. En cada uno, acepta la carpeta y elige dónde guardarla (en la laptop, por ejemplo
`C:\Users\<usuario>\Boveda`).

### 4.4 Activar el versionado en la PC

En las opciones de la carpeta, en la PC: *Versionado de archivos → Simple*.

> **Por qué:** Syncthing **no es un respaldo**. Si borras una nota en el móvil, se borra
> en todos los equipos. Con versionado simple, la PC guarda una copia de lo que llega
> modificado o borrado en la carpeta oculta `.stversions`. Es tu red de seguridad.

### 4.5 La prueba del día 1

Crea `prueba.md` en la bóveda de la PC con cualquier texto. En unos segundos debe
aparecer en la laptop y en el móvil.

> **Por qué es tan importante:** todo lo demás (bot, router, imágenes) solo escribe
> archivos y confía en que Syncthing los reparta. Si esto falla, el resto parecerá
> roto aunque no lo esté.

### 4.6 Abrir la bóveda en Obsidian

En el móvil, abre esa carpeta como bóveda. Obsidian crea dentro una carpeta
`.obsidian` con su configuración.

> **Por qué Obsidian no necesita nada especial:** una bóveda de Obsidian es solo una
> carpeta con archivos Markdown. El hub escribe archivos normales y Obsidian los muestra.
> No hay API, no hay base de datos: esa simplicidad es lo que hace todo tan robusto.

### Sobre el `.stignore`

`core` crea en la bóveda un archivo `.stignore` con patrones que Syncthing no debe
sincronizar: el estado de la interfaz de Obsidian (`workspace.json`, qué pestañas tienes
abiertas en cada equipo) y los temporales `*.tmp`. Syncthing **no sincroniza** el propio
`.stignore`: cada servidor lo crea la primera vez que arranca `core`.

### Conflictos

Si editas el mismo archivo en dos equipos antes de que se sincronicen, Syncthing guarda
las dos versiones y renombra una como `…sync-conflict….md`. El hub evita esto creando
siempre archivos nuevos con nombre único, en lugar de editar los existentes.

---

## 5. El repositorio y los secretos

### 5.1 Subir el repositorio a GitHub (una sola vez)

```bash
git init
git add .
git status        # revisa que NO aparezca .env
git commit -m "Esqueleto del hub creativo"
git branch -M main
git remote add origin https://github.com/<usuario>/hub-creativo.git
git push -u origin main
```

> **Qué hace `.gitignore`:** lista lo que Git nunca debe subir: `.env` (claves),
> `datos/` (base de datos y registros de cada equipo) y `modelos/` (gigas de modelos
> que cada equipo descarga por su cuenta).
> **Por qué revisar `git status`:** una clave subida a GitHub hay que darla por robada,
> aunque borres el archivo después (queda en el historial). Mirar antes cuesta tres segundos.

### 5.2 Clonar y crear el `.env` en cada equipo

```bash
git clone https://github.com/<usuario>/hub-creativo.git
cd hub-creativo
cp .env.example .env          # Windows: copy .env.example .env
```

Completa como mínimo:

| Variable | Qué poner | Por qué |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | El token de @BotFather | Es la "contraseña" del bot |
| `VAULT_PATH` | Ruta absoluta de la bóveda | Compose la monta en `/boveda` dentro de `core` |
| `SERVIDOR_NOMBRE` | `pc-casa` o `laptop` | Distingue los equipos en el latido y en `/estado` |
| `TELEGRAM_USUARIOS` | Vacío la primera vez | El bot te dirá tu ID (paso 6.2) |
| `LAN_IP` | Ubuntu: `127.0.0.1` por ahora. Windows: `0.0.0.0` | Solo importa cuando llegue la app web |

> **Por qué en Windows se escribe `C:/Users/...` con barras normales:** la barra
> invertida `\` tiene significado especial en muchos formatos (es el carácter de
> "escape"). Docker acepta barras normales en Windows sin problema, así que se evita el lío.

### 5.3 Leer el `docker-compose.yml`

Ábrelo y localiza estas líneas; cada una tiene su razón:

| Línea | Por qué está |
| --- | --- |
| `${VAULT_PATH:?Define VAULT_PATH en .env}` | Si falta la variable, Compose se detiene con ese mensaje en vez de montar una carpeta vacía por error |
| `./config.yaml:/app/config.yaml:ro` | Montado de solo lectura (`ro`): puedes cambiar la configuración sin reconstruir la imagen, y `core` no puede modificarla |
| `depends_on: [voz]` | Arranca `voz` antes que `core`. Solo garantiza el orden, no que `voz` ya esté listo: por eso el código tolera que tarde |
| `profiles: ["llm-local"]` en `ollama` | qwen está dormido: no arranca con el stack para no competir por CPU, RAM y GPU con Whisper, Kokoro y el router. Si algún día hace falta, se agrega `llm-local` a `COMPOSE_PROFILES` y `llm_local.activo: true` |
| `restart: unless-stopped` | Si `core` se cae, Docker lo reinicia solo, pero no si tú lo detuviste |
| `profiles: ["consulta"]` | OpenClaw no arranca hasta que pongas `COMPOSE_PROFILES=consulta`. El día 1 no te estorba |
| `openclaw` sin `env_file` | OpenClaw no debe ver `TELEGRAM_TOKEN`; si lo viera podría intentar leer el bot y provocar el 409 |

---

## 6. Primer arranque

### 6.1 Levantar el stack

```bash
./hub.sh arrancar          # Windows: .\hub.ps1 arrancar
```

> **Qué hace:** `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`.
> - `-f … -f …` combina los dos archivos: el segundo agrega la GPU a Ollama (solo si está activo).
> - `--build` construye la imagen de `core` si el código cambió.
> - `-d` deja todo corriendo en segundo plano.
>
> **Qué pasa al construir:** Docker lee `core/Dockerfile` de arriba abajo. Copia primero
> `requirements.txt` e instala las librerías, y solo después copia el código. **Por qué
> ese orden:** Docker guarda en caché cada paso. Si solo cambias código, reutiliza las
> librerías ya instaladas y la reconstrucción tarda segundos en vez de minutos.
>
> **Comprueba:** `./hub.sh estado` muestra `core` y `voz` (y `openclaw` con el perfil `consulta`) en estado *running*.

### 6.2 Obtener tu ID de Telegram

Envía `/start` al bot. Responde con tu ID.

> **Por qué:** cualquiera que encuentre tu bot puede escribirle. `core` solo atiende a
> los IDs de `TELEGRAM_USUARIOS`; al resto lo ignora en silencio. Mientras la lista está
> vacía, el bot entra en "modo configuración" y solo te dice tu ID. El código está en
> `core/app/entradas/telegram_bot.py`, clase `SoloAutorizados`.

Copia el número en `.env`:

```
TELEGRAM_USUARIOS=123456789
```

```bash
./hub.sh reiniciar
```

> **Por qué basta reiniciar y no reconstruir:** `.env` se lee al arrancar el contenedor,
> no forma parte de la imagen. Solo reconstruyes cuando cambia el código o las librerías.

### 6.3 Descargar el modelo local

```bash
./hub.sh modelos
```

> **Qué haces:** descargas el modelo base del clasificador del router (unos 470 MB, en `modelos/hf`).
> qwen (`qwen2.5:3b-instruct-q4_K_M`, unos 2 GB) **no** se descarga mientras `llm_local.activo`
> sea `false`: en el MVP está dormido para no competir por recursos. Lo que sigue explica su nombre
> por si algún día se activa.
> **Los modelos de voz no hacen falta aquí:** el contenedor `voz` los descarga solo la primera vez que
> arranca: Whisper (unos 460 MB) y Kokoro (177 MB, más solo la voz `jf_tebukuro`). Kokoro se verifica
> con su huella SHA-256 antes de usarse. Mientras descarga, el bot responde con texto.
> **Qué significa el nombre:**
> - `3b`: 3 mil millones de parámetros. Es un modelo pequeño, lo máximo razonable para
>   4 GB de VRAM.
> - `instruct`: afinado para seguir instrucciones.
> - `q4_K_M`: cuantizado a unos 4 bits por parámetro. En vez de guardar cada número con
>   16 bits, se guarda con 4. Ocupa 4 veces menos memoria a cambio de una pérdida pequeña
>   de calidad.
>
> **Para qué podría usarse:** como último respaldo del router si se agotan las suscripciones,
> en GPU y con `keep_alive` corto (carga, responde y se descarga). Hoy las dudas del router
> van a ChatGPT y Haiku, y las imágenes usan tu idea tal cual.
> **Por qué se descarga en `modelos/`:** es un bind mount; si reconstruyes el contenedor,
> el modelo sigue ahí y no vuelves a bajar 2 GB.

### 6.4 Verificar el equipo

```bash
./hub.sh chequeo
```

> **Qué revisa y por qué** (`core/scripts/chequeo.py`):
> - que el token sea válido, preguntando a Telegram quién es el bot (`getMe`);
> - que la bóveda esté montada y se pueda escribir, creando y borrando un archivo de prueba;
> - que exista `.stfolder`, o sea, que la carpeta la esté compartiendo Syncthing;
> - que exista `.obsidian`, o sea, que ya la abriste en Obsidian;
> - que Ollama responda y tenga el modelo (solo si `llm_local.activo`; si no, lo da por apagado);
> - quién escribió el último latido.
>
> Debe terminar en `Resultado: listo`. Los avisos no bloquean; los fallos sí.

### 6.5 La primera nota de verdad

En Telegram:

```
/proyecto nuevo Webtoon
/nota idea: la villana usa una máscara de zorro
tengo que terminar el storyboard del capítulo 3
/tareas
```

Abre Obsidian en el móvil y busca:

- `Proyectos/Webtoon/` con solo `_proyecto.md` (sin carpetas vacías: aparecen cuando hacen falta);
- la nota en un archivo del proyecto (con OpenClaw lo elige el redactor; sin él, `Ideas.md`);
- `terminar el storyboard del capítulo 3` en `tareas.md` (el bot quita el "tengo que");
- una línea con el enlace a la nota en `Diario/<fecha>.md`.

---

## 7. Qué pasa por dentro cuando envías un mensaje

Sigue el recorrido de *"tengo que terminar el storyboard"* con el código abierto.

| # | Qué ocurre | Dónde está | Por qué se hizo así |
| --- | --- | --- | --- |
| 1 | `core` recibe el mensaje por long polling | `main.py`, `dp.start_polling` | Sin puertos abiertos ni IP pública |
| 2 | El filtro comprueba tu ID | `telegram_bot.py`, `SoloAutorizados` | Nadie más puede escribir en tu bóveda |
| 3 | No es un comando: pasa al router | `texto_libre` → `router/cascada.py` | Comandos primero porque son gratis y exactos |
| 4 | El router prueba el clasificador local y las reglas; solo si dudan, pregunta al LLM local | `router/cascada.py`, `clasificador.py`, `llm_local.py` | Del nivel más barato al más caro |
| 5 | "tengo que" coincide con la regla de tarea, confianza 0.85 | `_ACCIONES` en `reglas.py` | Patrón claro: no hace falta ningún modelo |
| 6 | 0.85 ≥ 0.80: se ejecuta sin preguntar | `Router.nivel` y `config.yaml` | Umbrales ajustables sin tocar código |
| 7 | Se quita "tengo que" y se agrega `- [ ] …` a `tareas.md` | `limpiar_tarea`, `Boveda.agregar_tarea` | La tarea se lee limpia en Obsidian |
| 8 | Se escribe a `.tareas.md.tmp` y se renombra | `escritor.escribir_atomico` | Syncthing nunca copia un archivo a medias |
| 9 | Syncthing detecta el cambio y lo reparte | Fuera del código | El bot no sabe nada de sincronización |

Y si escribes algo ambiguo, como *"la villana usa una máscara de zorro"*: ninguna regla
coincide, la confianza queda en 0.45 (menos de 0.50), y el bot pregunta con botones.
El texto queda guardado en memoria 10 minutos esperando tu respuesta.

### Desde el 2026-09-30: lo concreto en local, lo que hay que guardar lo organiza el redactor

Con OpenClaw configurado, un mensaje sin comando (texto o voz, `procesar` en `telegram_bot.py`) sigue
este camino:

| # | Qué ocurre | Dónde está | Por qué |
| --- | --- | --- | --- |
| 1 | ¿Es una orden de frase fija? ("tarea: …", "dime mis tareas", "anota en mi diario…", "cambia al proyecto X", "estado", "limpia los temporales") | `orden_hablada` en `reglas.py` | No requiere razonar: se resuelve al instante y sin tokens |
| 2 | Si no, ChatGPT dice **qué** quieres (nota, personaje, consulta, imagen…) con un contexto corto | `router/interprete.py` | Entiende frases libres y lo que se dijo antes ("así será Aely") |
| 3 | Si es guardar algo, el **redactor** recibe tu mensaje y el contenido real del proyecto y devuelve operaciones: agregar a un archivo o a una sección de una ficha, crear un archivo o una ficha | `acciones/redactor.py` | Decidir **dónde** va cada dato necesita leer lo que ya escribiste |
| 4 | El código valida cada operación: solo agrega, no sale del proyecto, no toca `Imagenes/` ni `Analisis/`, y comprueba que tus palabras aparezcan en lo escrito (si faltan muchas, guarda también tu mensaje original, plegado) | `redactor.validar` y `redactor.cobertura` | El modelo propone; las reglas de la bóveda las impone el código |
| 5 | Si falta algo (el nombre del personaje), pregunta; tu respuesta llega como mensaje normal y se une a la anterior | `ctx.recordar(accion="pregunta")` | Sin estados especiales: el contexto viaja en `ultima_accion` |
| 6 | Si GPT no responde, la nota se guarda por tipo (`Ideas.md`, `Historia.md`…) | `notas.guardar` | Ninguna idea se pierde |

### Tres decisiones de diseño que vale la pena entender

**Escritura atómica.** Escribir un archivo lleva tiempo. Si Syncthing lo lee a mitad,
copia un archivo cortado. Por eso se escribe primero a un temporal oculto y luego se
renombra: el renombrado es instantáneo, así que el archivo nunca existe a medias. Los
temporales empiezan con punto y terminan en `.tmp`, y el `.stignore` los excluye.

**Nombres de archivo portables.** `escritor.slug` quita acentos, pasa a minúsculas y
elimina `\ / : * ? " < > |`. Motivos: Windows prohíbe esos caracteres (Syncthing no
podría copiar el archivo a la laptop), Windows no distingue `Idea.md` de `idea.md`
(chocarían) y los acentos pueden codificarse de dos formas distintas según el sistema.

**El latido.** Cada 60 segundos, `core` escribe `_hub/servidor.json` con su nombre y la
hora. Como está en la bóveda, Syncthing lo copia a los demás equipos. Al arrancar, `core`
lo lee: si otro equipo escribió hace menos de 3 minutos, se detiene. Es un segundo
candado, además del error 409 de Telegram, para no tener dos servidores activos.

---

## 8. Mover el servidor a la laptop

```bash
./hub.sh parar            # en la PC
```

Espera a que Syncthing marque la carpeta como *Actualizada* en la laptop.

```powershell
.\hub.ps1 arrancar        # en la laptop
```

> **Por qué este orden:** si arrancas la laptop antes de parar la PC, las dos pedirían
> mensajes a Telegram a la vez (409). La laptop lo detecta y se detiene; Docker la
> reintenta sola con esperas cada vez más largas, y en cuanto pares la PC, arranca.
> **Por qué esperar a Syncthing:** así la laptop empieza con la bóveda al día y con el
> latido de la PC ya viejo.
> **Si la PC se apagó de golpe:** su último latido tardará 3 minutos en caducar. O esperas,
> o pones `FORZAR_ARRANQUE=1` en el `.env` de la laptop **una sola vez** y lo vuelves a 0.

---

## 9. Pruebas y registros

### Pruebas

```bash
./hub.sh tests
```

> **Qué hace:** ejecuta `pytest` dentro del contenedor sobre `core/tests/`.
> **Por qué dentro del contenedor:** así las pruebas usan exactamente la misma versión de
> Python y de las librerías que el bot en producción.
> **Qué prueban:**
> - `test_boveda.py`: nombres portables, escritura atómica, proyectos, notas y tareas.
> - `test_router_y_referencias.py`: reglas, niveles de confianza y la inserción de
>   imágenes en la nota del personaje.
> - `test_estado.py`: latido, limpieza (nunca toca notas) y SQLite.
> - `test_bot.py`: el bot completo. Usa una "sesión falsa" que se hace pasar por Telegram:
>   captura lo que el bot enviaría en vez de enviarlo. Así se prueba el flujo real
>   (mensaje → botón → archivo en la bóveda) sin internet ni un bot de verdad.
>
> **Hábito recomendado:** ejecuta las pruebas antes de cada `git push`. Si algo que
> funcionaba se rompe, lo sabrás en segundos y no el día de la demo.

### Registros

```bash
./hub.sh logs
```

Muestra la salida de `core` en tiempo real. Además, `datos/logs/hub.log` guarda lo mismo
en formato JSON (una línea por evento), que es fácil de filtrar con herramientas.

> **Por qué fuera de la bóveda:** los registros cambian constantemente. Si estuvieran en
> la bóveda, Syncthing los copiaría al móvil sin parar. Se rotan cada día y se borran a
> los 14 días.

---

## 10. Ejercicios para afianzar

Cada uno toca una parte distinta del código y se resuelve en poco tiempo. Agrega una
prueba para cada uno en `core/tests/`.

1. **Nueva regla.** Haz que *"compra de materiales: tinta y papel"* se detecte como tarea.
   Archivo: `router/reglas.py`, lista `_ACCIONES`. Aprendes: expresiones regulares y cómo
   el router decide.
2. **Nuevo comando `/hoy`.** Que muestre la nota del día de `Diario/`. Archivo:
   `entradas/telegram_bot.py`, junto a `/tareas`. Aprendes: cómo se registra un comando
   en aiogram y cómo leer la bóveda.
3. **Umbrales.** Cambia `umbral_ejecutar` a `0.90` en `config.yaml`, ejecuta
   `./hub.sh reiniciar` y observa qué mensajes pasan a pedir confirmación. Aprendes: la
   diferencia entre configuración (sin reconstruir) y código (con reconstruir).
4. **Tipo de nota nuevo.** Agrega `lugar` (para escenarios del cómic) con su carpeta
   `Historia/Lugares`. Archivos: `config.yaml` y `reglas.py`. Aprendes: cómo la
   configuración y el código trabajan juntos.
5. **Provocar el 409 a propósito.** Con el stack activo en la PC, arranca también la
   laptop y lee los registros de la laptop. Aprendes: por qué existen el latido y la
   comprobación de arranque, viéndolos actuar.

---

Cuando todo esto funcione, el día 1 y el día 2 del plan estarán cerrados. El siguiente
paso es el día 3: entrenar el clasificador local del router con los ejemplos de
`core/app/router/datos/ejemplos.yaml`. Conviene ir escribiendo desde ya frases reales,
tal como ustedes hablan, porque de eso depende qué tan bien acierte.
