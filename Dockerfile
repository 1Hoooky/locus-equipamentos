FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências de sistema para psycopg e Pillow/WeasyPrint (etiquetas em PDF, Fase 1).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    fonts-liberation \
    shared-mime-info \
    libzbar0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
ARG REQUIREMENTS_FILE=requirements/prod.txt
RUN pip install --no-cache-dir -r ${REQUIREMENTS_FILE}

COPY . .

# Garantia independente do que chegar no contexto de build: se o checkout
# que gerou este contexto rodou em uma máquina/editor que normalizou o
# arquivo para CRLF (comum em Windows/git core.autocrlf) e/ou perdeu o bit
# de execução (comum ao extrair um .zip), o container falha ao iniciar sem
# nenhum log — nem o primeiro echo do script roda, porque o próprio exec()
# do ENTRYPOINT falha antes de qualquer coisa. sed remove um eventual CR
# de fim de linha (idempotente: não faz nada se já estiver em LF) e chmod
# garante o bit de execução, não importa como o arquivo chegou aqui.
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh

RUN adduser --disabled-password --no-create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["./docker/entrypoint.sh"]
