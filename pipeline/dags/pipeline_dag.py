from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

from pipeline.bronze import run_pipeline
from pipeline.camara.transform import carregar_silver_despesa as silver_camara
from pipeline.logging import configure_logging
from pipeline.senado.transform import carregar_silver_despesa as silver_senado
from pipeline.storage import criar_storage
from pipeline.transparencia.transform import (
    carregar_silver_cartao,
    carregar_silver_emenda,
)
from pipeline.watermark import AirflowVariableStore

default_args = {
    "owner": "observatorio",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _executar_bronze(**context):
    """Executa o pipeline Bronze end-to-end usando o storage de produção.

    Em produção (Airflow) o storage é MinIO (via `.env`, ADR-007/ADR-008) e o
    watermark fica em Airflow Variable (versionamento.md §2.1). O retorno é o
    `run_id` para rastreabilidade no XCom.
    """
    run = run_pipeline(
        storage=criar_storage(),
        store=AirflowVariableStore(),
    )
    return str(run.run_id)


def _executar_silver(**context):
    """Executa as cargas Silver para as três fontes (ADR-023).

    Roda em seguida da Bronze, reaproveitando o `run_id` dela (XCom) — o
    Data Quality Report fica chaveado pela mesma execução. Cada fonte é
    carregada em isolamento (falhas não derrubam as demais).
    """
    run_id = context["ti"].xcom_pull(task_ids="executar_bronze")
    storage = criar_storage()
    resultados = {
        "camara": silver_camara(storage=storage, run_id=run_id),
        "senado": silver_senado(storage=storage, run_id=run_id),
        "transparencia_cartoes": carregar_silver_cartao(
            storage=storage, run_id=run_id
        ),
        "transparencia_emendas": carregar_silver_emenda(
            storage=storage, run_id=run_id
        ),
    }
    return {
        fonte: None if resultado is None else len(resultado.aceitos)
        for fonte, resultado in resultados.items()
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

    executar_bronze = PythonOperator(
        task_id="executar_bronze",
        python_callable=_executar_bronze,
    )

    executar_silver = PythonOperator(
        task_id="executar_silver",
        python_callable=_executar_silver,
    )

    executar_bronze >> executar_silver
