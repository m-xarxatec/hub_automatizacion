#!/usr/bin/env bash
# Atajos para Ubuntu. Uso: ./hub.sh <accion>
set -euo pipefail
cd "$(dirname "$0")"

GPU=(-f docker-compose.yml -f docker-compose.gpu.yml)

case "${1:-ayuda}" in
  arrancar)     docker compose "${GPU[@]}" up -d --build ;;
  arrancar-cpu) docker compose up -d --build ;;
  parar)        docker compose down ;;
  reiniciar)    docker compose restart core ;;
  logs)         docker compose logs -f --tail=100 core ;;
  estado)       docker compose ps ;;
  chequeo)      docker compose run --rm --no-deps core python -m scripts.chequeo ;;
  modelos)      docker compose run --rm --no-deps core python -m scripts.descargar_modelos ;;
  tests)        docker compose run --rm --no-deps core python -m pytest -q ;;
  entrenar)     docker compose run --rm --no-deps core python -m scripts.entrenar_router ;;
  token)        docker compose run --rm --no-deps core python -m scripts.generar_token ;;
  gpu)          docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi ;;
  actualizar)   git pull && docker compose "${GPU[@]}" up -d --build ;;
  *)
    cat <<'TXT'
Uso: ./hub.sh <accion>
  arrancar      levanta todo con GPU (reconstruye si cambió el código)
  arrancar-cpu  levanta todo sin GPU
  parar         detiene todo (hacerlo antes de mover el servidor a otro equipo)
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
TXT
    ;;
esac
