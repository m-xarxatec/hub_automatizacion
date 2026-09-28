"""Genera un token aleatorio para OPENCLAW_GATEWAY_TOKEN o WEB_PIN.

Uso:  docker compose run --rm --no-deps core python -m scripts.generar_token
"""

import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(32))
