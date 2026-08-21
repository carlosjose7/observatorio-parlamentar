"""Contratos Pydantic da Gold — regressões de schema da Sprint 8."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pipeline.contracts import FonteOrigemUnidadeGestora, Poder, TipoDocumento
from pipeline.gold import (
    DimCategoriaDespesa,
    DimData,
    DimFornecedor,
    DimMunicipio,
    DimOrgao,
    DimParlamentar,
    DimPartido,
    DimUnidadeGestora,
    ExpenseOutliers,
    FactCartaoCpgf,
    FactDespesa,
    FactEmenda,
    NetworkEdges,
    NetworkNodes,
    PoliticianSimilarity,
    RiskScores,
    SupplierConcentration,
    SupplierGrowth,
)


def test_dimensoes_aceitam_contratos_validos():
    """Campos obrigatórios e opcionais das dimensões permanecem estáveis."""
    orgao = DimOrgao(id_orgao=1, poder=Poder.LEGISLATIVO, instituicao="Câmara", sigla="CD")
    unidade = DimUnidadeGestora(
        id_unidade_gestora=2,
        codigo="020001",
        nome="Senado Federal",
        id_orgao=orgao.id_orgao,
        fonte_origem=FonteOrigemUnidadeGestora.SIAFI,
    )
    fornecedor = DimFornecedor(
        id_fornecedor=3,
        cnpj_cpf_valor="11222333000181",
        tipo_documento=TipoDocumento.CNPJ,
        nome_fornecedor="Fornecedor A",
    )
    parlamentar = DimParlamentar(
        id_parlamentar=4,
        surrogate_key=5,
        nome="Parlamentar A",
        id_partido="PSOL",
        uf="SP",
        effective_date=date(2024, 1, 1),
        end_date=None,
        is_current=True,
    )
    assert unidade.gestao is None
    assert fornecedor.id_municipio is None
    assert parlamentar.is_current
    assert DimPartido(sigla="PSOL", nome="Partido Socialismo e Liberdade").ideologia is None
    assert DimMunicipio(cod_ibge=3550308, nome="São Paulo", uf="SP").uf == "SP"
    assert DimCategoriaDespesa(cod_tipo="passagem", descricao="Passagem").descricao == "Passagem"
    assert DimData(data_sk=20260101, data_completa=date(2026, 1, 1), ano=2026, mes=1, dia=1, is_dia_util=True).ano == 2026


def test_fatos_e_analiticos_aceitam_contrato_valido():
    versionamento = {
        "run_id": "run-1",
        "pipeline_version": "1.0.0",
        "execution_timestamp": "2026-01-01T00:00:00Z",
        "source_version": "fonte-1",
    }
    despesa = FactDespesa(
        id_despesa=1, id_parlamentar=2, id_fornecedor=3, id_orgao=1,
        cod_tipo="passagem", data_sk=20260101, cod_documento="doc-1",
        valor_liquido=Decimal("10.20"), valor_glosa=Decimal("0"), **versionamento,
    )
    emenda = FactEmenda(
        id_emenda=2, id_parlamentar=2, id_orgao=1, data_sk=20261231,
        codigo_emenda="2026-1", tipo_emenda="Individual", funcao="Saúde",
        subfuncao="Atenção", localidade_do_gasto="SP", valor_empenhado=Decimal("10"),
        valor_liquidado=Decimal("8"), valor_pago=Decimal("7"), **versionamento,
    )
    cartao = FactCartaoCpgf(
        id_transacao=3, id_orgao=4, id_unidade_gestora=5, data_sk=20260101,
        portador_nome="Servidor", portador_cpf_mascarado="***.123.456-**",
        valor_transacao=Decimal("9.99"), **versionamento,
    )
    assert despesa.id_unidade_gestora is None
    assert emenda.id_unidade_gestora is None
    assert cartao.id_fornecedor is None
    assert SupplierConcentration(ano=2026, id_parlamentar=2, num_fornecedores=1, total_valor=Decimal("10"), hhi=1).hhi == 1
    assert SupplierGrowth(ano=2026, id_fornecedor=3, valor_recebido=Decimal("10"), valor_ano_anterior=None, variacao_pct=None).variacao_pct is None
    assert ExpenseOutliers(
        id_despesa=1, id_parlamentar=2, data_sk=20260101, valor_liquido=Decimal("10"),
        criterio_zscore=True, criterio_if=False, criterio_fornecedor_poucos_clientes=False,
        criterio_empresa_nova=False, criterio_valores_identicos=True,
        criterio_dia_sem_sessao=False, num_criterios=2, **versionamento,
    ).id_fornecedor is None
    assert NetworkEdges(id_parlamentar=2, id_fornecedor=3, periodo=2026, valor_total=Decimal("10"), **versionamento).periodo == 2026
    assert NetworkNodes(id_no=2, tipo_no="parlamentar", periodo=2026, pagerank=0.3, degree_centrality=0.2, **versionamento).comunidade_id is None
    assert PoliticianSimilarity(id_parlamentar_a=2, id_parlamentar_b=4, periodo=2026, num_fornecedores_compartilhados=1, similaridade=0.8, **versionamento).similaridade == 0.8
    assert RiskScores(periodo=2026, id_parlamentar=2, supplier_concentration_score=0.1, political_exposure_score=0.2, supplier_dependency_score=0.3, expense_anomaly_score=0.4, network_influence_score=0.5, risk_index=0.3, **versionamento).risk_index == 0.3


def test_fatos_rejeitam_campos_obrigatorios_ausentes():
    with pytest.raises(ValidationError, match="id_parlamentar"):
        FactEmenda(
            id_emenda=1, id_orgao=1, data_sk=20261231, codigo_emenda="2026-1",
            tipo_emenda="Individual", funcao="Saúde", subfuncao="Atenção",
            localidade_do_gasto="SP", valor_empenhado=1, valor_liquidado=1, valor_pago=1,
            run_id="run", pipeline_version="1", execution_timestamp="agora", source_version="fonte",
        )
    with pytest.raises(ValidationError, match="id_unidade_gestora"):
        FactCartaoCpgf(
            id_transacao=1, id_orgao=1, data_sk=20260101, portador_nome="Servidor",
            portador_cpf_mascarado="***", valor_transacao=1, run_id="run",
            pipeline_version="1", execution_timestamp="agora", source_version="fonte",
        )
