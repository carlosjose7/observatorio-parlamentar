FROM apache/airflow:2.9.3-python3.11

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# O pacote vive em /opt/airflow/pipeline (não /opt/airflow/dags): em produção
# o docker-compose monta ./pipeline:/opt/airflow/pipeline (código vivo) e aponta
# DAGS_FOLDER=/opt/airflow/pipeline/dags. Se copiado para /opt/airflow/dags, o
# bind mount do compose sobrescreveria o pacote instalado e quebraria o import.
COPY pyproject.toml /opt/airflow/
COPY . /opt/airflow/pipeline/

USER airflow
# Constraints oficiais do Airflow 2.9.3 (python 3.11): sem elas, o resolver
# pip faz backtracking infinito entre dbt-core/duckdb e a árvore do Airflow
# (ResolutionTooDeep: 200000). O constraints file fixa as versões compatíveis
# e reduz o espaço de busca do resolver.
RUN pip install --no-cache-dir \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.3/constraints-3.11.txt" \
    -e ".[pipeline,analytics]"
# duckdb ACIMA do pin do constraints (1.0.0 → 1.5.5, pyproject): o storage
# do Gold é 1.5.5 e o formato quebra entre minors ("field id mismatch" no
# checkpoint, 10/09/2026). Constraints vazio só nesta camada para não
# reabrir o backtracking do resolver acima. dbt-duckdb 1.8 aceita
# `duckdb>=1.0.0` sem teto — compatível.
RUN PIP_CONSTRAINT=/dev/null pip install --no-cache-dir "duckdb==1.5.5"

ENV PYTHONPATH=/opt/airflow:$PYTHONPATH
