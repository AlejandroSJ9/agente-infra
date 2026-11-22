# Imagen del agente: biblioteca (RAG), calculadora y, más adelante, el bot.
# python:3.12-slim es multi-arquitectura: funciona igual en tu PC (x86) y en el servidor Graviton (ARM).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/cache/huggingface

WORKDIR /app

# PyTorch versión CPU primero: evita descargar gigas de librerías de GPU que no hay en el servidor.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Dependencias antes que el código: si solo cambia el código, Docker reutiliza esta capa (más rápido).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Seguridad: el contenedor no corre como root. UID 1000 = usuario "ubuntu" del servidor,
# así puede escribir en la carpeta datos/ montada desde el host.
RUN useradd --create-home --uid 1000 agente && mkdir -p /cache && chown -R agente /cache /app
USER agente

CMD ["python", "-m", "pytest", "-q"]
