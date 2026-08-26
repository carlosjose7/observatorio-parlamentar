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


def _rodar_dbt(selecao: str | None, exclusao: str | None, rotulo: str) -> str:
    """`dbt build` em SUBPROCESSO, com seletor opcional de models (ADR-018/026).

    Subprocesso efêmero porque a conexão dbt-duckdb é read-write por processo —
    ao sair, libera o DuckDB para a próxima etapa/API read-only. `get_dbt_vars()`
    injeta a var exigida por sources/schema; sem `--vars` o dbt falha em vez de
    aplicar um default divergente (PROJECT_CONTEXT §15).
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    RAIZ = Path(__file__).resolve().parents[2]
    GOLD = RAIZ / "pipeline" / "gold"
    argumentos = [
        "import json\n",
        "import sys\n",
        f"sys.path.insert(0, {str(RAIZ)!r})\n",
        f"sys.path.insert(0, {str(GOLD)!r})\n",
        "from dbt.cli.main import dbtRunner\n",
        "from pipeline.config import get_dbt_vars\n",
        "invocacao = [\n",
        "    'build',\n",
        f"    '--project-dir', {str(GOLD)!r},\n",
        f"    '--profiles-dir', {str(GOLD)!r},\n",
        "    '--vars', json.dumps(get_dbt_vars()),\n",
    ]
    if selecao:
        argumentos.append(f"    '--select', {selecao!r},\n")
    if exclusao:
        argumentos.append(f"    '--exclude', {exclusao!r},\n")
    argumentos.append("]\n")
    argumentos.append("raise SystemExit(0 if dbtRunner().invoke(invocacao).success else 1)\n")

    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(bool, (str(GOLD), os.environ.get("PYTHONPATH", "")))
        ),
    }
    subprocess.run([sys.executable, "-c", "".join(argumentos)], env=env, check=True)
    logger.info("dbt_build_ok", etapa=rotulo)
    return rotulo


def _executar_gold_core(**context):
    """Build CORE do Gold via dbt: dimensões, fatos e agregados puro-SQL.

    Exclui os cinco models analytics que leem `source('ml_staging', ...)` —
    eles só têm conteúdo depois da task `executar_analytics` (ADR-026) e são
    materializados por `executar_gold_analytics`. Antes do build, garante o
    schema `ml_staging` vazio (se ausente) e as Silver CGU vazias quando a
    fonte não trouxe dados — sem isso o build falharia com "table does not
    exist".
    """
    from pipeline.analytics_stage import MODELS_ANALYTICS

    _garantir_ml_staging_vazio()
    _garantir_silver_cgu_vazio()
    return _rodar_dbt(None, " ".join(MODELS_ANALYTICS), "gold_core")


def _executar_analytics(**context):
    """Popula `ml_staging` (ondas de ML 2→3→4) sobre o Gold core materializado.

    Repassa o `run_id` da Bronze (XCom) para rastreabilidade ponta a ponta.
    A escrita fica restrita a `ml_staging` — fronteira ADR-026.
    """
    from pipeline.analytics_stage import executar_etapa_analytics

    run_id = context["ti"].xcom_pull(task_ids="executar_bronze")
    resumo = executar_etapa_analytics(run_id)
    return resumo


def _executar_gold_analytics(**context):
    """Build ANALYTICS do Gold via dbt: os cinco models que leem `ml_staging`.

    Roda DEPOIS de `executar_analytics`; é o que materializa `expense_outliers`,
    `network_nodes`, `network_edges`, `politician_similarity` e `risk_scores`
    no Gold que a API expõe (ADR-026/ADR-021). Ao final, guardrail registra
    warning se houver fatos mas alguma tabela analítica ficou vazia
    (sintoma do fio solto corrigido no ADR-035).
    """
    from pipeline.analytics_stage import (
        MODELS_ANALYTICS,
        alertar_analytics_vazio,
    )

    resultado = _rodar_dbt(" ".join(MODELS_ANALYTICS), None, "gold_analytics")
    alertar_analytics_vazio(MODELS_ANALYTICS)
    return resultado


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


def _garantir_silver_cgu_vazio() -> None:
    """Cria `silver_cartao`/`silver_emenda` VAZIAS quando a CGU não trouxe dados.

    A CGU (cartão CPGF/emendas) pode não retornar transações em um período
    (ex: janela curta de validação no HML, ou fonte sem dados recentes). A
    Silver então não cria as tabelas, e o `dbt build` completo falha no Gold
    com "table silver_cartao/silver_emenda does not exist" — mesmo sintoma do
    `ml_staging` (ADR-026). Schema declarativo de `pipeline/schemas_silver.py`
    (fonte única): cria a tabela no schema `main` do DuckDB da Silver/Gold.
    """
    import os

    import duckdb

    from pipeline.schemas_silver import SCHEMAS_SILVER

    alvos = ("silver_cartao", "silver_emenda")
    caminho = os.environ["DUCKDB_DATABASE_PATH"]
    con = duckdb.connect(caminho)
    try:
        for tabela in alvos:
            existentes = {
                r[0]
                for r in con.execute(
                    "select table_name from information_schema.tables"
                    " where table_schema = 'main'"
                ).fetchall()
            }
            if tabela in existentes:
                continue
            colunas = ", ".join(
                f'"{nome}" {tipo}' for nome, (tipo, _) in SCHEMAS_SILVER[tabela].items()
            )
            con.execute(f'create table "{tabela}" ({colunas})')
        logger.info("silver_cgu_garantido", tabelas=list(alvos))
    finally:
        con.close()


with DAG(
    dag_id="observatorio_pipeline",
    description="Pipeline principal de ingestão e transformação de dados"
    " parlamentares (Câmara, Senado, CGU)",
    default_args=default_args,
    # Agendamento EXCLUSIVAMENTE externo (ADR-034): o timer systemd
    # (observatorio-pipeline.timer) dispara o `run_pipeline_daily.sh`, que
    # despausa e dispara o DAG. `schedule=None` impede o scheduler interno do
    # Airflow de criar run próprio — sem isso, dois relógios independentes
    # (systemd + Airflow `@daily`) competiam e duplicavam execuções.
    schedule=None,
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

    executar_gold_core = PythonOperator(
        task_id="executar_gold_core",
        python_callable=_executar_gold_core,
    )

    executar_analytics = PythonOperator(
        task_id="executar_analytics",
        python_callable=_executar_analytics,
    )

    executar_gold_analytics = PythonOperator(
        task_id="executar_gold_analytics",
        python_callable=_executar_gold_analytics,
    )

    executar_bronze >> executar_silver >> executar_gold_core
    executar_gold_core >> executar_analytics >> executar_gold_analytics
