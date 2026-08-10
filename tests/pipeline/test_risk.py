# tests/pipeline/test_risk.py
"""Scores de risco individual e `risk_index` (Sprint 5, Onda 4).

Cobre `pipeline/risk.py` — ADR-027 (os 5 scores individuais com fórmulas
fechadas: concentração HHI, exposição política, dependência de fornecedor,
anomalia de despesa, influência em rede), ADR-029 (composição ponderada
`risk_index` com `risk.pesos` da config), ADR-003/ADR-028 (normalização
Min-Max [0,1] via `minmax` reutilizável, por período) e a persistência em
`ml_staging.risk_scores` (ADR-026, Opção A — Python single-writer no staging).

Verifica:
- Extração dos raws das fontes existentes (Gold `supplier_concentration`,
  `fact_despesa`, `ml_staging.expense_outliers`, `ml_staging.network_nodes`).
- Normalização Min-Max POR PERÍODO (universo do período, §9) em [0, 1];
  série constante → 0.0; raw ausente do parlamentar → 0.0 (sem sinal).
- `risk_index` = Σ_i w_i · score_i com os pesos de `config/analytics.yaml`
  (0.2 uniforme por padrão) e com pesos alternativos injetados.
- Persistência `ml_staging.risk_scores` (recálculo total, run_id/
  pipeline_version/source_version) e `executar_carga_ml_risco`.
- Rastreabilidade das features da Onda 4 no registry (ADR-028).
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

import pipeline.risk as risco

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


# ── Derivar período do data_sk ─────────────────────────────────


def test_periodo_do_data_sk():
    """`data_sk` YYYYMMDD → ano do período (grão das analíticas, ADR-021)."""
    assert risco._periodo_do_data_sk(20190101) == 2019
    assert risco._periodo_do_data_sk(20200415) == 2020
    assert risco._periodo_do_data_sk(20201231) == 2020


# ── Raw: concentração (ADR-027.1) ──────────────────────────────


def test_df_concentracao_mapeia_periodo_hhi():
    """`supplier_concentration_score` raw = hhi da Gold (ano → periodo, ADR-021)."""
    conc = pd.DataFrame(
        {"ano": [2019, 2020], "id_parlamentar": [1, 1], "hhi": [0.8, 1.0]}
    )
    df = risco._df_concentracao(conc)
    assert list(df.columns) == ["periodo", "id_parlamentar", "raw"]
    assert df.to_dict("records") == [
        {"periodo": 2019, "id_parlamentar": 1, "raw": 0.8},
        {"periodo": 2020, "id_parlamentar": 1, "raw": 1.0},
    ]
    vazio = risco._df_concentracao(None)
    assert vazio.empty and list(vazio.columns) == ["periodo", "id_parlamentar", "raw"]


# ── Raw: exposição política (ADR-027.2) ────────────────────────


def test_df_exposure_fornecedor_compartilhado():
    """Exposição = média_{f∈F_p} (n_f - 1): fornecedor só de p contribui 0."""
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 2],
            "id_fornecedor": [10, 20, 10],
            "valor_liquido": [1.0, 1.0, 1.0],
            "data_sk": [20190101, 20190102, 20190105],
        }
    )
    df = risco._df_exposure(fatos)
    linhas = {int(p): r for p, r in zip(df["id_parlamentar"], df["raw"])}
    # f10 usado por p1 e p2 (n=2 → contrib 1); f20 só por p1 (n=1 → 0).
    assert linhas[1] == pytest.approx(0.5)  # (1 + 0) / 2
    assert linhas[2] == pytest.approx(1.0)  # 1 / 1


def test_df_exposure_sem_fornecedor_vazio():
    """Sem fatos resolvíveis → raw vazio com o schema fixo."""
    vazio = risco._df_exposure(pd.DataFrame({"id_parlamentar": [1]}))
    assert vazio.empty and list(vazio.columns) == ["periodo", "id_parlamentar", "raw"]


# ── Raw: dependência de fornecedor (ADR-027.3) ─────────────────


def test_df_dependency_hhi_fornecedor():
    """Dependência = média_{f∈F_p} dep_f; dep_f = Σ_p share^2 do fornecedor."""
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 2],
            "id_fornecedor": [10, 20, 10],
            "valor_liquido": [5.0, 7.0, 5.0],
            "data_sk": [20190101, 20190102, 20190105],
        }
    )
    df = risco._df_dependency(fatos)
    linhas = {int(p): r for p, r in zip(df["id_parlamentar"], df["raw"])}
    # f10 dividido 5/5 entre p1/p2 → dep_f = 0.25+0.25 = 0.5; f20 só de p1 → 1.0.
    assert linhas[1] == pytest.approx(0.75)  # (0.5 + 1.0) / 2
    assert linhas[2] == pytest.approx(0.5)  # 0.5 / 1


def test_df_dependency_fornecedor_um_cliente_é_um():
    """Fornecedor com um único cliente → dep_f = 1.0 (dependência máxima)."""
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 1],
            "id_fornecedor": [10, 20],
            "valor_liquido": [3.0, 7.0],
            "data_sk": [20190101, 20190102],
        }
    )
    df = risco._df_dependency(fatos)
    assert df["raw"].iloc[0] == pytest.approx(1.0)


# ── Raw: anomalia de despesa (ADR-027.4) ───────────────────────


def test_df_anomalia_fracao_por_parlamentar():
    """a_p = anomalias de p / despesas de p (is_anomalia da Onda 2)."""
    outliers = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 2, 2],
            "data_sk": pd.Series([20190101, 20190102, 20190105, 20190106], dtype="int64"),
            "is_anomalia": [True, False, True, True],
        }
    )
    df = risco._df_anomalia(outliers)
    linhas = {int(p): r for p, r in zip(df["id_parlamentar"], df["raw"])}
    assert linhas[1] == pytest.approx(0.5)  # 1 de 2
    assert linhas[2] == pytest.approx(1.0)  # 2 de 2


def test_df_anomalia_vazio_colunas_fixas():
    vazio = risco._df_anomalia(None)
    assert vazio.empty and list(vazio.columns) == ["periodo", "id_parlamentar", "raw"]


# ── Raw: influência em rede (ADR-027.5) ────────────────────────


def test_df_influencia_somente_nos_parlamentares():
    """Raw = pagerank só dos nós do tipo parlamentar (ADR-030)."""
    nos = pd.DataFrame(
        {
            "id_no": [1, 2, 10, 20],
            "tipo_no": ["parlamentar", "parlamentar", "fornecedor", "fornecedor"],
            "periodo": [2019, 2019, 2019, 2019],
            "pagerank": [0.6, 0.3, 0.07, 0.03],
        }
    )
    df = risco._df_influencia(nos)
    assert len(df) == 2  # só parlamentares
    linhas = {(int(p), int(per)): r for p, per, r in zip(
        df["id_parlamentar"], df["periodo"], df["raw"]
    )}
    assert linhas[(1, 2019)] == pytest.approx(0.6)
    assert linhas[(2, 2019)] == pytest.approx(0.3)


# ── União de ids por período ───────────────────────────────────


def test_uniao_ids_por_periodo():
    """Grão (periodo, id_parlamentar): união das fontes sem duplicar."""
    a = pd.DataFrame({"periodo": [2019, 2019, 2020], "id_parlamentar": [1, 2, 1]})
    b = pd.DataFrame({"periodo": [2019, 2021], "id_parlamentar": [2, 3]})
    u = risco._uniao_ids_por_periodo([a, b])
    assert set(map(tuple, u.itertuples(index=False))) == {
        (2019, 1), (2019, 2), (2020, 1), (2021, 3),
    }


def test_uniao_ids_por_periodo_vazio():
    assert risco._uniao_ids_por_periodo([None, pd.DataFrame()]).empty


# ── Composição completa ────────────────────────────────────────


def _fatos_2019_2020() -> pd.DataFrame:
    """Fatos de 2 períodos: 2019 com 2 parlamentares, 2020 só p1.

    2019 — p1: f10(5) + f20(7); p2: f10(5).
      exposição: f10 dividido (n=2→1) e f20 exclusivo (0): p1=0.5, p2=1.0.
      dependência: f10 dep 0.5, f20 dep 1.0: p1=0.75, p2=0.5.
    2020 — p1: f40(9) → exposição 0, dependência 1.0 (constante por período).
    """
    return pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 2, 1],
            "id_fornecedor": [10, 20, 10, 40],
            "valor_liquido": [5.0, 7.0, 5.0, 9.0],
            "data_sk": [20190101, 20190102, 20190105, 20200101],
        }
    )


def test_compor_risk_scores_fluxo_completo():
    """Normalização por período, raws ausentes → 0 e risk_index ponderado."""
    conc = pd.DataFrame(
        {"ano": [2019, 2019, 2020], "id_parlamentar": [1, 2, 1], "hhi": [0.8, 0.2, 0.5]}
    )
    fatores = _fatos_2019_2020()
    outliers = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 2, 2],
            "data_sk": pd.Series([20190101, 20190102, 20190105, 20190106], dtype="int64"),
            "is_anomalia": [True, False, True, True],
        }
    )
    nos = pd.DataFrame(
        {
            "id_no": [1, 2, 10],
            "tipo_no": ["parlamentar", "parlamentar", "fornecedor"],
            "periodo": [2019, 2019, 2019],
            "pagerank": [0.6, 0.3, 0.1],
        }
    )
    df = risco.compor_risk_scores(conc, fatores, outliers, nos)
    assert list(df.columns) == [
        "periodo", "id_parlamentar",
        "supplier_concentration_score", "political_exposure_score",
        "supplier_dependency_score", "expense_anomaly_score",
        "network_influence_score", "risk_index",
    ]
    assert df["periodo"].isin([2019, 2020]).all()
    for col in [
        "supplier_concentration_score", "political_exposure_score",
        "supplier_dependency_score", "expense_anomaly_score",
        "network_influence_score", "risk_index",
    ]:
        assert df[col].between(0.0, 1.0).all(), col

    p1_2019 = df[(df["periodo"] == 2019) & (df["id_parlamentar"] == 1)].iloc[0]
    p2_2019 = df[(df["periodo"] == 2019) & (df["id_parlamentar"] == 2)].iloc[0]
    # 2019: 5 raws distintos entre p1/p2 → min-max [0,1].
    assert p1_2019["supplier_concentration_score"] == pytest.approx(1.0)
    assert p1_2019["political_exposure_score"] == pytest.approx(0.0)
    assert p1_2019["supplier_dependency_score"] == pytest.approx(1.0)
    assert p1_2019["expense_anomaly_score"] == pytest.approx(0.0)
    assert p1_2019["network_influence_score"] == pytest.approx(1.0)
    assert p2_2019["supplier_concentration_score"] == pytest.approx(0.0)
    assert p2_2019["political_exposure_score"] == pytest.approx(1.0)
    assert p2_2019["supplier_dependency_score"] == pytest.approx(0.0)
    assert p2_2019["expense_anomaly_score"] == pytest.approx(1.0)
    assert p2_2019["network_influence_score"] == pytest.approx(0.0)
    # Uniforme 0.2: risk_index = 0.2 × Σ_i score_i.
    assert p1_2019["risk_index"] == pytest.approx(0.2 * 3.0)
    assert p2_2019["risk_index"] == pytest.approx(0.2 * 2.0)

    # 2020: p1 sozinho → séries constantes → min-max degenera para 0.0.
    p1_2020 = df[(df["periodo"] == 2020) & (df["id_parlamentar"] == 1)].iloc[0]
    assert p1_2020["supplier_concentration_score"] == pytest.approx(0.0)
    assert p1_2020["political_exposure_score"] == pytest.approx(0.0)
    assert p1_2020["supplier_dependency_score"] == pytest.approx(0.0)
    assert p1_2020["expense_anomaly_score"] == pytest.approx(0.0)
    assert p1_2020["network_influence_score"] == pytest.approx(0.0)
    assert p1_2020["risk_index"] == pytest.approx(0.0)


def test_compor_risk_scores_raw_ausente_vira_zero():
    """Parlamentar presente em só uma fonte → demais scores 0 (sem sinal)."""
    conc = pd.DataFrame({"ano": [2019], "id_parlamentar": [1], "hhi": [0.7]})
    df = risco.compor_risk_scores(conc, pd.DataFrame(), None, None)
    assert len(df) == 1
    linha = df.iloc[0]
    assert linha["supplier_concentration_score"] == pytest.approx(0.0)  # constante
    assert linha["political_exposure_score"] == pytest.approx(0.0)
    assert linha["expense_anomaly_score"] == pytest.approx(0.0)
    assert linha["network_influence_score"] == pytest.approx(0.0)


def test_compor_risk_scores_vazio_colunas_fixas():
    """Sem parlamentar em nenhuma fonte → DataFrame vazio com schema fixo."""
    df = risco.compor_risk_scores(None, pd.DataFrame(), None, None)
    assert df.empty
    assert list(df.columns) == [
        "periodo", "id_parlamentar",
        "supplier_concentration_score", "political_exposure_score",
        "supplier_dependency_score", "expense_anomaly_score",
        "network_influence_score", "risk_index",
    ]


def test_compor_risk_scores_pesos_alternativos(monkeypatch):
    """`risk_index` respeita `risk.pesos` injetados (ADR-029, config ADR-008)."""
    from pipeline.config import get_analytics

    conc = pd.DataFrame(
        {"ano": [2019, 2019], "id_parlamentar": [1, 2], "hhi": [0.8, 0.2]}
    )
    fatores = _fatos_2019_2020()
    outliers = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 2, 2],
            "data_sk": pd.Series([20190101, 20190102, 20190105, 20190106], dtype="int64"),
            "is_anomalia": [True, False, True, True],
        }
    )
    nos = pd.DataFrame(
        {
            "id_no": [1, 2, 10],
            "tipo_no": ["parlamentar", "parlamentar", "fornecedor"],
            "periodo": [2019, 2019, 2019],
            "pagerank": [0.6, 0.3, 0.1],
        }
    )
    pesos = {
        "supplier_concentration_score": 0.5,
        "political_exposure_score": 0.2,
        "supplier_dependency_score": 0.1,
        "expense_anomaly_score": 0.1,
        "network_influence_score": 0.1,
    }
    monkeypatch.setattr(get_analytics().risk, "pesos", pesos)

    df = risco.compor_risk_scores(conc, fatores, outliers, nos)
    p1 = df[(df["periodo"] == 2019) & (df["id_parlamentar"] == 1)].iloc[0]
    p2 = df[(df["periodo"] == 2019) & (df["id_parlamentar"] == 2)].iloc[0]
    # Scores [1,0,1,0,1] para p1 → 0.5+0+0.1+0+0.1 = 0.7.
    assert p1["risk_index"] == pytest.approx(0.5 + 0.1 + 0.1)
    assert p2["risk_index"] == pytest.approx(0.2 + 0.1)


# ── Persistência ml_staging (ADR-026/029) ──────────────────────


def test_escrever_risk_scores_duckdb_grava_ml_staging(tmp_path):
    """Python grava no schema `ml_staging`, com a auditoria do lote."""
    db = tmp_path / "risk.duckdb"
    scores = pd.DataFrame(
        {
            "periodo": [2019],
            "id_parlamentar": [1],
            "supplier_concentration_score": [0.8],
            "political_exposure_score": [0.0],
            "supplier_dependency_score": [0.4],
            "expense_anomaly_score": [0.0],
            "network_influence_score": [0.3],
            "risk_index": [0.3],
        }
    )
    risco.escrever_risk_scores_duckdb(
        scores, run_id="run-onda4", db_path=str(db), source_version="v1"
    )

    con = duckdb.connect(str(db))
    try:
        tabelas = {tuple(r) for r in con.execute(
            "select table_schema, table_name from information_schema.tables"
        ).fetchall()}
        assert ("ml_staging", "risk_scores") in tabelas
        assert con.execute(
            "select periodo, id_parlamentar, run_id"
            " from ml_staging.risk_scores"
        ).fetchall() == [(2019, 1, "run-onda4")]
        linhas = con.execute(
            "select pipeline_version is not null, source_version"
            " from ml_staging.risk_scores"
        ).fetchall()
        assert linhas == [(True, "v1")]
    finally:
        con.close()


def test_escrever_risk_scores_duckdb_vazio_cria_tabela(tmp_path):
    """Lote vazio: tabela de staging criada vazia (contrato dbt estável)."""
    db = tmp_path / "risk.duckdb"
    risco.escrever_risk_scores_duckdb(pd.DataFrame(), run_id="run-vazio", db_path=str(db))
    con = duckdb.connect(str(db))
    try:
        assert con.execute(
            "select count(*) from ml_staging.risk_scores"
        ).fetchone()[0] == 0
    finally:
        con.close()


def test_executar_carga_ml_risco_fluxo_completo(tmp_path):
    """Orquestração: compor + persistir; retorna nº de linhas gravadas."""
    db = tmp_path / "risk.duckdb"
    conc = pd.DataFrame({"ano": [2019], "id_parlamentar": [1], "hhi": [0.8]})
    fatos = pd.DataFrame(
        {"id_parlamentar": [1], "id_fornecedor": [10], "valor_liquido": [5.0],
         "data_sk": [20190101]}
    )
    n = risco.executar_carga_ml_risco(
        conc, fatos, None, None, run_id="run-onda4", db_path=str(db), source_version="v1"
    )
    assert n == 1

    con = duckdb.connect(str(db))
    try:
        linhas = con.execute(
            "select run_id, pipeline_version is not null"
            " from ml_staging.risk_scores"
        ).fetchall()
        assert linhas == [("run-onda4", True)]
    finally:
        con.close()


# ── Rastreabilidade na Feature Store (ADR-028) ─────────────────


def test_risk_scores_features_registradas_no_registry():
    """As 5 features de score, `minmax` e `risk_index` estão no registry (ADR-028)."""
    assert risco.risk_scores_no_registry() is True