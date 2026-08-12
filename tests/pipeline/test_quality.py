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
    schema_silver_emenda,
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


class TestSchemaSilverEmenda:
    def _df_emenda(self, **override):
        dados = {
            "ano": [2024],
            "codigo_emenda": ["202440340007"],
            "tipo_emenda": ["Emenda Individual - Transferências com Finalidade Definida"],
            "nome_autor": ["LUISA CANZIANI"],
            "funcao": ["Saúde"],
            "subfuncao": ["Assistência hospitalar e ambulatorial"],
            "localidade_do_gasto": ["LONDRINA - PR"],
            "valor_empenhado": [10000.0],
            "valor_liquidado": [10000.0],
            "valor_pago": [10000.0],
        }
        dados.update(override or {})
        return pd.DataFrame(dados)

    def test_valido_passa_sem_quarentena(self):
        df = self._df_emenda()
        validos, linha = avaliar_qualidade(
            df, schema_silver_emenda(), "run1", "silver_emenda"
        )
        assert len(validos) == 1
        assert linha.registros_quarentena == 0

    def test_chave_negocio_composta_detecta_duplicata(self):
        base = self._df_emenda()
        df = pd.concat([base, base], ignore_index=True)
        df["ano"] = [2024, 2024]
        df["codigo_emenda"] = ["E1", "E1"]
        validos, linha = avaliar_qualidade(
            df, schema_silver_emenda(), "run1", "silver_emenda"
        )
        assert "chave_negocio_unica" in linha.regras_violadas

    def test_mesmo_codigo_em_anos_distinto_nao_duplicata(self):
        # A chave e (ano, codigo_emenda); mesmo codigo em anos
        # diferentes nao e duplicata (ADR-017).
        base = self._df_emenda()
        df = pd.concat([base, base], ignore_index=True)
        df["ano"] = [2023, 2024]
        df["codigo_emenda"] = ["E1", "E1"]
        validos, linha = avaliar_qualidade(
            df, schema_silver_emenda(), "run1", "silver_emenda"
        )
        assert len(validos) == 2
        assert linha.registros_quarentena == 0

    def test_codigo_si_em_quarentena(self):
        df = self._df_emenda(codigo_emenda=["S/I"])
        validos, linha = avaliar_qualidade(
            df, schema_silver_emenda(), "run1", "silver_emenda"
        )
        assert len(validos) == 0
        assert "codigo_nao_si" in linha.regras_violadas

    def test_valor_negativo_em_quarentena(self):
        df = self._df_emenda(valor_empenhado=[-5.0])
        validos, linha = avaliar_qualidade(
            df, schema_silver_emenda(), "run1", "silver_emenda"
        )
        assert len(validos) == 0
        assert linha.registros_quarentena == 1


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


