# tests/pipeline/test_analytics.py
"""Estatística descritiva e correlações da Sprint 5/Onda 1.

Cobre `analytics/parliamentarians/analytics.py`: resumo descritivo (métricas §8),
correlação de Pearson entre colunas de fatos e agregação por
parlamentar (insumo ADR-027). São funções puras (sem ML) e
determinísticas — o reservado para ML/rede é das Ondas 2/3.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analytics.parliamentarians.analytics import (
    correlacao_pearson,
    resumo_estatistico,
    resumo_por_parlamentar,
    validar_features_no_registry,
)

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


def test_resumo_estatistico_valores_basicos() -> None:
    """Média, mediana, extrema e percentil 95 calculados corretamente."""
    serie = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0])
    resumo = resumo_estatistico(serie)

    assert resumo.contagem == 5
    assert resumo.media == 300.0
    assert resumo.mediana == 300.0
    assert resumo.minimo == 100.0
    assert resumo.maximo == 500.0
    assert resumo.percentil_95 == pytest.approx(480.0)


def test_resumo_estatistico_ignora_nulos() -> None:
    """Valores nulos são descartados da estatística."""
    resumo = resumo_estatistico(pd.Series([10.0, np.nan, 20.0, 30.0]))
    assert resumo.contagem == 3
    assert resumo.media == 20.0


def test_resumo_estatistico_serie_vazia_falha() -> None:
    """Série vazia levanta erro — sem medição enganosa."""
    with pytest.raises(ValueError):
        resumo_estatistico(pd.Series([], dtype=float))


def test_correlacao_pearson_positiva_perfeita() -> None:
    """r = 1.0 para variáveis linearmente proporcionais."""
    fatos = pd.DataFrame({"a": [1, 2, 3, 4], "b": [2, 4, 6, 8]})
    corr = correlacao_pearson(["a", "b"], fatos)
    assert corr["a"]["b"] == pytest.approx(1.0)


def test_correlacao_pearson_inversa() -> None:
    """r = -1.0 para variáveis inversamente proporcionais."""
    fatos = pd.DataFrame({"a": [1, 2, 3, 4], "b": [8, 6, 4, 2]})
    corr = correlacao_pearson(["a", "b"], fatos)
    assert corr["a"]["b"] == pytest.approx(-1.0)


def test_correlacao_pearson_ignora_colunas_nao_numericas() -> None:
    """Colunas não numéricas não entram na matriz de correlação."""
    fatos = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    corr = correlacao_pearson(["a", "b"], fatos)
    assert "b" not in corr


def test_correlacao_pearson_menos_de_2_validas() -> None:
    """Menos de duas colunas numéricas resulta em dicionário vazio."""
    corr = correlacao_pearson(["a"], pd.DataFrame({"a": [1.0, 2.0]}))
    assert corr == {}


def test_resumo_por_parlamentar_agrega_metricas() -> None:
    """total_gasto, num_fornecedores, ticket_medio e percentil_95 corretos."""
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 1, 2],
            "id_fornecedor": [10, 10, 20, 30],
            "valor_liquido": [100.0, 200.0, 300.0, 500.0],
        }
    )
    resumo = resumo_por_parlamentar(fatos)

    p1 = resumo[resumo["id_parlamentar"] == 1].iloc[0]
    assert p1["total_gasto"] == 600.0
    assert p1["num_fornecedores"] == 2
    assert p1["ticket_medio"] == 200.0
    assert p1["gasto_medio"] == 200.0
    assert p1["percentil_95"] == pytest.approx(290.0)

    p2 = resumo[resumo["id_parlamentar"] == 2].iloc[0]
    assert p2["total_gasto"] == 500.0
    assert p2["num_fornecedores"] == 1
    assert p2["percentil_95"] == 500.0


def test_resumo_por_parlamentar_vazio() -> None:
    """DataFrame vazio devolve DataFrame com as colunas, sem linhas."""
    resumo = resumo_por_parlamentar(pd.DataFrame())
    assert resumo.empty
    assert "total_gasto" in resumo.columns


def test_validar_features_no_registry_retorna_registry() -> None:
    """`validar_features_no_registry` devolve features do registry (ADR-028)."""
    nomes = validar_features_no_registry()
    assert "risk_index" in nomes
    assert "supplier_concentration_score" in nomes