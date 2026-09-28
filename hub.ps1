# Atajos para Windows (PowerShell). Uso: .\hub.ps1 <accion>
# Si Windows bloquea el script:  powershell -ExecutionPolicy Bypass -File .\hub.ps1 <accion>
param([string]$accion = "ayuda")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$gpu = @("-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml")

switch ($accion) {
    "arrancar"     { docker compose @gpu up -d --build }
    "arrancar-cpu" { docker compose up -d --build }
    "parar"        { docker compose down }
    "reiniciar"    { docker compose restart core }
    "logs"         { docker compose logs -f --tail=100 core }
    "estado"       { docker compose ps }
    "chequeo"      { docker compose run --rm --no-deps core python -m scripts.chequeo }
    "modelos"      { docker compose run --rm --no-deps core python -m scripts.descargar_modelos }
    "tests"        { docker compose run --rm --no-deps core python -m pytest -q -p no:cacheprovider }
    "entrenar"     { docker compose run --rm --no-deps core python -m scripts.entrenar_router }
    "token"        { docker compose run --rm --no-deps core python -m scripts.generar_token }
    "gpu"          { docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi }
    "actualizar"   { git pull; docker compose @gpu up -d --build }
    default {
        @"
Uso: .\hub.ps1 <accion>
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
"@
    }
}
