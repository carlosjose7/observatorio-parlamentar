"""analytics/anomalies/anomalies.py — detecção de anomalias estatísticas (Sprint 5, Onda 2).

Implementa a definição formal de anomalia do §10 / ADR-002
(PROJECT_CONTEXT.md): uma despesa é **anomalia estatística** quando satisfaz
**pelo menos dois** dos seis critérios:

| # | Critério | Threshold |
|---|----------|-----------|
| 1 | Z-score do valor vs histórico do parlamentar | `> 2.5` |
| 2 | Isolation Forest score | `< -0.1` (contamination `0.05`) |
| 3 | Fornecedor com < 3 clientes parlamentares distintos | — |
| 4 | Empresa aberta há < 12 meses na data da despesa | — |
| 5 | Valores idênticos em ≥ 3 ocorrências no mês | — |
| 6 | Despesa em dia sem sessão (feriado/fim de semana) | — |

Este predicado é a feature **`regra_anomalia`** da Feature Store
(`feature_store/registry.yaml`, ADR-028, categoria `funcao`), consumida por
`expense_anomaly_score` e `expense_outliers` — o módulo reusa a referência
registrada (não recria a lógica solta).

Nota ADR-002 (mantida fielmente): `contamination=0.05` é hiperparâmetro de
**treino** do Isolation Forest; threshold de score `< -0.1` é regra de
**decisão em inferência**. São distintos e não redundantes — reajuste de
qualquer um exige novo ADR.

Saída: por exigência do ADR-026 (Opção A), Python escreve **exclusivamente**
no schema `ml_staging` (DuckDB, single-writer) — aqui via
`ml_staging.expense_outliers`; o dbt consome como `source()` e materializa a
tabela Gold `expense_outliers` (model regular com `schema.yml`, ADR-021).
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import structlog

from analytics.features import carregar_registry

logger = structlog.get_logger()

#: Limiar do critério 1 (Z-score > 2.5) — §10/ADR-002.
ZSCORE_LIMIAR = 2.5

#: Contamination do Isolation Forest — hiperparâmetro de TREINO (ADR-002).
IF_CONTAMINACAO = 0.05

#: Limiar de decisão do critério 2 EM INFERÊNCIA — ADR-002.
IF_LIMIAR_SCORE = -0.1

#: Critério 3 — fornecedor com menos de N clientes parlamentares distintos.
FORNECEDOR_MIN_CLIENTES = 3

#: Critério 4 — empresa aberta há menos de N meses na data da despesa.
EMPRESA_NOVA_MESES = 12

#: Critério 5 — valores idênticos em ≥ N ocorrências no mês.
VALORES_IDENTICOS_MIN = 3

#: Colunas booleanas dos seis critérios, na ordem do §10/ADR-002.
CRITERIOS = [
    "criterio_zscore",
    "criterio_if",
    "criterio_fornecedor_poucos_clientes",
    "criterio_empresa_nova",
    "criterio_valores_identicos",
    "criterio_dia_sem_sessao",
]

#: Grão das colunas de auditoria persistidas (padrão Silver/Gold).
COLUNAS_AUDITORIA = [
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]


# ── Funções dos seis critérios (puras, determinísticas) ─────────


def _zscore_por_parlamentar(
    fatos: pd.DataFrame,
    *,
    coluna_valor: str,
    coluna_id: str,
) -> pd.Series:
    """Z-score do valor vs. histórico do parlamentar (critério 1).

    Para cada parlamentar, z = (valor − média) / desvio padrão populacional
    das suas despesas. Parlamentar com histórico insuficiente
    (desvio nulo) retorna `nan` — o critério não acusa por falta de base.

    Args:
        fatos: DataFrame no grão de fato (uma linha por despesa).
        coluna_valor: Coluna de valor monetário.
        coluna_id: Coluna de id do parlamentar.

    Returns:
        `pd.Series` com o z-score por despesa (índice = linha do `fatos`).
    """
    valores = pd.to_numeric(fatos[coluna_valor], errors="coerce")
    grupo = fatos.assign(_valor=valores).groupby(coluna_id)

    media = grupo["_valor"].transform("mean")
    desvio = grupo["_valor"].transform("std", ddof=0)
    # Parliamentar com uma única despesa → desvio 0 → z-score indefinido.
    return (valores - media) / desvio.replace(0, np.nan)


def _scores_isolation_forest(
    fatos: pd.DataFrame,
    *,
    coluna_valor: str,
    random_state: int = 42,
) -> pd.Series:
    """Scores de anomalia do Isolation Forest (critério 2, ADR-002).

    Treina um Isolation Forest com `contamination=0.05` (hiperparâmetro de
    treino) sobre o valor das despesas do período e devolve, por despesa, o
    `decision_function` — quanto menor o score, mais anômala a despesa. A
    regra de decisão `< -0.1` é aplicada EM INFERÊNCIA por
    `_criterio_isolation_forest` (ADR-002: treino e inferência são momentos
    distintos).

    Args:
        fatos: DataFrame no grão de fato (uma linha por despesa).
        coluna_valor: Coluna de valor monetário usada como feature.
        random_state: Semente fixa — treino determinístico por período.

    Returns:
        `pd.Series` com os scores (índice = linha do `fatos`).
    """
    from sklearn.ensemble import IsolationForest

    valores = pd.to_numeric(fatos[coluna_valor], errors="coerce").fillna(0.0)
    modelo = IsolationForest(
        contamination=IF_CONTAMINACAO,
        random_state=random_state,
    )
    modelo.fit(valores.to_numpy().reshape(-1, 1))
    scores = modelo.decision_function(valores.to_numpy().reshape(-1, 1))
    return pd.Series(scores, index=fatos.index)


def criterio_zscore(
    fatos: pd.DataFrame,
    *,
    coluna_valor: str = "valor_liquido",
    coluna_id: str = "id_parlamentar",
) -> pd.Series:
    """Critério 1 — z-score do valor vs. histórico do parlamentar > 2.5."""
    z = _zscore_por_parlamentar(
        fatos, coluna_valor=coluna_valor, coluna_id=coluna_id
    )
    return z.fillna(-np.inf) > ZSCORE_LIMIAR


def criterio_isolation_forest(
    fatos: pd.DataFrame,
    *,
    coluna_valor: str = "valor_liquido",
    random_state: int = 42,
) -> tuple[pd.Series, pd.Series]:
    """Critério 2 — Isolation Forest score < -0.1.

    Devolve `(scores, criterio_bool)`: o score é persistido para auditoria;
    o critério aplica o limiar de inferência.

    Args:
        fatos: DataFrame no grão de fato.
        coluna_valor: Coluna de valor usada como feature.
        random_state: Semente do treino determinístico.

    Returns:
        (`pd.Series` de scores, `pd.Series` booleana do critério).
    """
    scores = _scores_isolation_forest(
        fatos, coluna_valor=coluna_valor, random_state=random_state
    )
    return scores, scores < IF_LIMIAR_SCORE


def criterio_fornecedor_poucos_clientes(
    fatos: pd.DataFrame,
    *,
    coluna_fornecedor: str = "id_fornecedor",
    coluna_id: str = "id_parlamentar",
) -> pd.Series:
    """Critério 3 — fornecedor com < 3 clientes parlamentares distintos.

    Fornecedores com poucos clientes são mais suscetíveis a relação
    parlamentar-fornecedor concentrada. Despesas sem fornecedor (`nan`) não
    acusam o critério.
    """
    if fatos.empty or coluna_fornecedor not in fatos.columns:
        return pd.Series(False, index=fatos.index)
    clientes = (
        fatos.dropna(subset=[coluna_fornecedor])
        .groupby(coluna_fornecedor)[coluna_id]
        .nunique()
    )
    mapa_poucos_clientes = clientes < FORNECEDOR_MIN_CLIENTES
    return fatos[coluna_fornecedor].map(mapa_poucos_clientes).fillna(False).astype(bool)


def criterio_empresa_nova(
    fatos: pd.DataFrame,
    data_abertura_fornecedor: pd.Series | None,
    *,
    data_documento: pd.Series | None = None,
    coluna_fornecedor: str = "id_fornecedor",
) -> pd.Series:
    """Critério 4 — empresa aberta há < 12 meses na data da despesa.

    Exige a data de abertura do fornecedor (`data_abertura_fornecedor`,
    `pd.Series` indexada por `id_fornecedor`). Quando a base de fornecedores
    ainda não fornece abertura (`None`), o critério **não acusa** nenhuma
    despesa — degradação segura, sem falso-positivo por falta de dado.

    Args:
        fatos: DataFrame no grão de fato.
        data_abertura_fornecedor: Série `{id_fornecedor: data_de_abertura}`.
        data_documento: Série de datas do documento por despesa (índice =
            linha do `fatos`). Se omitida, usa `pd.Timestamp.today()` como
            referência.
        coluna_fornecedor: Coluna de id do fornecedor.

    Returns:
        `pd.Series` booleana do critério.
    """
    if fatos.empty or data_abertura_fornecedor is None:
        return pd.Series(False, index=fatos.index)
    if data_abertura_fornecedor.empty:
        logger.warning(
            "anomalia_empresa_nova_sem_dados",
            motivo="data de abertura de fornecedores não informada — critério 4 não acusa",
        )
        return pd.Series(False, index=fatos.index)

    abertura = fatos[coluna_fornecedor].map(
        pd.to_datetime(data_abertura_fornecedor, errors="coerce")
    )
    referencia = pd.to_datetime(data_documento) if data_documento is not None else pd.Timestamp.today()
    meses = ((referencia - abertura).dt.days / 30.44).where(abertura.notna())
    return (meses < EMPRESA_NOVA_MESES).fillna(False).astype(bool)


def criterio_valores_identicos(
    fatos: pd.DataFrame,
    dim_data: pd.DataFrame,
    *,
    coluna_valor: str = "valor_liquido",
    coluna_id: str = "id_parlamentar",
    coluna_data: str = "data_sk",
) -> pd.Series:
    """Critério 5 — valores idênticos em ≥ 3 ocorrências no mês.

    Agrupa por (parlamentar, mês, valor) e acusa quando a mesma despesa
    repete valor ≥ 3 vezes no mesmo mês — padrão típico de fracionamento.

    Args:
        fatos: DataFrame no grão de fato (com `coluna_data`).
        dim_data: DataFrame da `dim_data` (com `data_sk`, `ano`, `mes`).
        coluna_valor / coluna_id / coluna_data: Colunas de valor, id e data.

    Returns:
        `pd.Series` booleana do critério.
    """
    if fatos.empty or dim_data.empty:
        return pd.Series(False, index=fatos.index)
    trabalho = fatos.join(
        dim_data.set_index("data_sk")[["ano", "mes"]],
        on=coluna_data,
        how="left",
    )
    valores = pd.to_numeric(trabalho[coluna_valor], errors="coerce")
    contagem = trabalho.groupby([coluna_id, "ano", "mes", valores], dropna=False)[
        coluna_valor
    ].transform("size")
    return (contagem >= VALORES_IDENTICOS_MIN).fillna(False).astype(bool)


def criterio_dia_sem_sessao(
    fatos: pd.DataFrame,
    dim_data: pd.DataFrame,
    *,
    coluna_data: str = "data_sk",
) -> pd.Series:
    """Critério 6 — despesa em dia sem sessão (feriado/fim de semana).

    Usa `dim_data.is_dia_util` (seg-sex, sim/não). Feriados nacionais e o
    calendário de sessões parlamentares ainda não são modelados — ver
    `dim_data.sql` (Onda 1); quando existirem, este critério recebe a
    extensão (mesma regra, fonte mais completa).

    Args:
        fatos: DataFrame no grão de fato (com `coluna_data`).
        dim_data: DataFrame da `dim_data` (com `data_sk`, `is_dia_util`).
        coluna_data: Coluna de id da data.

    Returns:
        `pd.Series` booleana do critério.
    """
    dias_nao_uteis = dim_data[~dim_data["is_dia_util"]]["data_sk"]
    conjunto = set(dias_nao_uteis)
    return fatos[coluna_data].isin(conjunto)


# ── Predicado agregado (feature `regra_anomalia`, ADR-028) ───────


def avaliar_criterios(
    fatos: pd.DataFrame,
    dim_data: pd.DataFrame | None = None,
    *,
    data_abertura_fornecedor: pd.Series | None = None,
    coluna_valor: str = "valor_liquido",
    coluna_id: str = "id_parlamentar",
    coluna_fornecedor: str = "id_fornecedor",
    coluna_data: str = "data_sk",
    random_state: int = 42,
) -> pd.DataFrame:
    """Avalia os seis critérios do §10 sobre as despesas.

    Implementa a feature `regra_anomalia` (ADR-028, categoria `funcao`):
    `is_anomalia(d) = (count(criterio_k(d)) >= 2)`. Devolve um DataFrame no
    mesmo grão de `fatos`, com uma coluna booleana por critério
    (`criterio_*`), `zscore`, `if_score`, `num_criterios` e `is_anomalia` —
    que é o que vira `ml_staging.expense_outliers` (ADR-026).

    Args:
        fatos: DataFrame no grão de fato — uma linha por despesa, com
            `coluna_valor`, `coluna_id`, `coluna_fornecedor` (opcional) e
            `coluna_data`.
        dim_data: DataFrame da `dim_data` (com `data_sk`, `ano`, `mes`,
            `is_dia_util` e `data`). Necessária para os critérios 4, 5 e 6;
            se omitida, esses critérios não acusam.
        data_abertura_fornecedor: Série `{id_fornecedor: data_de_abertura}`
            para o critério 4; `None` desativa o critério (degradação segura).
        coluna_valor / coluna_id / coluna_fornecedor / coluna_data: Nomes de
            colunas operacionais do `fatos`.
        random_state: Semente do Isolation Forest (treino determinístico).

    Returns:
        DataFrame no grão de `fatos` com colunas `criterio_*`, `zscore`,
        `if_score`, `num_criterios` e `is_anomalia`.
    """
    if fatos.empty:
        return fatos.assign(
            zscore=pd.Series(dtype=float),
            if_score=pd.Series(dtype=float),
            criterio_zscore=pd.Series(dtype=bool),
            criterio_if=pd.Series(dtype=bool),
            criterio_fornecedor_poucos_clientes=pd.Series(dtype=bool),
            criterio_empresa_nova=pd.Series(dtype=bool),
            criterio_valores_identicos=pd.Series(dtype=bool),
            criterio_dia_sem_sessao=pd.Series(dtype=bool),
            num_criterios=pd.Series(dtype=int),
            is_anomalia=pd.Series(dtype=bool),
        )

    resultado = fatos.copy()
    resultado["zscore"] = _zscore_por_parlamentar(
        fatos, coluna_valor=coluna_valor, coluna_id=coluna_id
    )
    resultado["if_score"], resultado["criterio_if"] = criterio_isolation_forest(
        fatos, coluna_valor=coluna_valor, random_state=random_state
    )
    resultado["criterio_zscore"] = (
        resultado["zscore"].fillna(-np.inf) > ZSCORE_LIMIAR
    )
    if coluna_fornecedor in fatos.columns:
        resultado["criterio_fornecedor_poucos_clientes"] = (
            criterio_fornecedor_poucos_clientes(
                fatos, coluna_fornecedor=coluna_fornecedor, coluna_id=coluna_id
            )
        )
    else:
        resultado["criterio_fornecedor_poucos_clientes"] = False

    if dim_data is not None and not dim_data.empty:
        data_documento = fatos[coluna_data].map(
            dim_data.set_index("data_sk")["data"]
        )
    else:
        data_documento = None
    resultado["criterio_empresa_nova"] = criterio_empresa_nova(
        fatos,
        data_abertura_fornecedor,
        data_documento=data_documento,
        coluna_fornecedor=coluna_fornecedor,
    )
    if dim_data is not None and not dim_data.empty:
        resultado["criterio_valores_identicos"] = criterio_valores_identicos(
            fatos,
            dim_data,
            coluna_valor=coluna_valor,
            coluna_id=coluna_id,
            coluna_data=coluna_data,
        )
        resultado["criterio_dia_sem_sessao"] = criterio_dia_sem_sessao(
            fatos, dim_data, coluna_data=coluna_data
        )
    else:
        resultado["criterio_valores_identicos"] = False
        resultado["criterio_dia_sem_sessao"] = False

    resultado["num_criterios"] = resultado[CRITERIOS].sum(axis=1)
    resultado["is_anomalia"] = resultado["num_criterios"] >= 2
    return resultado


def contagem_anomalias(resultado: pd.DataFrame) -> int:
    """Número de despesas anômalas de um lote avaliado.

    Conveniência para `expense_anomaly_score` (ADR-027):
    `a_p = |despesas anômalas de p| / |despesas de p|`.
    """
    if resultado.empty:
        return 0
    return int(resultado["is_anomalia"].sum())


# ── Rastreabilidade via Feature Store (ADR-028) ──────────────────


def regra_anomalia_no_registry(registry_path: str | None = None) -> bool:
    """Confere se a feature `regra_anomalia` está registrada (ADR-028).

    O predicado implementado por este módulo é a feature `regra_anomalia` da
    Feature Store — sem registro, o contrato ADR-028 estaria quebrado. Usada
    em testes e em log estruturado (não bloqueia a execução).

    Args:
        registry_path: Caminho alternativo do registry (para testes).

    Returns:
        `True` se a feature estiver registrada como categoria `funcao`.
    """
    from pathlib import Path

    registry = carregar_registry(Path(registry_path) if registry_path else None)
    feature = registry.obter("regra_anomalia")
    ok = feature is not None and feature.categoria.value == "funcao"
    logger.info(
        "regra_anomalia_registrada",
        registrada=ok,
        consumidores=feature.consumidores if feature else [],
    )
    return ok


# ── Persistência DuckDB em `ml_staging` (ADR-026, Opção A) ───────


def _conectar_duckdb(db_path: str | None = None):
    """Abre uma conexão DuckDB no caminho de `DUCKDB_DATABASE_PATH`.

    Args:
        db_path: Caminho alternativo (testes). Padrão: env do pipeline.
    """
    import duckdb

    from pipeline.config import get_env

    return duckdb.connect(db_path or get_env().duckdb_database_path)


def escrever_expense_outliers_duckdb(
    resultado: pd.DataFrame,
    run_id: str,
    *,
    db_path: str | None = None,
    pipeline_version: str | None = None,
    source_version: str = "",
) -> None:
    """Persiste `ml_staging.expense_outliers` (ADR-026/ADR-021).

    Métricas da regra de anomalia para cada despesa, já com
    `is_anomalia` calculada. O schema `ml_staging` é criado se ausente; a
    carga é idempotente por `run_id` (recalcula e substitui o mesmo lote).

    Args:
        resultado: DataFrame de `avaliar_criterios(...)` (grão despesa).
        run_id: Identificador da execução.
        db_path: Caminho DuckDB alternativo (testes).
        pipeline_version: Versão do pipeline; padrão lido de `pyproject.toml`.
        source_version: Versão da fonte do lote.
    """
    if resultado.empty:
        return

    from pipeline.config import get_pipeline_version

    pipeline_version = pipeline_version or get_pipeline_version()
    agora = datetime.now(UTC).isoformat()
    colunas_resultado = [c for c in resultado.columns if c not in COLUNAS_AUDITORIA]
    carga = resultado.assign(
        run_id=run_id,
        pipeline_version=pipeline_version,
        execution_timestamp=agora,
        source_version=source_version,
    )[colunas_resultado + COLUNAS_AUDITORIA]

    con = _conectar_duckdb(db_path)
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS ml_staging")
        con.execute("DROP TABLE IF EXISTS ml_staging.expense_outliers")
        con.register("tmp_outliers", carga)
        con.execute(
            "CREATE TABLE ml_staging.expense_outliers AS SELECT * FROM tmp_outliers"
        )
        logger.info(
            "ml_staging_expense_outliers_gravado",
            run_id=run_id,
            linhas=len(carga),
            db_path=db_path or "padrao",
        )
    finally:
        con.close()


def executar_carga_outliers(
    fatos: pd.DataFrame,
    run_id: str,
    *,
    dim_data: pd.DataFrame | None = None,
    data_abertura_fornecedor: pd.Series | None = None,
    db_path: str | None = None,
    source_version: str = "",
) -> pd.DataFrame:
    """Fluxo completo da Onda 2: avaliar critérios e gravar `ml_staging`.

    Orquestra `avaliar_criterios` + `escrever_expense_outliers_duckdb` —
    o ponto de entrada da DAG apontando para o DuckDB do Gold (mesmo padrão
    de `pipeline/silver.py`).

    Args:
        fatos: DataFrame de despesas no grão de fato.
        run_id: Identificador da execução.
        dim_data: `dim_data` para critérios 5/6.
        data_abertura_fornecedor: Data de abertura dos fornecedores (critério 4).
        db_path: Caminho DuckDB alternativo.
        source_version: Versão da fonte.

    Returns:
        DataFrame avaliado (mesmo de `avaliar_criterios`).
    """
    resultado = avaliar_criterios(
        fatos,
        dim_data,
        data_abertura_fornecedor=data_abertura_fornecedor,
    )
    escrever_expense_outliers_duckdb(
        resultado,
        run_id,
        db_path=db_path,
        source_version=source_version,
    )
    return resultado
