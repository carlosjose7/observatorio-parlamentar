# tests/pipeline/test_transform_senado.py
"""Testes do transform Bronze → Silver do Senado (ADR-023, Trilha B)."""

from __future__ import annotations

import pandas as pd
from decimal import Decimal

from pipeline.normalize import normalizar_nome_proprio, parse_decimal_ptbr
from pipeline.senado.transform import COLUNAS_SILVER, construir_silver


def _df_bronze(**override) -> pd.DataFrame:
    dados = {
        "ano": [2024],
        "mes": [3],
        "senador": ["EDUARDO GOMES"],
        "tipo_despesa": ["PASSAGENS"],
        "cnpj_cpf": ["04.433.000/0001-90"],
        "fornecedor": ["TAM LINHAS AEREAS"],
        "documento": ["12345"],
        "data": ["03/03/2024"],
        "detalhamento": ["Trecho Brasília-São Paulo"],
        "valor_reembolsado": ["1.234,56"],
        "cod_documento": [90201],
        "run_id": ["run-0001"],
        "pipeline_version": ["0.1.0"],
        "execution_timestamp": ["2024-08-01T00:00:00Z"],
        "source_version": ["despesa_ceaps_2024.csv"],
    }
    dados.update(override or {})
    return pd.DataFrame(dados)


class TestConstruirSenado:
    def test_mapeamento_canonico(self):
        df = construir_silver(_df_bronze())

        assert list(df.columns) == COLUNAS_SILVER
        assert df.loc[0, "fonte"] == "senado"
        assert df.loc[0, "cod_documento"] == "90201"
        assert df.loc[0, "cnpj_cpf_valor"] == "04433000000190"
        assert df.loc[0, "tipo_documento"] == "CNPJ"
        assert df.loc[0, "valor_liquido"] == 1234.56
        assert df.loc[0, "valor_glosa"] == 0.0
        assert str(df.loc[0, "data_documento"])[:10] == "2024-03-03"

    def test_valor_ptbr_e_data_ddmmaaaa(self):
        df = construir_silver(
            _df_bronze(valor_reembolsado=["12,50"], data=["31/12/2023"])
        )
        assert df.loc[0, "valor_liquido"] == 12.50
        assert str(df.loc[0, "data_documento"])[:10] == "2023-12-31"

    def test_cpf_pessoa_fisica(self):
        df = construir_silver(_df_bronze(cnpj_cpf=["123.456.789-01"]))
        assert df.loc[0, "cnpj_cpf_valor"] == "12345678901"
        assert df.loc[0, "tipo_documento"] == "CPF"

    def test_valor_nao_parseavel_vira_nan(self):
        df = construir_silver(_df_bronze(valor_reembolsado=["N/A"]))
        assert pd.isna(df.loc[0, "valor_liquido"])

    def test_vazio_retorna_schema(self):
        df = construir_silver(pd.DataFrame(columns=["ano"]))
        assert df.empty


class TestNormalizacaoSenado:
    def test_decimal_ptbr(self):
        assert parse_decimal_ptbr("1.234,56") == Decimal("1234.56")

    def test_normalizar_nome_proprio(self):
        assert normalizar_nome_proprio("João da Silva") == "JOAO DA SILVA"
        assert normalizar_nome_proprio(None) is None