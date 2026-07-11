from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "observatorio",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="observatorio_pipeline",
    description="Pipeline principal de ingestão e transformação de dados"
    " parlamentares (Câmara, Senado, CGU)",
    default_args=default_args,
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["observatorio", "principal"],
) as dag:

    def _check_sources(**context):
        print("Verificando fontes de dados...")
        return "OK"

    check_sources = PythonOperator(
        task_id="check_sources",
        python_callable=_check_sources,
    )

    check_sources
