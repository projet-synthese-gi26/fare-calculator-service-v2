FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-openbsd \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN useradd -m appuser

# S'assurer que le script d'initialisation est exécutable et au format Linux
USER root
RUN apt-get update && apt-get install -y sed && rm -rf /var/lib/apt/lists/*
RUN sed -i 's/\r$//' /app/init-db.sh
RUN chmod +x /app/init-db.sh
RUN mkdir -p /app/logs && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=fare_calculator.settings

# Utiliser le script d'initialisation intelligente
CMD ["/app/init-db.sh"]