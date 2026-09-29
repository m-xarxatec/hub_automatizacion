# OpenClaw con Claude Code instalado, para reutilizar la suscripción de Claude
# (backend claude-cli) además de ChatGPT por OAuth de Codex.
# Imagen oficial: ghcr.io/openclaw/openclaw  (fijar una versión cuando funcione)
ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest
FROM ${OPENCLAW_IMAGE}

USER root
# El postinstall de npm no siempre baja el binario nativo ("claude native binary not
# installed"): se ejecuta a mano y se comprueba con --version para que falle al construir.
RUN npm install -g @anthropic-ai/claude-code \
    && node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs" \
    && claude --version \
    && npm cache clean --force
# La carpeta del volumen openclaw_claude debe existir y ser de node: si no, Docker la crea
# como root y el /login de Claude Code no puede guardar la sesión.
RUN mkdir -p /home/node/.claude && chown node:node /home/node/.claude
# Plugin puente dentro de la imagen y no montado: en Windows, Docker Desktop monta las
# carpetas con permisos 777 y OpenClaw bloquea un plugin escribible por cualquiera.
# De root y sin escritura para otros; tras cambiar el plugin hay que reconstruir.
COPY plugins/hub-puente /home/node/hub-puente
RUN chmod -R u=rwX,go=rX /home/node/hub-puente
USER node
