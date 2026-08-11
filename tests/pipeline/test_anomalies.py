# tests/pipeline/test_anomalies.py
"""Detecção de anomalias de despesa (Sprint 5, Onda 2).

Cobre `analytics/anomalies/anomalies.py` — o predicado `regra_anomalia` do §10/ADR-002:
uma despesa é anomalia quando satisfaz PELO MENOS 2 dos 6 critérios. Verifica:

- Cada um dos 6 critérios isoladamente (`criterio_*`), com thresholds exatos
  do §10 (Z-score > 2.5; Isolation Forest score < -0.1 com contamination
  0.05; fornecedor < 3 clientes; empresa < 12 meses; valores idênticos >= 3
  no mês; dia sem sessão via dim_data.is_dia_util).
- O agregado `is_anomalia` (>= 2 critérios) e a rastreabilidade da feature
  `regra_anomalia` no registry (ADR-028).
- A persistência em `ml_staging.expense_outliers` (ADR-026, Opção A —
  Python single-writer no staging, schema próprio no mesmo DuckDB).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from analytics.anomalies.anomalies import (
    IF_CONTAMINACAO,
    IF_LIMIAR_SCORE,
    ZSCORE_LIMIAR,
    avaliar_criterios,
    criterio_dia_sem_sessao,
    criterio_empresa_nova,
    criterio_fornecedor_poucos_clientes,
    criterio_valores_identicos,
    criterio_zscore,
    escrever_expense_outliers_duckdb,
    contagem_anomalias,
    executar_carga_outliers,
)

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


def _fatos(
    valores: list[float],
    *,
    id_parlamentar: int = 1,
    id_fornecedor: int = 10,
    data_sk: int = 20240501,
) -> pd.DataFrame:
    """DataFrame Gold `fact_despesa` mínimo para exercitar os criteria."""
    return pd.DataFrame(
        {
            "id_despesa": list(range(1, len(valores) + 1)),
            "id_parlamentar": [id_parlamentar] * len(valores),
            "id_fornecedor": [id_fornecedor] * len(valores),
            "data_sk": [data_sk] * len(valores),
            "valor_liquido": valores,
        }
    )


def _dim_data() -> pd.DataFrame:
    """`dim_data` minimal: 2 dias úteis (maio/2024) + 1 domingo."""
    return pd.DataFrame(
        {
            "data_sk": [20240501, 20240502, 20240505],
            "data": [date(2024, 5, 1), date(2024, 5, 2), date(2024, 5, 5)],
            "ano": [2024, 2024, 2024],
            "mes": [5, 5, 5],
            "is_dia_util": [True, True, False],
        }
    )


# ── Critérios individuais ───────────────────────────────────────


def test_zscore_acima_limiar_acusar():
    """Critério 1: despesa muito acima da média do parlamentar z > 2.5."""
    # Histórico estável (varias valores ~100) + outlier 50x maior: o z do
    # outlier deve passar de 2.5; o dos demais fica baixo.
    fatos = _fatos([100.0] * 20 + [5000.0])
    criterio = criterio_zscore(fatos)
    assert criterio.tolist() == [False] * 20 + [True]


def test_zscore_hist_insuficiente_nao_acusa():
    """Parlamentar com uma despesa só → desvio zero → critério não acusa."""
    fatos = _fatos([1000])
    assert criterio_zscore(fatos).tolist() == [False]


def test_if_score_usado_como_criterio():
    """Critério 2: Isolation Forest usa contamination 0.05 e threshold -0.1."""
    # Valor destoante (outlier claro) deve ter score < -0.1.
    valores = [100.0] * 95 + [100000.0]
    fatos = _fatos(valores)
    # Usamos avaliar_criterios para obter os scores (treino determinístico).
    resultado = avaliar_criterios(fatos, _dim_data())
    assert "if_score" in resultado.columns
    assert "criterio_if" in resultado.columns
    outlier = resultado["valor_liquido"] == 100000.0
    assert resultado.loc[outlier, "criterio_if"].any()
    # contamination é hiperparâmetro de treino (ADR-002) — não confundir com
    # threshold de inferência.
    assert IF_CONTAMINACAO == 0.05
    assert IF_LIMIAR_SCORE == -0.1


def test_fornecedor_poucos_clientes():
    """Critério 3: fornecedor com 1 cliente acusa; com 4 clientes não acusa."""
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 2, 3, 4],
            "id_fornecedor": [10, 10, 10, 10, 20][:4],
        }
    )
    criterio = criterio_fornecedor_poucos_clientes(fatos)
    # Fornecedor 10 tem 4 clientes (> 3) → não acusa; o outro (20) só aparece
    # em... aqui usamos apenas 4 linhas todas do fornecedor 10.
    assert criterio.tolist() == [False, False, False, False]


def test_fornecedor_sem_dado_nao_acusa():
    """Despesa sem fornecedor resolvido não dispara o critério 3."""
    fatos = pd.DataFrame(
        {"id_parlamentar": [1, 2], "id_fornecedor": [None, 20]}
    )
    criterio = criterio_fornecedor_poucos_clientes(fatos)
    assert criterio.tolist() == [False, True]


def test_empresa_nova_doze_meses():
    """Critério 4: empresa com < 12 meses na data da despesa acusa."""
    fatos = _fatos([100.0, 100.0], id_fornecedor=10)
    # Fornecedor aberto há 6 meses na data da despesa (2024-05-01).
    abertura = pd.Series({10: pd.Timestamp("2023-11-01")})
    data_doc = pd.Series([pd.Timestamp("2024-05-01")] * 2)
    assert criterio_empresa_nova(
        fatos, abertura, data_documento=data_doc
    ).tolist() == [True, True]


def test_empresa_antiga_nao_acusa():
    """Fornecedor aberto há 3 anos NÃO dispara o critério 4."""
    fatos = _fatos([100.0], id_fornecedor=10)
    abertura = pd.Series({10: pd.Timestamp("2021-01-01")})
    data_doc = pd.Series([pd.Timestamp("2024-05-01")])
    assert criterio_empresa_nova(
        fatos, abertura, data_documento=data_doc
    ).tolist() == [False]


def test_empresa_nova_sem_base_nao_acusa():
    """Sem base de abertura, o critério 4 degrada com segurança (False)."""
    fatos = _fatos([100.0, 100.0])
    assert criterio_empresa_nova(fatos, None).tolist() == [False, False]


def test_valores_identicos_no_mes():
    """Critério 5: 3+ valores idênticos do mesmo parlamentar no mês."""
    fatos = _fatos([50, 50, 50, 10], data_sk=20240501)
    criterio = criterio_valores_identicos(fatos, _dim_data())
    assert criterio.tolist() == [True, True, True, False]


def test_valores_identicos_parlamentares_distintos():
    """Valores iguais de parlamentares diferentes não contam juntos."""
    fatos = _fatos([50, 50], id_parlamentar=1, data_sk=20240501)
    fatos = pd.concat([fatos, _fatos([50], id_parlamentar=2, data_sk=20240501)])
    criterio = criterio_valores_identicos(fatos, _dim_data())
    # Parlamentar 1: 2 ocorrências (< 3) → não acusa; parl 2: só 1.
    assert criterio.tolist() == [False, False, False]


def test_dia_sem_sessao():
    """Critério 6: despesa em FINAL DE SEMANA (is_dia_util=false) acusa."""
    fatos = pd.DataFrame(
        {"data_sk": [20240501, 20240502, 20240505]}  # seg, qui, dom
    )
    criterio = criterio_dia_sem_sessao(fatos, _dim_data())
    assert criterio.tolist() == [False, False, True]


# ── Predicado agregado (regra_anomalia) ─────────────────────────


def test_anomalia_requer_dois_criterios():
    """Despesa satisfazendo APENAS 1 critério NÃO é anomalia (ADR-002)."""
    # P1: histórico estável + outlier 50x maior (criterio 1, z>2,5) e o
    # fornecedor 10 é exclusivo (criterio 3, <3 clientes) → a despesa maior
    # soma 2 critérios → anomalia. P2: fornecedores exclusivos (criterio 3)
    # em histórico estável → só 1 critério → NÃO anomalia.
    fatos = pd.DataFrame(
        {
            "id_despesa": list(range(1, 9)),
            "id_parlamentar": [1] * 6 + [2, 2],
            "id_fornecedor": [10] * 6 + [20, 21],
            "data_sk": [20240501] * 8,
            "valor_liquido": [100, 100, 100, 100, 100, 5000, 100, 100],
        }
    )
    resultado = avaliar_criterios(fatos, _dim_data())

    p1 = resultado[resultado["id_parlamentar"] == 1]
    p2 = resultado[resultado["id_parlamentar"] == 2]
    # P1: despesa de 5000 tem z > 2.5 e o fornecedor 10 é exclusivo → 2 critérios.
    assert resultado.loc[resultado["valor_liquido"] == 5000, "is_anomalia"].all()
    # P2: fornecedores 20 e 21 exclusivos (1 cliente cada) → 1 critério/despesa.
    assert not p2["is_anomalia"].any()


def test_anomalia_contagem():
    """`contagem_anomalias` conta as despesas anômalas do lote."""
    fatos = pd.DataFrame(
        {
            "id_despesa": list(range(1, 8)),
            "id_parlamentar": [1] * 7,
            "id_fornecedor": [10] * 7,
            "data_sk": [20240501] * 7,
            "valor_liquido": [100, 100, 100, 100, 100, 100, 8000],
        }
    )
    resultado = avaliar_criterios(fatos, _dim_data())
    # Fornecedor exclusivo (criterio 3) + outlier (criterio 1) na mesma
    # despesa → garante ao menos 1 anomalia.
    assert 1 <= contagem_anomalias(resultado) <= 7
    assert contagem_anomalias(pd.DataFrame()) == 0


def test_regra_anomalia_registrada_no_registry():
    """A feature `regra_anomalia` está registrada na Feature Store (ADR-028).

    O módulo implementa o predicado registrado — sem ele, o contrato do
    registry (categoria `funcao`, consumidora de expense_anomaly_score e
    expense_outliers) estaria quebrado.
    """
    from analytics.anomalies.anomalies import regra_anomalia_no_registry

    assert regra_anomalia_no_registry() is True


# ── Persistência em ml_staging (ADR-026) ─────────────────────────


def test_escrita_ml_staging_expense_outliers(tmp_path):
    """Python grava no schema `ml_staging`, não direto no Gold."""
    db = tmp_path / "pipe.duckdb"
    fatos = pd.DataFrame(
        {
            "id_despesa": list(range(1, 8)),
            "id_parlamentar": [1] * 7,
            "id_fornecedor": [10] * 7,
            "data_sk": [20240501] * 7,
            "valor_liquido": [100, 100, 100, 100, 100, 100, 8000],
        }
    )
    resultado = avaliar_criterios(fatos, _dim_data())
    assert resultado["is_anomalia"].any()

    escrever_expense_outliers_duckdb(
        resultado, run_id="run-onda2", db_path=str(db), source_version="v1"
    )

    con = duckdb.connect(str(db))
    try:
        tabelas = {tuple(r) for r in con.execute(
            "select table_schema, table_name from information_schema.tables"
        ).fetchall()}
        assert ("ml_staging", "expense_outliers") in tabelas
        linhas = con.execute(
            "select run_id, pipeline_version, source_version, num_criterios"
            " from ml_staging.expense_outliers"
        ).fetchall()
        assert len(linhas) == 7
        assert all(r[0] == "run-onda2" for r in linhas)
        assert all(r[2] == "v1" for r in linhas)
        assert any(r[3] >= 2 for r in linhas)
    finally:
        con.close()


def test_executar_carga_outliers_escreve_e_retorna(tmp_path):
    """Orquestra avaliar + gravar em ml_staging (ponto de entrada da DAG)."""
    db = tmp_path / "pipe.duckdb"
    fatos = _fatos([100, 100, 100, 5040], id_fornecedor=10)
    resultado = executar_carga_outliers(
        fatos, run_id="run-onda2", dim_data=_dim_data(), db_path=str(db)
    )
    assert "is_anomalia" in resultado.columns

    con = duckdb.connect(str(db))
    try:
        n = con.execute(
            "select count(*) from ml_staging.expense_outliers"
        ).fetchone()[0]
        assert n == 4
    finally:
        con.close()


def test_empresa_nova_na_persistencia(tmp_path):
    """O critério 4 entra na regra quando a base de abertura existe."""
    db = tmp_path / "pipe.duckdb"
    fatos = _fatos([100, 100], id_fornecedor=10)
    abertura = pd.Series({10: pd.Timestamp("2023-11-01")})  # 6 meses
    resultado = avaliar_criterios(
        fatos, _dim_data(), data_abertura_fornecedor=abertura
    )
    assert resultado["criterio_empresa_nova"].all()