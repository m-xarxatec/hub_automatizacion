FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# torch solo CPU en su propia capa: pesa mucho y cambia poco, así Docker la
# reutiliza aunque cambie requirements.txt. La GPU queda libre para Ollama.
RUN pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests

CMD ["python", "-m", "app.main"]
