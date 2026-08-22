# tests/pipeline/test_dag.py
"""Import-test do DAG do pipeline com Airflow DagBag (Sprint 6.5).

Cobre o resíduo registrado no fechamento da Sprint 4: o encadeamento
`executar_bronze >> executar_silver >> executar_gold` só era confirmado por
leitura de código. Sem subir o scheduler, valida:

1. o parsing do módulo `pipeline/dags/pipeline_dag.py` pelo DagBag;
2. o `dag_id`, agendamento e tags declarados;
3. a estrutura de dependências de todas as tasks (ordem Bronze→Silver→Gold);
4. a integridade XCom: `executar_silver` consome o `run_id` produzido por
   `executar_bronze` (mesma task pullada na upstream).

O Airflow (`apache-airflow[postgres]==2.9.3`) é optional-dependency do
extra `pipeline` e NÃO está instalado no ambiente de desenvolvimento local
(pyproject.toml). Por isso o módulo é importado via `pytest.importorskip`:
em ambientes sem o Airflow o teste é pulado sem falha; em CI/containers com
o extra instalado ele roda como barreira real.
"""

from __future__ import annotations

import inspect

import pytest

AIRFLOW = pytest.importorskip("airflow")

from airflow.models import DagBag  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _airflow_metadata_db_ready():
    """Inicializa o metadata DB do Airflow (tabela `dag`, etc.) antes do teste.

    `DagBag.get_dag()` consulta `DagModel` no metadata DB; sem `airflow db
    init` a tabela `dag` não existe e o teste falha com
    `sqlite3.OperationalError: no such table: dag` (CI — airflow instalado).
    Em dev (sem airflow) o módulo é pulado via `importorskip` no topo.
    """
    from airflow.utils import db

    db.initdb()


def _dagbag() -> DagBag:
    import pathlib

    caminho_dag = (
        pathlib.Path(__file__).resolve().parents[2]
        / "pipeline"
        / "dags"
        / "pipeline_dag.py"
    )
    assert caminho_dag.exists(), f"DAG não encontrado: {caminho_dag}"
    dagbag = DagBag(dag_folder=str(caminho_dag), include_examples=False)
    assert not dagbag.import_errors, f"erros de import no DAG: {dagbag.import_errors}"
    return dagbag


def test_dag_parseia_sem_erros():
    dagbag = _dagbag()
    assert "observatorio_pipeline" in dagbag.dags


def test_dag_configuracao_basica():
    dag = _dagbag().get_dag("observatorio_pipeline")
    assert dag.dag_id == "observatorio_pipeline"
    # Agendamento é EXCLUSIVAMENTE externo (ADR-034): o timer systemd dispara
    # via script (despausa + trigger). `schedule=None` impede o scheduler do
    # Airflow de criar run próprio — sem isso dois relógios competiam e
    # duplicavam execuções (fix duplicação 22/08/2026).
    assert dag.schedule_interval is None
    assert dag.catchup is False
    assert "observatorio" in dag.tags
    assert dag.default_args["retries"] == 1
    assert dag.default_args["depends_on_past"] is False


def test_dag_tem_tres_tasks():
    dag = _dagbag().get_dag("observatorio_pipeline")
    # Airflow 2.9: `task_ids` é lista (set em versões mais novas) — normaliza.
    assert set(dag.task_ids) == {"executar_bronze", "executar_silver", "executar_gold"}


def test_dag_ordem_de_dependencias():
    dag = _dagbag().get_dag("observatorio_pipeline")
    bronze = dag.get_task("executar_bronze")
    silver = dag.get_task("executar_silver")
    gold = dag.get_task("executar_gold")

    assert set(bronze.downstream_task_ids) == {"executar_silver"}
    assert set(silver.upstream_task_ids) == {"executar_bronze"}
    assert set(silver.downstream_task_ids) == {"executar_gold"}
    assert set(gold.upstream_task_ids) == {"executar_silver"}
    assert set(gold.downstream_task_ids) == set()


def test_dag_xcom_run_id_bronze_para_silver():
    dag = _dagbag().get_dag("observatorio_pipeline")
    silver = dag.get_task("executar_silver")
    fonte = inspect.getsource(silver.python_callable)
    assert 'task_ids="executar_bronze"' in fonte
    assert "xcom_pull" in fonte
