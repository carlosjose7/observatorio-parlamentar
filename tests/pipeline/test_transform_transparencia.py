# tests/pipeline/test_transform_transparencia.py
"""Testes do transform Bronze → Silver da CGU (cartões e emendas, ADR-023).

Cobre o mapeamento puro (`construir_silver_cartao` / `construir_silver_emenda`)
e a carga integrada dos dois grãos com DuckDB temporário.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd
import pytest

import pipeline.config as config
from pipeline.pseudonymize import pseudonymize_cpf
from pipeline.storage import LocalParquetStorage
from pipeline.transparencia.transform import (
    COLUNAS_SILVER_CARTAO,
    COLUNAS_SILVER_EMENDA,
    construir_silver_cartao,
    construir_silver_emenda,
)

_CHAVE_TESTE = "chave-teste-transform-transparencia-2026"
# CPF pseudonimizado na Silver (ADR-033): o hash dos testes usa a MESMA chave
# do EnvSettings injetada pelo fixture autouse `_cpf_env`.
_CPF_HMAC = pseudonymize_cpf("12345678901", _CHAVE_TESTE.encode("utf-8"))


@pytest.fixture(autouse=True)
def _cpf_env(monkeypatch):
    """Define chave HMAC determinística (ADR-033) e limpa o cache de settings.

    `pseudonymize_cpf_column` lê `EnvSettings.cpf_hmac_secret_key`, que é
    cacheado por `functools.lru_cache` — sem limpar o cache, um `.env` ou
    teste anterior vazando o caminho DuckDB invalidaria a chave.
    """
    monkeypatch.setenv("CPF_HMAC_SECRET_KEY", _CHAVE_TESTE)
    config.load_env_settings.cache_clear()
    yield
    config.load_env_settings.cache_clear()


def _df_cartao(**override) -> pd.DataFrame:
    dados = {
        "id": [9001],
        "mes_extrato": ["07/2024"],
        "data_transacao": ["03/07/2024"],
        "valor_transacao": ["1.234,56"],
        "tipo_cartao_codigo": ["1"],
        "estabelecimento_id": [55],
        "estabelecimento_cnpj_formatado": ["12.222.333/0001-81"],
        "estabelecimento_cpf_formatado": [None],
        "estabelecimento_nome": ["FARMACIA SAO PAULO"],
        "estabelecimento_razao_social_receita": ["FARMACIA SAO PAULO LTDA"],
        "estabelecimento_tipo": ["CNPJ"],
        "estabelecimento_numero_inscricao_social": [None],
        "portador_nome": ["JOSE DA SILVA"],
        "portador_cpf_formatado": ["***.122.497-**"],
        "portador_nis": [None],
        "unidade_gestora_codigo": ["15001"],
        "unidade_gestora_nome": ["INSTITUTO NACIONAL"],
        "run_id": ["run-0001"],
        "pipeline_version": ["0.1.0"],
        "execution_timestamp": ["2024-08-01T00:00:00Z"],
        "source_version": ["07/2024-execution-2024-08-01"],
    }
    dados.update(override or {})
    return pd.DataFrame(dados)


def _df_emenda(**override) -> pd.DataFrame:
    dados = {
        "ano": [2024],
        "codigo_emenda": ["202440340007"],
        "tipo_emenda": ["Emenda Individual - Transferências"],
        "nome_autor": ["Luisa Canziani"],
        "numero_emenda": ["12330007"],
        "funcao": ["Saúde"],
        "subfuncao": ["Assistência hospitalar"],
        "localidade_do_gasto": ["LONDRINA - PR"],
        "valor_empenhado": ["10.000,00"],
        "valor_liquidado": ["10.000,00"],
        "valor_pago": ["9.500,00"],
        "valor_resto_inscrito": ["500,00"],
        "valor_resto_cancelado": ["0,00"],
        "valor_resto_pago": ["0,00"],
        "run_id": ["run-0001"],
        "pipeline_version": ["0.1.0"],
        "execution_timestamp": ["2024-08-01T00:00:00Z"],
        "source_version": ["2024-execution-2024-08-01"],
    }
    dados.update(override or {})
    return pd.DataFrame(dados)


class TestConstruirCartao:
    def test_mapeamento_canonico(self):
        df = construir_silver_cartao(_df_cartao())

        assert list(df.columns) == COLUNAS_SILVER_CARTAO
        assert df.loc[0, "id"] == 9001
        assert df.loc[0, "estabelecimento_cnpj_valor"] == "12222333000181"
        assert df.loc[0, "estabelecimento_tipo_documento"] == "CNPJ"
        assert df.loc[0, "valor_transacao"] == 1234.56
        assert df.loc[0, "portador_cpf_mascarado"] == "***.122.497-**"
        assert str(df.loc[0, "data_transacao"])[:10] == "2024-07-03"

    def test_estabelecimento_sem_cnpj_nao_classifica(self):
        df = construir_silver_cartao(_df_cartao(estabelecimento_cnpj_formatado=[None]))
        assert df.loc[0, "estabelecimento_cnpj_valor"] is None
        assert df.loc[0, "estabelecimento_tipo_documento"] is None

    def test_estabelecimento_pessoa_cpf_pseudonimizado(self):
        df = construir_silver_cartao(
            _df_cartao(estabelecimento_cnpj_formatado=["123.456.789-01"])
        )
        assert df.loc[0, "estabelecimento_cnpj_valor"] == _CPF_HMAC
        assert df.loc[0, "estabelecimento_tipo_documento"] == "CPF"

    def test_vazio_retorna_schema(self):
        df = construir_silver_cartao(pd.DataFrame(columns=["id"]))
        assert df.empty


class TestConstruirEmenda:
    def test_mapeamento_canonico(self):
        df = construir_silver_emenda(_df_emenda())

        assert list(df.columns) == COLUNAS_SILVER_EMENDA
        assert df.loc[0, "codigo_emenda"] == "202440340007"
        assert df.loc[0, "nome_autor"] == "LUISA CANZIANI"
        assert df.loc[0, "valor_empenhado"] == 10000.0
        assert df.loc[0, "valor_pago"] == 9500.0

    def test_nome_autor_normalizado_sem_acento(self):
        df = construir_silver_emenda(_df_emenda(nome_autor=["João da Silva"]))
        assert df.loc[0, "nome_autor"] == "JOAO DA SILVA"

    def test_vazio_retorna_schema(self):
        df = construir_silver_emenda(pd.DataFrame(columns=["ano"]))
        assert df.empty


class TestCarregarCgu:
    def _carregar(self, tmp_path, diretorio, df_bronze, funcao, run_id):
        import pipeline.config as config

        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        storage = LocalParquetStorage(root)
        storage.write_file(Path(diretorio), df_bronze, "run-1.parquet")

        db_path = tmp_path / "silver.duckdb"
        config.load_env_settings.cache_clear()
        old = os.environ.get("DUCKDB_DATABASE_PATH")
        os.environ["DUCKDB_DATABASE_PATH"] = str(db_path)
        try:
            return funcao(storage=storage, run_id=run_id)
        finally:
            if old is None:
                os.environ.pop("DUCKDB_DATABASE_PATH", None)
            else:
                os.environ["DUCKDB_DATABASE_PATH"] = old
            config.load_env_settings.cache_clear()

    def test_carga_cartao_integrada(self, tmp_path):
        from pipeline.transparencia.transform import carregar_silver_cartao

        resultado = self._carregar(
            tmp_path,
            "transparencia_cartoes",
            _df_cartao(),
            carregar_silver_cartao,
            "run-0001",
        )
        assert resultado is not None
        assert len(resultado.aceitos) == 1

        con = duckdb.connect(str(tmp_path / "silver.duckdb"))
        try:
            linha = con.execute(
                "select id, unidade_gestora_codigo from silver_cartao"
            ).fetchall()
        finally:
            con.close()
        assert linha == [(9001, "15001")]

    def test_carga_emenda_integrada(self, tmp_path):
        from pipeline.transparencia.transform import carregar_silver_emenda

        resultado = self._carregar(
            tmp_path,
            "transparencia_emendas",
            _df_emenda(),
            carregar_silver_emenda,
            "run-0001",
        )
        assert resultado is not None
        assert len(resultado.aceitos) == 1