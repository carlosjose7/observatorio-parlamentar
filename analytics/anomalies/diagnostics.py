"""analytics/anomalies/diagnostics.py — monitor de deriva (ADR-065, item 5).

Informativo: taxa de sinalização do modelo CONGELADO por ano e comparação
da distribuição dos scores contra a janela de referência, gravado em
`control.anomaly_model_diagnostics`. O monitor **nunca retreina** — decisão
de retreino é humana e registrada (ADR-065, item 5).

CLI:
    python -m analytics.anomalies.model diagnose --db <duckdb>
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import structlog

from analytics.anomalies.anomalies import avaliar_criterios

logger = structlog.get_logger()

#: Tabela do monitor (append por execução — série histórica de deriva).
TABELA_DIAG = "control.anomaly_model_diagnostics"

#: Colunas gravadas por diagnóstico.
COLUNAS_DIAG = [
    "executed_at",
    "model_version",
    "manifest_sha256",
    "ano",
    "n_despesas",
    "taxa_if",
    "taxa_anomalia",
    "score_p50",
    "score_p90",
    "score_p99",
    "ref_score_p50",
    "ref_score_p90",
    "ref_score_p99",
    "delta_p99_vs_ref",
]


def calcular_diagnostico(
    fatos: pd.DataFrame,
    dim_data: pd.DataFrame | None,
    *,
    modelo,
    anos_janela: list[int],
    registro: dict,
) -> pd.DataFrame:
    """Diagnóstico de deriva por ano vs. janela de referência.

    Args:
        fatos: `gold.fact_despesa` (com `valor_liquido`, `data_sk`, …).
        dim_data: `gold.dim_data` (critérios 5/6); `None` degrada.
        modelo: `IsolationForest` ativo (inferência-only).
        anos_janela: Anos fechados da janela de referência (manifesto).
        registro: Linha do registro ativo (`model_version`, `manifest_sha256`).

    Returns:
        DataFrame no formato `COLUNAS_DIAG` (uma linha por ano da Gold).
    """
    if fatos.empty:
        return pd.DataFrame(columns=COLUNAS_DIAG)

    res = avaliar_criterios(fatos, dim_data, modelo_if=modelo)
    res["_ano"] = pd.to_numeric(res["data_sk"], errors="coerce").astype("Int64") // 10000
    janela = res[res["_ano"].isin(anos_janela)]

    def _q(series: pd.Series, q: float) -> float:
        return float(series.quantile(q)) if len(series) else float("nan")

    ref_p50 = _q(janela["if_score"], 0.50)
    ref_p90 = _q(janela["if_score"], 0.90)
    ref_p99 = _q(janela["if_score"], 0.99)

    agora = datetime.now(UTC).isoformat()
    linhas = []
    for ano, grupo in res.groupby("_ano"):
        linhas.append(
            {
                "executed_at": agora,
                "model_version": registro["model_version"],
                "manifest_sha256": registro["manifest_sha256"],
                "ano": int(ano),
                "n_despesas": int(len(grupo)),
                "taxa_if": float(grupo["criterio_if"].mean()),
                "taxa_anomalia": float(grupo["is_anomalia"].mean()),
                "score_p50": _q(grupo["if_score"], 0.50),
                "score_p90": _q(grupo["if_score"], 0.90),
                "score_p99": _q(grupo["if_score"], 0.99),
                "ref_score_p50": ref_p50,
                "ref_score_p90": ref_p90,
                "ref_score_p99": ref_p99,
                "delta_p99_vs_ref": _q(grupo["if_score"], 0.99) - ref_p99,
            }
        )
    return pd.DataFrame(linhas, columns=COLUNAS_DIAG)


def gravar_diagnostico(resultado: pd.DataFrame, *, db_path: str | Path) -> int:
    """Grava o diagnóstico em `control.anomaly_model_diagnostics` (append).

    Returns:
        Número de linhas gravadas.
    """
    import duckdb

    if resultado.empty:
        return 0
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS control")
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {TABELA_DIAG} ("
            " executed_at VARCHAR, model_version VARCHAR, manifest_sha256 VARCHAR,"
            " ano BIGINT, n_despesas BIGINT, taxa_if DOUBLE, taxa_anomalia DOUBLE,"
            " score_p50 DOUBLE, score_p90 DOUBLE, score_p99 DOUBLE,"
            " ref_score_p50 DOUBLE, ref_score_p90 DOUBLE, ref_score_p99 DOUBLE,"
            " delta_p99_vs_ref DOUBLE)"
        )
        con.register("diag", resultado[COLUNAS_DIAG])
        con.execute(f"INSERT INTO {TABELA_DIAG} SELECT * FROM diag")
    finally:
        con.close()
    logger.info(
        "anomalias_diagnostico_gravado", linhas=len(resultado), tabela=TABELA_DIAG
    )
    return len(resultado)


def executar_diagnostico(
    *,
    db_path: str | Path,
    store_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Pipeline do monitor: modelo ativo + Gold → `control.…_diagnostics`.

    Só INFERÊNCIA (nunca retreina — ADR-065, item 5). Os anos da janela de
    referência vêm do manifesto do artefato ativo.
    """
    import duckdb

    from analytics.anomalies.model import _resolver_store, carregar_modelo_ativo

    modelo, registro = carregar_modelo_ativo(db_path=db_path, store_dir=store_dir)
    manifesto_path = (
        _resolver_store(store_dir) / registro["model_version"] / "manifest.json"
    )
    anos_janela = json.loads(manifesto_path.read_text(encoding="utf-8"))["dados"]["anos"]

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        fatos = con.execute(
            "SELECT id_despesa, id_parlamentar, id_fornecedor, data_sk, valor_liquido "
            "FROM gold.fact_despesa WHERE data_sk IS NOT NULL"
        ).df()
        dim_data = con.execute("SELECT * FROM gold.dim_data").df()
    finally:
        con.close()

    resultado = calcular_diagnostico(
        fatos, dim_data, modelo=modelo, anos_janela=anos_janela, registro=registro
    )
    gravar_diagnostico(resultado, db_path=db_path)
    return resultado