class TestPersistenciaDedupSilver:
    """Carga Silver integrada: linhas removidas persistidas + report (ADR-014/015).

    Usa DuckDB em arquivo temporário — verifica que `deduplicar_silver`
    `removidas` sao gravadas em `dedup_removidas_{tabela}` e que o
    `data_quality_report` contabiliza `registros_deduplicados`.
    """

    def _carregar(self, tmp_path, df, tabela, chaves):
        import duckdb

        db_path = tmp_path / "silver_test.duckdb"
        monkeypatch_env = f"DUCKDB_DATABASE_PATH={db_path}"

        # get_env() e cacheado (lru_cache) — limpa para usar o path temporario
        import pipeline.config as config
        import pipeline.silver as silver

        config.load_env_settings.cache_clear()

        import os

        old = os.environ.get("DUCKDB_DATABASE_PATH")
        os.environ["DUCKDB_DATABASE_PATH"] = str(db_path)
        try:
            return silver.carregar_tabela_silver(
                df, tabela, "run-test", chaves_dedup=chaves
            )
        finally:
            if old is None:
                os.environ.pop("DUCKDB_DATABASE_PATH", None)
            else:
                os.environ["DUCKDB_DATABASE_PATH"] = old
            config.load_env_settings.cache_clear()

    def _query(self, tmp_path, sql):
        import duckdb

        db_path = tmp_path / "silver_test.duckdb"
        con = duckdb.connect(str(db_path))
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_removidas_persistidas_e_report(self, tmp_path):
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
        resultado = self._carregar(tmp_path, df, "silver_despesa", ["fonte", "cod_documento"])

        assert len(resultado.deduplicadas) == 1
        assert len(resultado.aceitos) == 1

        removidas = self._query(tmp_path, "SELECT cod_documento FROM dedup_removidas_silver_despesa")
        assert removidas == [("AAA",)]

        report = self._query(
            tmp_path,
            "SELECT registros_deduplicados, registros_validos FROM data_quality_report",
        )
        assert report == [(1, 1)]

    def test_sem_duplicatas_nao_cria_tabela(self, tmp_path):
        df = pd.DataFrame(
            {
                "fonte": ["camara"],
                "cod_documento": ["AAA"],
                "data_documento": pd.to_datetime(["2024-07-03"]),
                "valor_liquido": [100.0],
                "valor_glosa": [0.0],
                "tipo_documento": ["CNPJ"],
            }
        )
        self._carregar(tmp_path, df, "silver_despesa", ["fonte", "cod_documento"])

        import duckdb

        db_path = tmp_path / "silver_test.duckdb"
        con = duckdb.connect(str(db_path))
        try:
            tabelas = con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
            nomes = [t[0] for t in tabelas]
            assert "dedup_removidas_silver_despesa" not in nomes
        finally:
            con.close()

    def test_reexecucao_mesma_chave_upsert_nao_duplica(self, tmp_path):
        """Corretivo QA BUG-003: a Silver é idempotente por chave de negócio —
        re-executar a mesma carga SUBSTITUI o registro (DELETE+INSERT via
        `escrever_validos_duckdb`), não duplica a linha na tabela."""
        df = pd.DataFrame(
            {
                "fonte": ["camara"],
                "cod_documento": ["AAA"],
                "data_documento": pd.to_datetime(["2024-07-03"]),
                "valor_liquido": [100.0],
                "valor_glosa": [0.0],
                "tipo_documento": ["CNPJ"],
            }
        )
        chaves = ["fonte", "cod_documento"]
        self._carregar(tmp_path, df, "silver_despesa", chaves)
        self._carregar(tmp_path, df, "silver_despesa", chaves)

        linhas = self._query(
            tmp_path,
            "SELECT fonte, cod_documento FROM silver_despesa WHERE cod_documento = 'AAA'",
        )
        assert linhas == [("camara", "AAA")]  # 1 linha, nunca 2

    def test_correcao_de_registro_em_reexecucao_reflete(self, tmp_path):
        """Corretivo QA BUG-003: correção de um registro já consolidado (mesma
        chave, valor novo) REFLETE na Silver em vez de gerar nova linha —
        a reexecução não cria novo `cod_documento`."""
        def _df(valor):
            return pd.DataFrame(
                {
                    "fonte": ["camara"],
                    "cod_documento": ["AAA"],
                    "data_documento": pd.to_datetime(["2024-07-03"]),
                    "valor_liquido": [valor],
                    "valor_glosa": [0.0],
                    "tipo_documento": ["CNPJ"],
                }
            )

        chaves = ["fonte", "cod_documento"]
        self._carregar(tmp_path, _df(100.0), "silver_despesa", chaves)
        self._carregar(tmp_path, _df(250.0), "silver_despesa", chaves)

        linhas = self._query(
            tmp_path,
            "SELECT cod_documento, valor_liquido FROM silver_despesa WHERE cod_documento = 'AAA'",
        )
        assert linhas == [("AAA", 250.0)]

    def test_migracao_de_schema_em_tabela_legada(self, tmp_path):
        """Corretivo QA BUG-004: tabela Silver legada (criada por uma versão
        anterior sem `valor_liquido`) é MIGRADA via `ALTER TABLE ADD COLUMN`
        na carga — o INSERT por nome persiste a coluna nova em vez de falhar
        ou desalinhar colunas."""
        import duckdb

        db_path = tmp_path / "silver_test.duckdb"
        con = duckdb.connect(str(db_path))
        con.execute(
            "create table silver_despesa ("
            "  fonte varchar, cod_documento varchar, data_documento date,"
            "  valor_glosa double, tipo_documento varchar)"
        )
        con.close()

        df = pd.DataFrame(
            {
                "fonte": ["camara"],
                "cod_documento": ["AAA"],
                "data_documento": pd.to_datetime(["2024-07-03"]),
                "valor_liquido": [100.0],  # coluna nova, ausente no schema legado
                "valor_glosa": [0.0],
                "tipo_documento": ["CNPJ"],
            }
        )
        self._carregar(tmp_path, df, "silver_despesa", ["fonte", "cod_documento"])

        colunas = [
            c[0]
            for c in self._query(
                tmp_path,
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'silver_despesa'",
            )
        ]
        assert "valor_liquido" in colunas

        linhas = self._query(
            tmp_path,
            "SELECT cod_documento, valor_liquido, valor_glosa FROM silver_despesa"
            " WHERE cod_documento = 'AAA'",
        )
        assert linhas == [("AAA", 100.0, 0.0)]
