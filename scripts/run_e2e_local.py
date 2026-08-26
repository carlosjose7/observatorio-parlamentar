"""scripts/run_e2e_local.py — validação end-to-end local Bronze→Silver→Gold.

Sprint 6.5: exercita a cadeia completa com as APIs REAIS (sem mocks) em modo
validação (`validacao:` de config/pipeline.yaml), limitando a janela histórica
a `--limite-periodos` períodos (incluindo a Câmara, que particiona por mês de
competência) e isolando o watermark em namespace `validacao:`. Sem o modo
validação, a Câmara puxaria a janela integral desde `mes_inicio`
(01/2015) — um backfill de 11 anos.

Fluxo espelhado no DAG (pipeline/dags/pipeline_dag.py):
  1. Bronze: `run_pipeline` (local storage + JsonFileStore, watermark isolado).
  2. Silver: as 6 cargas (`silver_despesa` x2 fontes, `silver_parlamentar` x2,
     `silver_cartao`, `silver_emenda`).
  3. Gold core: `dbt build` EXCETO os models analytics (subprocesso — a
     conexão dbt-duckdb é read-write por processo; subprocesso efêmero libera
     o arquivo para a API reabrir em read_only).
  4. Analytics: cargas de ML populam `ml_staging` (ondas 2→3→4, ADR-026) via
     `pipeline.analytics_stage.executar_etapa_analytics`.
  5. Gold analytics: `dbt build --select` dos models que leem `ml_staging`.

Uso:
    python scripts/run_e2e_local.py                       # validação (limite 2)
    python scripts/run_e2e_local.py --limite-periodos 1   # janela ainda menor
    python scripts/run_e2e_local.py --no-validacao        # backfill integral
    python scripts/run_e2e_local.py --duckdb-path data/silver/observatorio.duckdb

O DuckDB alvo é o de `DUCKDB_DATABASE_PATH` (env var > `.env`); o runner
redireciona `os.environ` ANTES de qualquer import que leia a config. Quando
`--reset`, o arquivo existente é movido para `<caminho>.bak-<ts>` — a Silver
INSERE (não faz upsert), então recriar do zero garante rebuild determinístico.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GOLD = RAIZ / "pipeline" / "gold"

sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(GOLD))


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Runner E2E local (Sprint 6.5).")
    ap.add_argument(
        "--limite-periodos",
        type=int,
        default=2,
        help="Janela truncada no modo validação (períodos). Padrão: 2.",
    )
    ap.add_argument(
        "--no-validacao",
        action="store_true",
        help="Desliga o modo validação (backfill integral da janela histórica).",
    )
    ap.add_argument(
        "--duckdb-path",
        default=None,
        help="DuckDB alvo (padrão: DUCKDB_DATABASE_PATH).",
    )
    ap.add_argument(
        "--reset",
        action="store_true",
        help="Move o DuckDB existente para .bak-<ts> antes de rebuild (Silver INSERE).",
    )
    return ap.parse_args()


def _habilitar_validacao(limite: int) -> None:
    """Liga o modo validação no config em runtime (nunca edita o YAML).

    `pipeline.bronze` referencia `get_pipeline` no módulo (import name), então
    substituir o atributo do módulo redireciona `_truncar_validacao`,
    `_camara_filtro_inicial` e `run_pipeline` sem tocar em config/pipeline.yaml.
    """
    import pipeline.bronze as bronze
    from pipeline.config import load_pipeline_settings

    cfg = load_pipeline_settings().model_copy(deep=True)
    cfg.validacao.habilitado = True
    cfg.validacao.limite_periodos = limite
    bronze.get_pipeline = lambda: cfg
    print(f"[validacao] habilitada, limite_periodos={limite}", flush=True)


def _rodar_bronze() -> str:
    from pipeline.bronze import run_pipeline
    from pipeline.logging_config import configure_logging
    from pipeline.storage import criar_storage
    from pipeline.watermark import JsonFileStore

    configure_logging()
    run = run_pipeline(storage=criar_storage(), store=JsonFileStore())
    print(f"[bronze] status={run.status} fontes_com_erro={run.fontes_com_erro}", flush=True)
    if run.fontes_com_erro:
        raise RuntimeError(f"Bronze com falha parcial: {run.fontes_com_erro}")
    return str(run.run_id)


def _rodar_silver(run_id: str) -> dict[str, int | None]:
    from pipeline.camara.transform import (
        carregar_silver_despesa as silver_camara,
    )
    from pipeline.camara.transform import (
        carregar_silver_parlamentar as silver_camara_parlamentar,
    )
    from pipeline.senado.transform import (
        carregar_silver_despesa as silver_senado,
    )
    from pipeline.senado.transform import (
        carregar_silver_parlamentar as silver_senado_parlamentar,
    )
    from pipeline.storage import criar_storage
    from pipeline.transparencia.transform import (
        carregar_silver_cartao,
        carregar_silver_emenda,
    )

    storage = criar_storage()
    cargas = {
        "silver_despesa_camara": silver_camara(storage=storage, run_id=run_id),
        "silver_parlamentar_camara": silver_camara_parlamentar(storage=storage, run_id=run_id),
        "silver_despesa_senado": silver_senado(storage=storage, run_id=run_id),
        "silver_parlamentar_senado": silver_senado_parlamentar(storage=storage, run_id=run_id),
        "silver_cartao": carregar_silver_cartao(storage=storage, run_id=run_id),
        "silver_emenda": carregar_silver_emenda(storage=storage, run_id=run_id),
    }
    resumo = {
        nome: None if res is None else len(res.aceitos)
        for nome, res in cargas.items()
    }
    print(f"[silver] {resumo}", flush=True)
    return resumo


_ML_STAGING_VAZIO: dict[str, str] = {
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


def _criar_ml_staging_vazio() -> None:
    """Cria o schema `ml_staging` VAZIO quando ausente (ADR-026).

    Os models analytics (`network_*`, `politician_similarity`, `risk_scores`,
    `expense_outliers`) leem de `ml_staging` — schema escrito EXCLUSIVAMENTE
    pelos scripts de ML (`analytics/network/network.py`, etc.), fora do dbt.
    Sem essas tabelas, o `dbt build` completo falha no Gold com "schema
    ml_staging does not exist". Mesmo contrato do teste de contrato
    (`tests/integration/test_api_gold_contrato.py`): criar vazias valida a
    cadeia Gold sem depender do sub-pipeline de ML.
    """
    import duckdb

    caminho = os.environ["DUCKDB_DATABASE_PATH"]
    con = duckdb.connect(caminho)
    try:
        con.execute("create schema if not exists ml_staging")
        for tabela, colunas in _ML_STAGING_VAZIO.items():
            con.execute(
                f"create table if not exists ml_staging.{tabela} ({colunas})"
            )
        print(
            f"[gold] ml_staging vazio garantido ({len(_ML_STAGING_VAZIO)} tabelas)",
            flush=True,
        )
    finally:
        con.close()


def _rodar_gold(selecao: str | None, exclusao: str | None, rotulo: str) -> None:
    """`dbt build` (com seletor opcional) em subprocesso — receita do DAG."""
    _criar_ml_staging_vazio()
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
    print(f"[gold] dbt build {rotulo} (subprocesso)...", flush=True)
    subprocess.run([sys.executable, "-c", "".join(argumentos)], env=env, check=True)
    print(f"[gold] build {rotulo} concluído", flush=True)


def _rodar_analytics(run_id: str) -> dict[str, int]:
    """Popula `ml_staging` (ondas de ML 2→3→4) — mesma etapa do DAG."""
    from pipeline.analytics_stage import executar_etapa_analytics

    resumo = executar_etapa_analytics(run_id)
    print(f"[analytics] {resumo}", flush=True)
    return resumo


def _resumo_final() -> None:
    import duckdb

    caminho = os.environ["DUCKDB_DATABASE_PATH"]
    print(f"\n[resumo] DuckDB: {caminho}", flush=True)
    con = duckdb.connect(caminho, read_only=True)
    try:
        tabelas = con.execute(
            "select table_name from information_schema.tables"
            " where table_schema = 'main' order by table_name"
        ).fetchall()
        for (tabela,) in tabelas:
            try:
                n = con.execute(f'select count(*) from "{tabela}"').fetchone()[0]
            except Exception:  # noqa: BLE001 — tabela sem acesso simples, segue
                n = "?"
            print(f"  {tabela}: {n} linhas", flush=True)
    finally:
        con.close()


def main() -> None:
    args = _parse_args()
    alvo = args.duckdb_path or os.environ.get("DUCKDB_DATABASE_PATH", "data/silver/observatorio.duckdb")

    if args.reset and os.path.exists(alvo):
        bak = f"{alvo}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        os.makedirs(os.path.dirname(bak) or ".", exist_ok=True)
        shutil.move(alvo, bak)
        print(f"[reset] {alvo} -> {bak}", flush=True)

    os.environ["DUCKDB_DATABASE_PATH"] = alvo
    print(f"[e2e] DuckDB alvo: {alvo}", flush=True)

    if not args.no_validacao:
        _habilitar_validacao(args.limite_periodos)

    run_id = _rodar_bronze()
    _rodar_silver(run_id)
    from pipeline.analytics_stage import (
        MODELS_ANALYTICS,
        alertar_analytics_vazio,
    )

    _rodar_gold(None, " ".join(MODELS_ANALYTICS), "core")
    _rodar_analytics(run_id)
    _rodar_gold(" ".join(MODELS_ANALYTICS), None, "analytics")
    alertar_analytics_vazio(MODELS_ANALYTICS)
    _resumo_final()
    print(f"\n[e2e] concluído. run_id={run_id}", flush=True)


if __name__ == "__main__":
    main()
