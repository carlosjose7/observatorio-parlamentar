# tests/pipeline/test_transform_camara.py
"""Testes do transform Bronze → Silver da Câmara (ADR-023, Trilha B).

Cobre o mapeamento puro (`construir_silver`) e a carga integrada
(`carregar_silver_despesa`) com DuckDB em arquivo temporário.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from pipeline.camara.transform import COLUNAS_SILVER, construir_silver
from pipeline.storage import LocalParquetStorage


def _df_bronze(**override) -> pd.DataFrame:
    dados = {
        "ano": [2024],
        "mes": [7],
        "cnpj_cpf_fornecedor": ["01.234.567/0001-89"],
        "cod_documento": ["a3f3c9b1-0000-4000-8000-000000000001"],
        "data_documento": ["2024-07-03T00:00:00"],
        "tipo_despesa": ["PASSAGEM AÉREA"],
        "nome_fornecedor": ["LATAM AIRLINES"],
        "valor_liquido": [1234.56],
        "valor_glosa": [0.0],
        "run_id": ["run-0001"],
        "pipeline_version": ["0.1.0"],
        "execution_timestamp": ["2024-08-01T00:00:00Z"],
        "source_version": ["2024-07-03"],
    }
    dados.update(override or {})
    return pd.DataFrame(dados)


class TestConstruirCamara:
    def test_mapeamento_canonico(self):
        df = construir_silver(_df_bronze())

        assert list(df.columns) == COLUNAS_SILVER
        assert df.loc[0, "fonte"] == "camara"
        assert df.loc[0, "cod_documento"] == "a3f3c9b1-0000-4000-8000-000000000001"
        assert df.loc[0, "cnpj_cpf_valor"] == "01234567000189"
        assert df.loc[0, "tipo_documento"] == "CNPJ"
        assert df.loc[0, "valor_liquido"] == 1234.56
        assert str(df.loc[0, "data_documento"])[:10] == "2024-07-03"

    def test_cpf_classificado(self):
        df = construir_silver(_df_bronze(cnpj_cpf_fornecedor=["123.456.789-01"]))
        assert df.loc[0, "cnpj_cpf_valor"] == "12345678901"
        assert df.loc[0, "tipo_documento"] == "CPF"

    def test_documento_ausente_nao_classifica(self):
        df = construir_silver(_df_bronze(cnpj_cpf_fornecedor=[None]))
        assert df.loc[0, "cnpj_cpf_valor"] is None
        assert df.loc[0, "tipo_documento"] is None

    def test_data_nao_parseavel_fica_nat(self):
        df = construir_silver(_df_bronze(data_documento=["invalido"]))
        assert pd.isna(df.loc[0, "data_documento"])

    def test_vazio_retorna_schema(self):
        df = construir_silver(pd.DataFrame(columns=["ano"]))
        assert df.empty
        assert list(df.columns) == COLUNAS_SILVER


class TestCarregarCamara:
    def _carregar(self, tmp_path, df_bronze):
        import pipeline.config as config

        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        storage = LocalParquetStorage(root)
        storage.write_file(Path("camara"), df_bronze, "run-1.parquet")

        db_path = tmp_path / "silver.duckdb"
        config.load_env_settings.cache_clear()
        old = os.environ.get("DUCKDB_DATABASE_PATH")
        os.environ["DUCKDB_DATABASE_PATH"] = str(db_path)
        try:
            from pipeline.camara.transform import carregar_silver_despesa

            return carregar_silver_despesa(storage=storage, run_id="run-0001")
        finally:
            if old is None:
                os.environ.pop("DUCKDB_DATABASE_PATH", None)
            else:
                os.environ["DUCKDB_DATABASE_PATH"] = old
            config.load_env_settings.cache_clear()

    def test_carga_integrada_persiste(self, tmp_path):
        resultado = self._carregar(tmp_path, _df_bronze())

        assert resultado is not None
        assert len(resultado.aceitos) == 1
        assert resultado.quarentena.empty

        import duckdb

        con = duckdb.connect(str(tmp_path / "silver.duckdb"))
        try:
            linhas = con.execute(
                "select fonte, cod_documento from silver_despesa"
            ).fetchall()
        finally:
            con.close()
        assert linhas == [("camara", "a3f3c9b1-0000-4000-8000-000000000001")]

    def test_bronze_vazio_retorna_none(self, tmp_path):
        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        from pipeline.camara.transform import carregar_silver_despesa

        assert carregar_silver_despesa(LocalParquetStorage(root), "run-0001") is None