# tests/pipeline/test_features.py
"""Contrato da Feature Store (ADR-028) — `analytics/features.py`.

Valida que o `feature_store/registry.yaml` respeita o contrato Pydantic
(ADR-028.1), que nomes são únicos (ADR-028.3) e que toda feature de
categoria `agregado`/`ml`/`composicao` tem origem concreta (feature
não-órfã, ADR-028.5). O registry do repo é a fonte da verdade — falhar
aqui significa que uma feature foi adicionada sem registro válido.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from analytics.features import (
    Feature,
    FeatureCategoria,
    FeatureRegistry,
    carregar_registry,
)

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


def test_registry_do_repo_valida() -> None:
    """O registry real carrega e valida no Pydantic (ADR-028.1)."""
    registry = carregar_registry()
    assert len(registry.features) >= 7


def test_registry_contem_features_baseline_adr027() -> None:
    """As 7 entradas baseline (ADR-027/028) estão registradas."""
    registry = carregar_registry()
    nomes = {f.nome for f in registry.features}
    esperadas = {
        "minmax",
        "regra_anomalia",
        "supplier_concentration_score",
        "political_exposure_score",
        "supplier_dependency_score",
        "expense_anomaly_score",
        "network_influence_score",
        "risk_index",
    }
    assert esperadas.issubset(nomes)


def test_nomes_sao_unicos() -> None:
    """Nomes de feature únicos no registry (ADR-028.3)."""
    registry = carregar_registry()
    nomes = [f.nome for f in registry.features]
    assert len(nomes) == len(set(nomes))


def test_features_nao_funcao_tem_tabela() -> None:
    """Feature de categoria persistente exige tabela de origem (ADR-028.5)."""
    registry = carregar_registry()
    for feature in registry.features:
        if feature.categoria != FeatureCategoria.FUNCAO:
            assert feature.tabela, (
                f"feature '{feature.nome}' sem 'tabela' — feature órfã "
                "(ADR-028.5)"
            )


def test_apenas_funcao_dispensa_tabela() -> None:
    """Toda feature de categoria `funcao` não exige tabela."""
    registry = carregar_registry()
    funcoes = [f for f in registry.features if f.categoria == FeatureCategoria.FUNCAO]
    assert len(funcoes) >= 2
    assert all(f.tabela is None for f in funcoes)


def test_feature_persistente_sem_tabela_falha() -> None:
    """Modelo rejeita feature de categoria persistente sem tabela."""
    with pytest.raises(ValidationError):
        Feature(
            nome="feature_sem_tabela",
            descricao="deve falhar",
            formula="x",
            origem="calculado",
            tipo="float",
            categoria=FeatureCategoria.AGREGADO,
        )


def test_feature_nome_invalido_falha() -> None:
    """Nome fora do padrão snake_case é rejeitado."""
    with pytest.raises(ValidationError):
        Feature(
            nome="Nome Com Espaço",
            descricao="deve falhar",
            formula="x",
            origem="calculado",
            tipo="float",
            categoria=FeatureCategoria.FUNCAO,
        )


def test_nomes_duplicados_falham() -> None:
    """Registry com nome duplicado é rejeitado (ADR-028.3)."""
    base = Feature(
        nome="dup",
        descricao="a",
        formula="x",
        origem="calculado",
        tipo="float",
        categoria=FeatureCategoria.FUNCAO,
    )
    with pytest.raises(ValidationError):
        FeatureRegistry.model_validate({"features": [base, base]})


def test_obter_retorna_feature_correta() -> None:
    """`registry.obter` encontra feature pelo nome."""
    registry = carregar_registry()
    assert registry.obter("risk_index") is not None
    assert registry.obter("nao_existe") is None


def test_ulima_atualizacao_null_ate_calcular() -> None:
    """Features ainda não calculadas têm `ultima_atualizacao` nula."""
    registry = carregar_registry()
    for feature in registry.features:
        assert feature.ultima_atualizacao is None


def test_registry_inexistente_levanta_erro() -> None:
    """Caminho inexistente falha com FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        carregar_registry(path=Path(__file__).with_name("nao_existe.yaml"))
