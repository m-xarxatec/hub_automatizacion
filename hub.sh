#!/usr/bin/env bash
# Atajos para Ubuntu. Uso: ./hub.sh <accion>
set -euo pipefail
cd "$(dirname "$0")"

GPU=(-f docker-compose.yml -f docker-compose.gpu.yml)
# core corre con tu usuario: lo que escribe en la bóveda es tuyo (Obsidian y Syncthing pueden editarlo).
export HUB_UID="${HUB_UID:-$(id -u)}" HUB_GID="${HUB_GID:-$(id -g)}"

case "${1:-ayuda}" in
  arrancar)     docker compose "${GPU[@]}" up -d --build ;;
  arrancar-cpu) docker compose up -d --build ;;
  parar)        docker compose down
                # Relevo: si hay un equipo de guardia, espera a que retome el bot (Syncthing le lleva el aviso).
                docker compose run --rm --no-deps core python -m scripts.relevo esperar || true ;;
  servidores)   docker compose run --rm --no-deps core python -m scripts.relevo ;;
  reiniciar)    docker compose restart core ;;
  logs)         docker compose logs -f --tail=100 core ;;
  estado)       docker compose ps ;;
  chequeo)      docker compose run --rm --no-deps core python -m scripts.chequeo ;;
  modelos)      docker compose run --rm --no-deps core python -m scripts.descargar_modelos ;;
  tests)        docker compose run --rm --no-deps core python -m pytest -q -p no:cacheprovider ;;
  entrenar)     docker compose run --rm --no-deps core python -m scripts.entrenar_router ;;
  token)        docker compose run --rm --no-deps core python -m scripts.generar_token ;;
  gpu)          docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi ;;
  actualizar)   git pull && docker compose "${GPU[@]}" up -d --build ;;
  permisos)     # Una vez: devuelve a tu usuario lo que core escribió como root (versiones anteriores).
                docker compose run --rm --no-deps --user root core \
                  chown -R "$HUB_UID:$HUB_GID" /boveda /datos /modelos/hf ;;
  *)
    cat <<'TXT'
Uso: ./hub.sh <accion>
  arrancar      levanta todo con GPU (reconstruye si cambió el código)
  arrancar-cpu  levanta todo sin GPU
  parar         detiene todo; con relevo, espera a que el equipo de guardia retome el bot
  servidores    quién atiende el bot, quién espera y quién está apagado (latidos en _hub/)
  reiniciar     reinicia core (tras editar config.yaml o .env)
  logs          sigue los registros de core
  estado        contenedores en marcha
  chequeo       verifica token, bóveda, Syncthing, Ollama y OpenClaw
  modelos       descarga los modelos locales (una vez por equipo)
  tests         ejecuta las pruebas dentro del contenedor
  entrenar      entrena el router local (ejemplos, aprendidos de la IA y correcciones)
  token         genera un token aleatorio para .env
  gpu           comprueba que Docker ve la GPU NVIDIA
  actualizar    git pull y reconstruir
  permisos      devuelve a tu usuario la bóveda, datos/ y modelos/hf (una vez, con el stack parado)
TXT
    ;;
esac
