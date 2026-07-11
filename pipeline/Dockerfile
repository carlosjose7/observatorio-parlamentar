FROM apache/airflow:2.9.3-python3.11

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /opt/airflow/
COPY . /opt/airflow/dags/

USER airflow
RUN pip install --no-cache-dir -e ".[pipeline]"

ENV PYTHONPATH=/opt/airflow/dags:$PYTHONPATH
