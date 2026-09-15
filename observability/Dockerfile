# Exporter Prometheus do pipeline (Sprint 22, ADR-051, Onda 2).
# Processo longa-vida que coleta do DuckDB Gold em read_only (ADR-026) a
# cada 60s e serve métricas para scrape interno (nunca via Nginx).
FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r observability/requirements.txt \
    && useradd --create-home --uid 10002 exporter \
    && chown -R exporter:exporter /app

USER exporter
EXPOSE 8001
CMD ["python", "observability/pipeline_exporter.py"]
