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
    -e ".[pipeline]"

ENV PYTHONPATH=/opt/airflow:$PYTHONPATH
