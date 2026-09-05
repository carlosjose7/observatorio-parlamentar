FROM python:3.11-slim AS base

WORKDIR /app

COPY . .
# Instala APÓS copiar o código para o editable install descobrir os pacotes
# (se instalado antes, o finder fica com MAPPING vazio — a API só funciona
# hoje por acaso, porque o uvicorn roda com cwd=/app no sys.path).
RUN pip install --no-cache-dir -e ".[api]" \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

FROM base AS dev
RUN pip install --no-cache-dir -e ".[dev-dashboard]"

FROM base AS production
# Diretório gravável do contador de visitas (Sprint 12): o mount
# ./data:/app/data é :ro (ADR-026), então o DuckDB de visitas vive em
# volume nomeado montado em /app/data/analytics (ver docker-compose.yml).
# O mkdir aqui garante ownership appuser herdada pelo volume no 1º uso.
RUN mkdir -p /app/data/analytics && chown appuser:appuser /app/data/analytics
USER appuser
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
