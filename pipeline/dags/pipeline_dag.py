from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

from pipeline.bronze import run_pipeline
from pipeline.camara.transform import (
    carregar_silver_despesa as silver_camara,
)
from pipeline.camara.transform import (
    carregar_silver_parlamentar as silver_parlamentar,
)
from pipeline.senado.transform import carregar_silver_despesa as silver_senado
from pipeline.senado.transform import (
    carregar_silver_parlamentar as silver_parlamentar_senado,
)
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
    """Executa as cargas Silver para as três fontes (ADR-023), Onda 2 inclusa.

    Roda em seguida da Bronze, reaproveitando o `run_id` dela (XCom) — o
    Data Quality Report fica chaveado pela mesma execução. Cada fonte é
    carregada em isolamento (falhas não derrubam as demais).
    """
    run_id = context["ti"].xcom_pull(task_ids="executar_bronze")
    storage = criar_storage()
    resultados = {
        "camara": silver_camara(storage=storage, run_id=run_id),
        "camara_parlamentares": silver_parlamentar(
            storage=storage, run_id=run_id
        ),
        "senado": silver_senado(storage=storage, run_id=run_id),
        "senado_parlamentares": silver_parlamentar_senado(
            storage=storage, run_id=run_id
        ),
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


def _executar_gold(**context):
    """Build das tabelas Gold via dbt (ADR-018/ADR-026) após Bronze→Silver.

    Roda `dbt build` completo no projeto `pipeline/gold` num SUBPROCESSO
    (mesmo motivo do teste de contrato: o adaptador dbt-duckdb mantém uma
    conexão read-write por processo — subprocesso efêmero libera o DuckDB ao
    sair, permitindo que a API o reabra read-only). `get_dbt_vars()` injeta a
    var exigida por sources/schema; sem `--vars` o dbt falha em vez de
    aplicar um default divergente (PROJECT_CONTEXT §15). Só é seguro rodar em
    processo próprio porque no worker do Airflow ninguém mais mantém conexão.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    RAIZ = Path(__file__).resolve().parents[2]
    GOLD = RAIZ / "pipeline" / "gold"
    codigo = (
        f"sys.path.insert(0, {str(RAIZ)!r})\n"
        f"sys.path.insert(0, {str(GOLD)!r})\n"
        "from dbt.cli.main import dbtRunner\n"
        "from pipeline.config import get_dbt_vars\n"
        f"r = dbtRunner().invoke([\n"
        f"    'build',\n"
        f"    '--project-dir', {str(GOLD)!r},\n"
        f"    '--profiles-dir', {str(GOLD)!r},\n"
        f"    '--vars', json.dumps(get_dbt_vars()),\n"
        "]\n"
        ")\n"
        "raise SystemExit(0 if r.success else 1)\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(bool, (str(GOLD), os.environ.get("PYTHONPATH", "")))
        ),
    }
    subprocess.run([sys.executable, "-c", codigo], env=env, check=True)
    return "gold_pronto"


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

    executar_gold = PythonOperator(
        task_id="executar_gold",
        python_callable=_executar_gold,
    )

    executar_bronze >> executar_silver >> executar_gold
