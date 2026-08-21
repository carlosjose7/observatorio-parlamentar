from datetime import datetime, timedelta

import structlog
from airflow import DAG
from airflow.operators.python import PythonOperator

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

logger = structlog.get_logger()

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

    ADR-026: os models analytics (`ml_staging.*`) são escritos EXCLUSIVAMENTE
    pelos scripts de ML (`analytics/...`), fora do dbt. Antes do build,
    garantimos o schema `ml_staging` vazio (se ausente) para o dbt compilar —
    mesmo contrato do `scripts/run_e2e_local.py` e do teste de contrato
    (`tests/integration/test_api_gold_contrato.py`). Os scripts de ML rodam
    como etapa separada e populam essas tabelas.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    # Garante o schema `ml_staging` vazio (ADR-026) — tabelas de controle.
    _garantir_ml_staging_vazio()

    RAIZ = Path(__file__).resolve().parents[2]
    GOLD = RAIZ / "pipeline" / "gold"
    codigo = (
        "import json\n"
        "import sys\n"
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


def _garantir_ml_staging_vazio() -> None:
    """Cria o schema `ml_staging` VAZIO quando ausente (ADR-026).

    Os models analytics (`network_*`, `politician_similarity`, `risk_scores`,
    `expense_outliers`) leem de `ml_staging` — schema escrito EXCLUSIVAMENTE
    pelos scripts de ML (`analytics/network/network.py`, etc.), fora do dbt.
    Sem essas tabelas, o `dbt build` completo falha no Gold com "schema
    ml_staging does not exist". Mesmo contrato do teste de contrato
    (`tests/integration/test_api_gold_contrato.py`): criar vazias valida a
    cadeia Gold sem depender do sub-pipeline de ML.
    """
    import os

    import duckdb

    ML_STAGING_VAZIO: dict[str, str] = {
        "network_edges": (
            " id_parlamentar bigint, id_fornecedor bigint, periodo bigint,"
            " valor_total double, run_id varchar, pipeline_version varchar,"
            " execution_timestamp varchar, source_version varchar"
        ),
        "network_nodes": (
            " id_no bigint, tipo_no varchar, periodo bigint, pagerank double,"
            " degree_centrality double, comunidade_id bigint, run_id varchar,"
            " pipeline_version varchar, execution_timestamp varchar,"
            " source_version varchar"
        ),
        "politician_similarity": (
            " id_parlamentar_a bigint, id_parlamentar_b bigint, periodo bigint,"
            " num_fornecedores_compartilhados bigint, similaridade double,"
            " run_id varchar, pipeline_version varchar, execution_timestamp varchar,"
            " source_version varchar"
        ),
        "expense_outliers": (
            " id_despesa bigint, id_parlamentar bigint, id_fornecedor bigint,"
            " data_sk bigint, valor_liquido double, zscore double, if_score double,"
            " criterio_zscore boolean, criterio_if boolean,"
            " criterio_fornecedor_poucos_clientes boolean, criterio_empresa_nova boolean,"
            " criterio_valores_identicos boolean, criterio_dia_sem_sessao boolean,"
            " num_criterios bigint, is_anomalia boolean, run_id varchar,"
            " pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar"
        ),
        "risk_scores": (
            " periodo bigint, id_parlamentar bigint,"
            " supplier_concentration_score double, political_exposure_score double,"
            " supplier_dependency_score double, expense_anomaly_score double,"
            " network_influence_score double, risk_index double,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar"
        ),
    }
    caminho = os.environ["DUCKDB_DATABASE_PATH"]
    con = duckdb.connect(caminho)
    try:
        con.execute("create schema if not exists ml_staging")
        for tabela, colunas in ML_STAGING_VAZIO.items():
            con.execute(f"create table if not exists ml_staging.{tabela} ({colunas})")
        logger.info(
            "ml_staging_garantido",
            tabelas=len(ML_STAGING_VAZIO),
        )
    finally:
        con.close()


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
