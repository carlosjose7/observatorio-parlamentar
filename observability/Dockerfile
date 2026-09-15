# Exporter Prometheus do pipeline (Sprint 22, ADR-051, Onda 2).
# Processo longa-vida que coleta do DuckDB Gold em read_only (ADR-026) a
# cada 60s e serve métricas para scrape interno (nunca via Nginx).
FROM python:3.11-slim

WORKDIR /app

# `python observability/pipeline_exporter.py` põe `observability/` no
# sys.path — sem isto `from api.repo import ...` falha (crash-loop visto
# em prod 15/09/2026). Mesmo precedente do pipeline/Dockerfile.
ENV PYTHONPATH=/app:$PYTHONPATH

COPY . .

RUN pip install --no-cache-dir -r observability/requirements.txt \
    && useradd --create-home --uid 10002 exporter \
    && chown -R exporter:exporter /app

USER exporter
EXPOSE 8001
CMD ["python", "observability/pipeline_exporter.py"]
