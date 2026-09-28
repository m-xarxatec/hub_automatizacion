# Hub creativo

Bot de Telegram que guarda notas, tareas, imágenes y referencias en una bóveda de
Obsidian organizada por proyecto, sincronizada con Syncthing entre la PC de casa, la
laptop y el móvil. Todo corre en Docker: **el equipo donde se levanta es el servidor**.

## Qué funciona hoy (días 1 y 2)

- Bot con lista blanca de usuarios y modo configuración (te dice tu ID).
- Proyectos con estructura completa de carpetas (`/proyecto nuevo Webtoon`).
- Notas por tipo, tareas, nota del día y texto libre con botones de confirmación.
- Imágenes como referencia; con un pie como *"referencia para Zamael"* se insertan en
  `Historia/Personajes/Zamael.md` (y si no existe, ofrece crearla).
- Latido del servidor, bloqueo si otro equipo ya está activo (error 409 de Telegram).
- Limpieza diaria de temporales, registros en JSON, estado en SQLite.
- Ollama con Qwen2.5 3B **dormido**: no arranca con el stack para no competir por recursos con la
  voz y el router (perfil `llm-local`; queda como posible respaldo después del MVP).

Lo que falta, por día, está en [Hoja de ruta](#hoja-de-ruta).

> Este README es la referencia rápida. Para aprender qué hace cada paso y por qué,
> sigue **[GUIA.md](GUIA.md)**.

---

## 1. Instalaciones por equipo

Los dos servidores tienen el mismo hardware (i5 12.ª gen, 16 GB de RAM, NVIDIA de 4 GB);
solo cambia el sistema operativo.

| Qué | PC de casa (Ubuntu) | Laptop (Windows) |
| --- | --- | --- |
| Git | `sudo apt install git` | Git for Windows |
| Docker | Docker Engine | Docker Desktop con motor WSL2 |
| GPU en Docker | Driver NVIDIA + NVIDIA Container Toolkit | Solo el driver NVIDIA de Windows |
| Syncthing | Paquete del sistema como servicio | Instalador de Windows con inicio automático |
| Obsidian | Opcional (para revisar) | Opcional (para revisar) |

### Ubuntu (PC de casa)

```bash
# Git y Docker Engine
sudo apt update && sudo apt install -y git curl
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER          # cerrar sesión y volver a entrar

# Driver NVIDIA (si nvidia-smi no funciona todavía)
sudo ubuntu-drivers install            # reiniciar después

# NVIDIA Container Toolkit (guía oficial de NVIDIA; verificar si cambió)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Syncthing como servicio, también sin sesión iniciada
sudo apt install -y syncthing
systemctl --user enable --now syncthing
sudo loginctl enable-linger $USER
# Interfaz: http://127.0.0.1:8384
```

### Windows (laptop)

1. **WSL2**: en PowerShell como administrador, `wsl --install` y reiniciar.
2. **Driver NVIDIA** actualizado desde la web de NVIDIA o GeForce Experience.
3. **Docker Desktop**: instalar y, en *Settings → General*, dejar marcado *Use the WSL 2
   based engine*. No hace falta instalar nada más para la GPU.
4. **Git for Windows**. Después, en PowerShell: `git config --global core.autocrlf false`.
5. **Syncthing**: el instalador *Syncthing Windows Setup* (enlazado en la página de
   descargas de syncthing.net) lo deja arrancando solo con Windows.
6. Energía: con la laptop conectada, modo *máximo rendimiento* y suspensión desactivada
   mientras sea servidor.

### Móvil

- Android: **Syncthing-Fork** + **Obsidian**.
- iOS: **Möbius Sync** + **Obsidian** (no hay app oficial de Syncthing para iOS).
- **Telegram** con la cuenta autorizada.

### Comprobar la GPU en Docker

```
./hub.sh gpu        # Ubuntu
.\hub.ps1 gpu       # Windows
```

Debe mostrar la tabla de `nvidia-smi` con la GPU. Si falla en Windows, es lo primero
que hay que resolver antes de la demo.

---

## 2. Syncthing y la bóveda

1. Crear la carpeta de la bóveda en la PC de casa, por ejemplo `/home/<usuario>/Boveda`.
2. Abrir la interfaz de Syncthing en cada equipo y emparejarlos por su ID
   (*Acciones → Mostrar ID* en uno, *Agregar dispositivo remoto* en el otro).
3. En la PC: *Agregar carpeta*, ruta de la bóveda, compartirla con la laptop y el móvil.
4. Aceptar la carpeta en la laptop (por ejemplo `C:\Users\<usuario>\Boveda`) y en el móvil.
5. En la PC, en las opciones de la carpeta: *Versionado de archivos → Simple*.
6. Abrir esa misma carpeta como bóveda en Obsidian (en el móvil y, si quieres, en la PC).

**Prueba del día 1:** crear un archivo cualquiera en la PC y comprobar que aparece en el
móvil. Si esto no funciona, no sigas: todo lo demás depende de ello.

`core` crea al arrancar la estructura base (`00-Bandeja`, `Diario`, `Proyectos`, `_hub`)
y un `.stignore` que evita sincronizar el estado de la interfaz de Obsidian y los
temporales. Syncthing no sincroniza el `.stignore`: cada servidor lo crea la primera
vez que arranca `core`, y el móvil no lo necesita.

---

## 3. Primer arranque

**Subir el repositorio a GitHub (una sola vez, desde la carpeta descomprimida):**

```bash
git init
git add .
git commit -m "Esqueleto del hub creativo"
git branch -M main
git remote add origin https://github.com/<usuario>/hub-creativo.git
git push -u origin main
```

Antes del primer `git add`, confirma que no existe un `.env` con claves en la carpeta
(el `.gitignore` lo excluye, pero conviene revisarlo con `git status`).

**En cada equipo:**

```bash
git clone <url-del-repo> hub-creativo
cd hub-creativo
cp .env.example .env          # Windows: copy .env.example .env
```

Completa en `.env` como mínimo `TELEGRAM_TOKEN`, `VAULT_PATH` y `SERVIDOR_NOMBRE`
(`pc-casa` o `laptop`). Deja `TELEGRAM_USUARIOS` vacío la primera vez.

```bash
./hub.sh arrancar             # Windows: .\hub.ps1 arrancar
```

1. En Telegram, envía `/start` al bot: responderá con tu ID.
2. Copia el ID en `TELEGRAM_USUARIOS` (varios separados por coma) y `./hub.sh reiniciar`.
3. `./hub.sh modelos` descarga el modelo base del router (unos 470 MB, una vez por equipo). Whisper y
   Kokoro los descarga solo el contenedor `voz` al primer arranque (Kokoro verificado por SHA-256).
4. `./hub.sh chequeo` debe terminar en `Resultado: listo`.
5. En Telegram: `/proyecto nuevo Webtoon`, luego `/nota idea: primera prueba` y mira
   cómo aparece en Obsidian del móvil.

Repite los pasos en la laptop con su propio `.env` (misma bóveda vía Syncthing,
`SERVIDOR_NOMBRE=laptop`, `VAULT_PATH` con la ruta de Windows y `LAN_IP=0.0.0.0`).

---

## 4. Comandos

| Acción | Ubuntu | Windows |
| --- | --- | --- |
| Levantar con GPU | `./hub.sh arrancar` | `.\hub.ps1 arrancar` |
| Levantar sin GPU | `./hub.sh arrancar-cpu` | `.\hub.ps1 arrancar-cpu` |
| Detener todo | `./hub.sh parar` | `.\hub.ps1 parar` |
| Reiniciar tras cambiar `config.yaml` o `.env` | `./hub.sh reiniciar` | `.\hub.ps1 reiniciar` |
| Ver registros | `./hub.sh logs` | `.\hub.ps1 logs` |
| Verificar el equipo | `./hub.sh chequeo` | `.\hub.ps1 chequeo` |
| Descargar modelos | `./hub.sh modelos` | `.\hub.ps1 modelos` |
| Pruebas | `./hub.sh tests` | `.\hub.ps1 tests` |
| Entrenar el router | `./hub.sh entrenar` | `.\hub.ps1 entrenar` |
| Generar token | `./hub.sh token` | `.\hub.ps1 token` |
| Traer cambios y reconstruir | `./hub.sh actualizar` | `.\hub.ps1 actualizar` |

Si Windows bloquea el script: `powershell -ExecutionPolicy Bypass -File .\hub.ps1 arrancar`.

### Mover el servidor de la PC a la laptop

1. En la PC: `./hub.sh parar`.
2. Esperar a que Syncthing marque la carpeta como *Actualizada* en la laptop.
3. En la laptop: `.\hub.ps1 arrancar`.

Si se olvida el paso 1, la laptop no arranca: el latido de `_hub/servidor.json` o el
error 409 de Telegram lo impiden, y Docker reintenta solo hasta que la PC se detenga.

### Comandos del bot

| Comando | Qué hace |
| --- | --- |
| `/proyecto` | Ver y elegir el proyecto activo con botones |
| `/proyecto nuevo <nombre>` | Crear proyecto con todas sus carpetas |
| `/proyecto ninguno` | Guardar todo en `00-Bandeja` |
| `/nota [tipo:] <texto>` | Nota; tipos: `idea`, `historia`, `produccion`, `dialogo` |
| `/tarea <texto>` · `/tareas` | Agregar y ver pendientes del proyecto |
| `/consulta <pregunta>` | Respuesta de ChatGPT mini (o Claude Haiku si falla), con historial corto |
| `/analisis <pedido>` | Análisis a fondo de las notas del proyecto: muestra notas y tokens estimados, eliges el modelo y luego su esfuerzo con botones; resultado en `Analisis/` |
| `/modelo` | Elegir el modelo de análisis predeterminado (Opus 5.5, Sonnet 5 o GPT-6 Sol) |
| `/img <idea>` | Imagen de referencia: `.jpg` + nota hermana en `Imagenes/` del proyecto |
| `/diagnostico` | Revisa cada proveedor de imágenes sin generar nada (no gasta cuota) |
| `/estado` | Servidor, proyecto, router, Ollama, OpenClaw, cola |
| `/nuevo` | Reiniciar el contexto de conversación |
| `/limpiar` · `/limpiar simular` | Borrar temporales o ver qué borraría |
| `/reentrenar` | Entrenar el router con los ejemplos y tus correcciones (unos 3 min) |
| Texto libre | El router decide; si duda, pregunta con botones y aprende de lo que elijas |
| Imagen con pie | Referencia del proyecto, o del personaje si el pie lo nombra |

---

## 5. Estructura del repositorio

```
hub-creativo/
  docker-compose.yml       servicios: core, voz, openclaw (perfil consulta), ollama (perfil llm-local, dormido)
  docker-compose.gpu.yml   GPU NVIDIA para ollama (solo si se activa)
  .env.example             variables por equipo (copiar a .env)
  config.yaml              umbrales, proveedores, limpieza, latido
  hub.sh / hub.ps1         atajos de comandos
  core/                    bot, router, bóveda, estado (Python 3.12)
    app/
      main.py              arranque: bot + web + latido + limpieza
      entradas/            telegram_bot.py, web/
      router/              reglas, cascada, clasificador SetFit, llm_local, ejemplos
      acciones/            referencias.py (listo), imagenes, consulta, analisis...
      proveedores/         cadenas y clientes de APIs (días 3-5)
      boveda/              escritor.py, proyectos.py
      estado/              db.py, latido.py, limpieza.py
    scripts/               chequeo, descargar_modelos, generar_token, entrenar_router
    tests/                 48 pruebas rápidas + 1 lenta, incluido el bot completo sin internet
  openclaw/                Dockerfile y guía de configuración (día 5)
  voz/                     servicio de voz (fase 2)
  datos/                   SQLite, logs, temporales (no se sube ni se sincroniza)
  modelos/                 modelos locales (no se sube ni se sincroniza)
```

Los módulos pendientes tienen en su cabecera qué deben hacer y en qué día.

---

## Hoja de ruta

| Día | Objetivo | Estado |
| --- | --- | --- |
| 1 | Repositorio, Docker Compose, Syncthing en los tres equipos | Código listo; falta instalar y sincronizar |
| 2 | Bot, lista blanca, notas, tareas, proyectos, referencias | Listo |
| 3 | Router local: SetFit + LLM local + reentrenamiento con botones | Listo |
| 4 | Imágenes: ChatGPT por suscripción (Cloudflare y tensor.art desactivados hasta después del MVP); si falla, aviso + `/diagnostico` | Listo |
| 5 | OpenClaw (ChatGPT y Claude por suscripción), consulta, imágenes con ChatGPT, modo análisis y `/modelo` | Listo, ver `openclaw/README.md` |
| 6 | `/estado` con gasto y cuotas, pruebas de fallos, despliegue en la laptop | Pendiente |
| 7 | Margen, video de respaldo y ensayo | Pendiente |

---

## Problemas comunes

| Síntoma | Causa y solución |
| --- | --- |
| `Otro proceso está leyendo este bot (409)` | El stack sigue activo en el otro equipo, o hay un OpenClaw fuera del proyecto con canal de Telegram. Detenerlo. |
| `El equipo 'pc-casa' escribió un latido hace…` | Hacer `parar` en ese equipo. Si está apagado de verdad, `FORZAR_ARRANQUE=1` una vez. |
| `Define VAULT_PATH en .env` | Falta la ruta. En Windows usar barras normales: `C:/Users/...`. |
| `La bóveda no está montada` | En Windows, compartir la unidad en Docker Desktop (*Settings → Resources → File sharing*) si la bóveda está fuera de `C:\Users`. |
| El bot no responde | `./hub.sh logs`. Si no hay errores, revisar que tu ID esté en `TELEGRAM_USUARIOS`. |
| `./hub.sh gpu` falla | Ubuntu: repetir el paso del Container Toolkit. Windows: actualizar el driver NVIDIA y Docker Desktop. |
| La tablet no abre la web (fase 2) | Windows: marcar la red como *Privada*. Ubuntu: `sudo ufw allow from 192.168.0.0/16 to any port 8080`. |
| Archivos `.sync-conflict` en la bóveda | Se editó lo mismo en dos equipos a la vez. Conservar la versión buena y borrar la otra. |
