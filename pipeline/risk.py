"""pipeline/risk.py - scores de risco e `risk_index` (Sprint 5, Onda 4).

Implementa a Onda 4 (ADR-027/ADR-029): os **5 scores individuais** do §9
com suas fórmulas fechadas no ADR-027 e a **composição final** `risk_index`
com pesos configuráveis (`config/analytics.yaml -> risk.pesos`, ADR-029 -
baseline 0.2 uniforme vigente). O módulo NÃO redesenha nenhuma fórmula:
consome as fontes já existentes das Ondas anteriores e apenas agrega +
normaliza + pondera.

Fontes dos raws (grão `(periodo, id_parlamentar)`):

| Score (ADR-027) | Raw | Fonte |
|---|---|---|
| `supplier_concentration_score` | `hhi_p` (ADR-021) | Gold `supplier_concentration` |
| `political_exposure_score` | média_{f in F_p} (n_f - 1) | `fact_despesa` promovido |
| `supplier_dependency_score` | média_{f in F_p} dep_f (HHI por fornecedor) | `fact_despesa` promovido |
| `expense_anomaly_score` | a_p = anomalias de p / despesas de p | `ml_staging.expense_outliers` (Onda 2) |
| `network_influence_score` | pr_p (PageRank do nó parlamentar) | `ml_staging.network_nodes` (Onda 3) |

Antes da ponderação, cada score é **normalizado Min-Max para [0, 1]**
(ADR-003) usando a feature `minmax` da Feature Store (ADR-028) - a função
reutilizável `pipeline/analytics.normalizar_minmax`, NÃO uma versão solta
aqui. O `risk_index` = `sum_i w_i * score_i(p)`, `w_i` lidos de `risk.pesos`
(fonte única ADR-008/ADR-029 - nunca constantes no código).

Saída: por exigência do ADR-026 (Opção A), Python escreve **exclusivamente**
no schema `ml_staging` (DuckDB, single-writer) - aqui `ml_staging.risk_
scores`; o dbt consome como `source()` e materializa a Gold `risk_scores`
(model regular com `schema.yml`, ADR-021). Recálculo total por execução,
chaveado por `(run_id, periodo)` (mesmo padrão de anomalies/network).
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import structlog

from pipeline.analytics import normalizar_minmax
from pipeline.config import SCORES_RISCO, get_analytics
from pipeline.features import carregar_registry

logger = structlog.get_logger()

#: Grão das colunas de auditoria persistidas (padrão Silver/Gold).
COLUNAS_AUDITORIA = [
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

#: Ordem das colunas de score no staging (idêntica à ordem do risk_index).
SCORES = list(SCORES_RISCO)

#: DDL da tabela vazia do contrato `ml_staging` (dbt consome source mesmo
#: sem linhas - ADR-026; schema.yml testa FK sobre estas tabelas no build
#: de Fase 1). Tipos espelham o que o `CREATE TABLE AS SELECT` do lote
#: produz (float -> double; ids -> bigint).
_DDL_VAZIO_RISK = (
    "CREATE TABLE ml_staging.risk_scores ("
    " periodo bigint, id_parlamentar bigint,"
    " supplier_concentration_score double, political_exposure_score double,"
    " supplier_dependency_score double, expense_anomaly_score double,"
    " network_influence_score double, risk_index double,"
    " run_id varchar, pipeline_version varchar, execution_timestamp varchar,"
    " source_version varchar)"
)


def _periodo_do_data_sk(data_sk: int) -> int:
    """Ano de um `data_sk` YYYYMMDD (grão das analíticas §7/ADR-021)."""
    return int(str(int(data_sk))[:4])


def _periodos_do_fato(fatos: pd.DataFrame, coluna_data: str = "data_sk") -> list[int]:
    """Anos distintos presentes no fato (mesma derivação da Onda 3)."""
    if fatos is None or fatos.empty:
        return []
    return sorted(
        {_periodo_do_data_sk(ts) for ts in fatos[coluna_data].dropna().unique()}
    )


def _df_concentracao(
    concentracao: pd.DataFrame, coluna_periodo: str = "ano"
) -> pd.DataFrame:
    """Raw `supplier_concentration_score` = `hhi_p` (ADR-021).

    A Gold `supplier_concentration` já entrega HHI por parlamentar/ano —
    fonte direta (Onda 3, ADR-021), sem recalcular aqui.
    """
    if concentracao is None or concentracao.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])
    return (
        concentracao.rename(columns={coluna_periodo: "periodo", "hhi": "raw"})
        .loc[:, ["periodo", "id_parlamentar", "raw"]]
        .copy()
    )


def _df_exposure(fatos: pd.DataFrame) -> pd.DataFrame:
    """Raw `political_exposure_score` = média_{f∈F_p} (n_f - 1) (ADR-027.2).

    Para cada fornecedor `f`: `n_f` = nº de parlamentares que o usam no
    período. Exposição do parlamentar `p` = média sobre `F_p` de `(n_f - 1)`
    (fornecedor usado por 1 parlamentar -> contribuição 0). Usa o fato
    PROMOVIDO como universo (ADR-018).

    A média é sobre o CONJUNTO DE FORNECEDORES DISTINTOS de p no período
    (`F_p`), NÃO sobre despesas — para isso o fato é reduzido a
    `(periodo, id_parlamentar, id_fornecedor)` distinto antes da média
    (um fornecedor com mais lançamentos não pesa mais no indicador, como
    exigiria a leitura literal do ADR-027).
    """
    if fatos is None or fatos.empty or "id_fornecedor" not in fatos.columns:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])

    trabalho = fatos.dropna(subset=["id_parlamentar", "id_fornecedor"]).copy()
    if trabalho.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])
    trabalho["periodo"] = trabalho["data_sk"].map(_periodo_do_data_sk)

    n_fornecedor = (
        trabalho.groupby(["periodo", "id_fornecedor"])["id_parlamentar"]
        .nunique()
        .rename("n_f")
        .reset_index()
    )
    # Reduz ao grão do conjunto `F_p` (fornecedores distintos de p no
    # período) — a unidade de média do ADR-027 é o FORNECEDOR.
    fornecedores_parlamentar = (
        trabalho[["periodo", "id_parlamentar", "id_fornecedor"]]
        .drop_duplicates()
    )
    com_contagem = fornecedores_parlamentar.merge(
        n_fornecedor, on=["periodo", "id_fornecedor"], how="left"
    )
    com_contagem["contribuicao"] = (com_contagem["n_f"] - 1).fillna(0.0)

    return (
        com_contagem.groupby(["periodo", "id_parlamentar"])["contribuicao"]
        .mean()
        .rename("raw")
        .reset_index()
    )


def _df_dependency(fatos: pd.DataFrame) -> pd.DataFrame:
    """Raw `supplier_dependency_score` = média_{f in F_p} dep_f (ADR-027.3).

    `dep_f = SUM_p (v_{p,f} / SUM_{p'} v_{p',f})^2` — HHI do lado do
    FORNECEDOR (concentração da dependência, granularidade do BACKLOG item
    173). Dependência do parlamentar = média de `dep_f` sobre seus
    fornecedores.

    O HHI pressupõe `v_{p,f} >= 0` (share ∈ [0, 1] e `dep_f ∈ [1/n, 1]`).
    Essa premissa é garantida a MONTANTE pelo gate de qualidade Silver
    (`pipeline/quality.schema_silver_despesa` — `valor_liquido` Pandera
    `ge(0)`, ADR-013): valores negativos/estornos vão à QUARENTENA na
    carga Silver e nunca chegam ao `fact_despesa` que este módulo lê; o
    mesmo contrato é reafirmado no Gold (`nao_negativo` em
    `fact_despesa.schema.yml`). Dependência = média sobre o conjunto `F_p`.
    """
    if fatos is None or fatos.empty or "id_fornecedor" not in fatos.columns:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])

    trabalho = fatos.dropna(subset=["id_parlamentar", "id_fornecedor"]).copy()
    if trabalho.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])
    trabalho["periodo"] = trabalho["data_sk"].map(_periodo_do_data_sk)
    trabalho["valor"] = pd.to_numeric(trabalho["valor_liquido"], errors="coerce").fillna(
        0.0
    )

    share_fornecedor = (
        trabalho.groupby(["periodo", "id_fornecedor", "id_parlamentar"])["valor"]
        .sum()
        .rename("valor_par_f")
        .reset_index()
    )
    total_fornecedor = (
        share_fornecedor.groupby(["periodo", "id_fornecedor"])["valor_par_f"]
        .sum()
        .rename("total_fornecedor")
        .reset_index()
    )
    com_share = share_fornecedor.merge(
        total_fornecedor, on=["periodo", "id_fornecedor"], how="left"
    )
    com_share["share"] = com_share["valor_par_f"] / com_share["total_fornecedor"]
    dep_f = (
        com_share.groupby(["periodo", "id_fornecedor"])["share"]
        .apply(lambda s: float((s**2).sum()))
        .rename("dep_f")
        .reset_index()
    )

    por_parlamentar = trabalho[["periodo", "id_parlamentar", "id_fornecedor"]].drop_duplicates()
    return (
        por_parlamentar.merge(dep_f, on=["periodo", "id_fornecedor"], how="left")
        .groupby(["periodo", "id_parlamentar"])["dep_f"]
        .mean()
        .rename("raw")
        .reset_index()
    )


def _df_anomalia(outliers: pd.DataFrame) -> pd.DataFrame:
    """Raw `expense_anomaly_score` = a_p (ADR-027.4).

    `a_p = |despesas anômalas de p| / |despesas de p|` — anomalia =
    `is_anomalia` do `ml_staging.expense_outliers` (Onda 2, ADR-002/§10).
    Valores de `data_sk` derivam o período.
    """
    if outliers is None or outliers.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])

    trabalho = outliers.dropna(subset=["id_parlamentar"]).copy()
    if trabalho.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])
    trabalho["periodo"] = pd.to_numeric(
        trabalho["data_sk"], errors="coerce"
    ).map(_periodo_do_data_sk)

    total = (
        trabalho.groupby(["periodo", "id_parlamentar"])
        .size()
        .rename("total")
        .reset_index()
    )
    anomalias = (
        trabalho[trabalho["is_anomalia"]]
        .groupby(["periodo", "id_parlamentar"])
        .size()
        .rename("anomalias")
        .reset_index()
    )
    return (
        total.merge(anomalias, on=["periodo", "id_parlamentar"], how="left")
        .fillna({"anomalias": 0})
        .assign(raw=lambda d: d["anomalias"] / d["total"])
        .loc[:, ["periodo", "id_parlamentar", "raw"]]
    )


def _df_influencia(nos: pd.DataFrame) -> pd.DataFrame:
    """Raw `network_influence_score` = pr_p (ADR-027.5).

    PageRank do nó PARLAMENTAR no `ml_staging.network_nodes` (Onda 3,
    ADR-030). `id_no` com `tipo_no == 'parlamentar'` é o `id_parlamentar`.
    """
    if nos is None or nos.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])
    parl = nos[nos["tipo_no"] == "parlamentar"].copy()
    if parl.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar", "raw"])
    return (
        parl.rename(columns={"id_no": "id_parlamentar", "pagerank": "raw"})
        .loc[:, ["periodo", "id_parlamentar", "raw"]]
        .reset_index(drop=True)
    )


def _uniao_ids_por_periodo(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """União dos ids de parlamentar por período das fontes de raw.

    O grão do `risk_scores` é `(periodo, id_parlamentar)` — a união garante
    que todo parlamentar que aparece em QUALQUER uma das fontes entra na
    composição; os raws ausentes das demais viram 0 (sem sinal).
    """
    partes: list[pd.DataFrame] = []
    for df in dfs:
        if df is not None and not df.empty:
            partes.append(df.loc[:, ["periodo", "id_parlamentar"]])
    if not partes:
        return pd.DataFrame(columns=["periodo", "id_parlamentar"])
    return (
        pd.concat(partes, ignore_index=True)
        .drop_duplicates()
        .sort_values(["periodo", "id_parlamentar"])
        .reset_index(drop=True)
    )


def _completar_auditoria(
    df: pd.DataFrame,
    run_id: str,
    pipeline_version: str,
    execution_timestamp: str,
    source_version: str,
) -> pd.DataFrame:
    """Reordena para [colunas de negócio] + [auditoria] (padrão Silver/Gold)."""
    colunas_negocio = [c for c in df.columns if c not in COLUNAS_AUDITORIA]
    return df.assign(
        run_id=run_id,
        pipeline_version=pipeline_version,
        execution_timestamp=execution_timestamp,
        source_version=source_version,
    )[colunas_negocio + COLUNAS_AUDITORIA]


def compor_risk_scores(
    concentracao: pd.DataFrame | None,
    fatos: pd.DataFrame,
    outliers: pd.DataFrame | None,
    nos: pd.DataFrame | None,
) -> pd.DataFrame:
    """Junta os raws, normaliza Min-Max por período e pondera o `risk_index`.

    Retorna o DataFrame de negócio (sem auditoria) no grão
    `(periodo, id_parlamentar)` com as 5 colunas de score normalizadas em
    [0, 1] e `risk_index` — pronto para persistência do staging.

    Args:
        concentracao: Gold `supplier_concentration` (ano, id_parlamentar,
            hhi, ...).
        fatos: `fact_despesa` promovido (ids reais do DuckDB).
        outliers: `ml_staging.expense_outliers` (is_anomalia por despesa).
        nos: `ml_staging.network_nodes` (pagerank por nó).

    Returns:
        DataFrame com as colunas de negócio do `risk_scores`. Vazio se não
        houver parlamentar em nenhuma fonte.
    """
    raws = {
        "supplier_concentration_score": _df_concentracao(concentracao),
        "political_exposure_score": _df_exposure(fatos),
        "supplier_dependency_score": _df_dependency(fatos),
        "expense_anomaly_score": _df_anomalia(outliers),
        "network_influence_score": _df_influencia(nos),
    }

    base = _uniao_ids_por_periodo(list(raws.values()))
    if base.empty:
        return pd.DataFrame(columns=["periodo", "id_parlamentar"] + SCORES + ["risk_index"])

    for nome in SCORES:
        raw = raws[nome]
        if raw.empty:
            base[nome] = 0.0
            continue
        base = base.merge(raw, on=["periodo", "id_parlamentar"], how="left")
        base[nome] = _normalizar_por_periodo(base, base["raw"]).fillna(0.0)
        base = base.drop(columns=["raw"])

    pesos = get_analytics().risk.pesos
    base["risk_index"] = sum(
        pesos[nome] * base[nome].astype(float) for nome in SCORES
    )
    return base.reset_index(drop=True)


def _normalizar_por_periodo(base: pd.DataFrame, raw: pd.Series) -> pd.Series:
    """Min-Max de um raw POR período (universo X do período, ADR-027).

    `normalizar_minmax` (feature `minmax`, ADR-028) é aplicada agrupada
    pelo período — a normalização refeita por execução (§9).
    """
    resultado = pd.Series(np.nan, index=raw.index, dtype=float)
    if base.empty or base["periodo"].isna().all():
        return resultado
    for periodo in base["periodo"].drop_duplicates():
        mascara = base["periodo"] == periodo
        vals = normalizar_minmax(raw[mascara])
        resultado.loc[mascara] = vals.to_numpy()
    return resultado


def escrever_risk_scores_duckdb(
    scores: pd.DataFrame,
    run_id: str,
    *,
    db_path: str | None = None,
    pipeline_version: str | None = None,
    source_version: str = "",
) -> None:
    """Persiste `ml_staging.risk_scores` (ADR-026/ADR-029).

    Substitui integralmente a tabela do staging por execução (single-writer
    DuckDB, recálculo total chaveado por `(run_id, periodo)`). Tabela vazia
    é criada mesmo sem dados, para manter o contrato dbt estável.

    Args:
        scores: DataFrame de negócio de `compor_risk_scores`.
        run_id: Identificador da execução.
        db_path: Caminho DuckDB alternativo (testes).
        pipeline_version: Versão do pipeline; padrão de `pyproject.toml`.
        source_version: Versão da fonte do lote.
    """
    import duckdb

    from pipeline.config import get_env, get_pipeline_version

    pipeline_version = pipeline_version or get_pipeline_version()
    agora = datetime.now(timezone.utc).isoformat()
    colunas_negocio = [c for c in scores.columns if c not in COLUNAS_AUDITORIA]
    carga = scores.assign(
        run_id=run_id,
        pipeline_version=pipeline_version,
        execution_timestamp=agora,
        source_version=source_version,
    )[colunas_negocio + COLUNAS_AUDITORIA]

    con = duckdb.connect(db_path or get_env().duckdb_database_path)
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS ml_staging")
        con.execute("DROP TABLE IF EXISTS ml_staging.risk_scores")
        if carga.empty:
            con.execute(_DDL_VAZIO_RISK)
        else:
            con.register("tmp_risk", carga)
            con.execute(
                "CREATE TABLE ml_staging.risk_scores AS SELECT * FROM tmp_risk"
            )
        logger.info(
            "ml_staging_risk_scores_gravado",
            run_id=run_id,
            linhas=len(carga),
            db_path=db_path or "padrao",
        )
    finally:
        con.close()


def executar_carga_ml_risco(
    concentracao: pd.DataFrame | None,
    fatos: pd.DataFrame,
    outliers: pd.DataFrame | None,
    nos: pd.DataFrame | None,
    run_id: str,
    *,
    db_path: str | None = None,
    source_version: str = "",
) -> int:
    """Fluxo completo da Onda 4: compor scores + gravar `ml_staging`.

    Orquestra `compor_risk_scores` + `escrever_risk_scores_duckdb` — o
    ponto de entrada da DAG apontando para o DuckDB do Gold (mesmo padrão
    de `executar_carga_outliers`/`executar_carga_ml_rede`).

    Args:
        concentracao: Gold `supplier_concentration` (hhi por parlamentar/ano).
        fatos: `fact_despesa` promovido (ids reais do DuckDB).
        outliers: `ml_staging.expense_outliers` (raw de anomalia).
        nos: `ml_staging.network_nodes` (raw de PageRank).
        run_id: Identificador da execução.
        db_path: Caminho DuckDB alternativo.
        source_version: Versão da fonte do lote.

    Returns:
        Número de linhas gravadas em `ml_staging.risk_scores`.
    """
    scores = compor_risk_scores(concentracao, fatos, outliers, nos)
    escrever_risk_scores_duckdb(
        scores,
        run_id,
        db_path=db_path,
        source_version=source_version,
    )
    return len(scores)


def risk_scores_no_registry(registry_path: str | None = None) -> bool:
    """Confere se as features da Onda 4 estão registradas (ADR-028).

    Os 5 scores do ADR-027, a função `minmax` e o `risk_index` são features
    da Feature Store — sem registro, o contrato ADR-028 estaria quebrado.
    Não bloqueia a execução (mesma convenção das Ondas 2/3).

    Args:
        registry_path: Caminho alternativo do registry (para testes).

    Returns:
        `True` se todas as features da Onda 4 estiverem registradas.
    """
    from pathlib import Path

    registry = carregar_registry(Path(registry_path) if registry_path else None)
    exigidas = SCORES + ["minmax", "risk_index"]
    presentes = {f.nome for f in registry.features}
    faltantes = [nome for nome in exigidas if nome not in presentes]
    ok = not faltantes
    logger.info(
        "risk_scores_features_registradas",
        registradas=ok,
        faltantes=faltantes,
        pesos=get_analytics().risk.pesos,
    )
    return ok