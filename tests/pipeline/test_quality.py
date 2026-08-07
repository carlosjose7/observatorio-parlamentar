# tests/pipeline/test_quality.py
"""Testes unitários do pipeline/quality.py (ADR-013/ADR-015).

Cobre o gate Pandera do `silver_despesa`: separação de valores de regras de
lote violadas (quarentena), exclusão da chave de negócio duplicada, percentual
de nulos e o registro do Data Quality Report.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline.quality import (
    avaliar_qualidade,
    percentual_nulos,
    schema_silver_cartao,
    schema_silver_despesa,
)


def _df_despesa(valor_liquido):
    n = len(valor_liquido)
    return pd.DataFrame(
        {
            "fonte": ["camara"] * n,
            "cod_documento": [f"C{i}" for i in range(n)],
            "data_documento": pd.to_datetime(["2024-07-03"] * n),
            "valor_liquido": valor_liquido,
            "valor_glosa": [0.0] * n,
            "tipo_documento": ["CNPJ"] * n,
        }
    )


class TestSchemaSilverDespesa:
    def test_tudo_valido_passa_sem_quarentena(self):
        from pipeline.quality import avaliar_qualidade

        df = pd.DataFrame(
            {
                "fonte": ["camara", "senado"],
                "cod_documento": ["AAA", "BBB"],
                "data_documento": pd.to_datetime(["2024-07-03", "2024-07-03"]),
                "valor_liquido": [100.0, 50.0],
                "valor_glosa": [0.0, 0.0],
                "tipo_documento": ["CNPJ", "CPF"],
            }
        )
        validos, linha = avaliar_qualidade(
            df, schema_silver_despesa(), "run1", "silver_despesa"
        )
        assert len(validos) == 2
        assert linha.registros_quarentena == 0
        assert linha.regras_violadas == []

    def test_valor_negativo_em_quarentena(self):
        from pipeline.quality import avaliar_qualidade

        df = _df_despesa([100.0, -5.0, 30.0])
        validos, linha = avaliar_qualidade(
            df, schema_silver_despesa(), "run1", "silver_despesa"
        )
        assert len(validos) == 2
        assert linha.registros_quarentena == 1

    def test_data_anterior_2015_em_quarentena(self):
        from pipeline.quality import avaliar_qualidade

        df = pd.DataFrame(
            {
                "fonte": ["camara", "camara"],
                "cod_documento": ["AAA", "BBB"],
                "data_documento": pd.to_datetime(["2014-12-31", "2024-07-03"]),
                "valor_liquido": [100.0, 50.0],
                "valor_glosa": [0.0, 0.0],
                "tipo_documento": ["CNPJ", "CNPJ"],
            }
        )
        validos, linha = avaliar_qualidade(
            df, schema_silver_despesa(), "run1", "silver_despesa"
        )
        assert linha.registros_quarentena == 1
        assert "nao_anterior_2015" in linha.regras_violadas

    def test_chave_negocio_duplicada_detectada(self):
        from pipeline.quality import avaliar_qualidade

        df = pd.DataFrame(
            {
                "fonte": ["camara", "camara"],
                "cod_documento": ["AAA", "AAA"],
                "data_documento": pd.to_datetime(["2024-07-03", "2024-07-03"]),
                "valor_liquido": [100.0, 100.0],
                "valor_glosa": [0.0, 0.0],
                "tipo_documento": ["CNPJ", "CNPJ"],
            }
        )
        validos, linha = avaliar_qualidade(
            df, schema_silver_despesa(), "run1", "silver_despesa"
        )
        assert "chave_negocio_unica" in linha.regras_violadas

    def test_df_vazio_nao_quarentena(self):
        from pipeline.quality import avaliar_qualidade

        df = pd.DataFrame(columns=["fonte", "cod_documento", "data_documento"])
        validos, linha = avaliar_qualidade(
            df, schema_silver_despesa(), "run1", "silver_despesa"
        )
        assert len(validos) == 0
        assert linha.registros_quarentena == 0


class TestSchemaSilverCartao:
    def _df_cartao(self, **override):
        dados = {
            "data_transacao": pd.to_datetime(["2024-07-03"]),
            "valor_transacao": [97.89],
            "estabelecimento_cnpj_valor": ["11222333000181"],
            "estabelecimento_tipo_documento": ["CNPJ"],
            "estabelecimento_nome": ["FARMACIA SAO PAULO"],
            "portador_nome": ["JOSE DA SILVA"],
            "portador_cpf_mascarado": ["***.122.497-**"],
            "unidade_gestora_codigo": ["15001"],
            "unidade_gestora_nome": ["INSTITUTO NACIONAL"],
        }
        dados.update(override or {})
        return pd.DataFrame(dados)

    def test_valido_passa_sem_quarentena(self):
        df = self._df_cartao()
        validos, linha = avaliar_qualidade(
            df, schema_silver_cartao(), "run1", "silver_cartao"
        )
        assert len(validos) == 1
        assert linha.registros_quarentena == 0

    def test_unidade_gestora_ausente_em_quarentena(self):
        df = self._df_cartao(unidade_gestora_codigo=[None])
        validos, linha = avaliar_qualidade(
            df, schema_silver_cartao(), "run1", "silver_cartao"
        )
        assert len(validos) == 0
        assert linha.registros_quarentena == 1

    def test_valor_negativo_em_quarentena(self):
        df = self._df_cartao(valor_transacao=[-5.0])
        validos, linha = avaliar_qualidade(
            df, schema_silver_cartao(), "run1", "silver_cartao"
        )
        assert len(validos) == 0
        assert linha.registros_quarentena == 1

    def test_chave_negocio_parametrizada_reaproveita_fallback(self):
        df = pd.DataFrame(
            {
                "data_transacao": pd.to_datetime(["2024-07-03", "2024-07-03"]),
                "valor_transacao": [10.0, 10.0],
                "estabelecimento_cnpj_valor": [None, None],
                "estabelecimento_tipo_documento": [None, None],
                "estabelecimento_nome": ["A", "A"],
                "portador_nome": ["B", "B"],
                "portador_cpf_mascarado": ["***", "***"],
                "unidade_gestora_codigo": ["1", "1"],
                "unidade_gestora_nome": ["UG", "UG"],
                "codigo_transacao": ["T1", "T1"],
            }
        )
        validos, linha = avaliar_qualidade(
            df,
            schema_silver_cartao(),
            "run1",
            "silver_cartao",
            chaves_negocio=["codigo_transacao"],
        )
        assert "chave_negocio_unica" in linha.regras_violadas


class TestPercentualNulos:
    def test_sem_nulos(self):
        df = pd.DataFrame({"valor_liquido": [100.0, 50.0]})
        assert percentual_nulos(df, ["valor_liquido"]) == 0.0

    def test_metade_nulos(self):
        df = pd.DataFrame({"valor_liquido": [100.0, None]})
        assert percentual_nulos(df, ["valor_liquido"]) == 0.5

    def test_campo_inexistente_ignorado(self):
        df = pd.DataFrame({"valor_liquido": [100.0]})
        assert percentual_nulos(df, ["campo_inexistente"]) == 0.0

    def test_df_vazio(self):
        assert percentual_nulos(pd.DataFrame(), ["x"]) == 0.0