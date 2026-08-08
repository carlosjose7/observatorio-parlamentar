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


def _df_bronze_parlamentar(**override) -> pd.DataFrame:
    dados = {
        "id_deputado": [1],
        "nome_civil": ["ANA BEATRIZ OLIVEIRA"],
        "nome_eleitoral": ["ANA BEATRIZ"],
        "sigla_partido": ["PSB"],
        "sigla_uf": ["PE"],
        "id_legislatura": [57],
        "situacao": ["Exercício"],
        "condicao_eleitoral": ["Titular"],
        "data_status": ["2026-08-07T00:00:00"],
        "run_id": ["run-0001"],
        "pipeline_version": ["0.1.0"],
        "execution_timestamp": ["2026-08-07T00:00:00Z"],
        "source_version": ["2026-08-07"],
    }
    dados.update(override or {})
    return pd.DataFrame(dados)


class TestConstruirParlamentarCamara:
    def test_mapeamento_canonico(self):
        from pipeline.camara.transform import (
            COLUNAS_SILVER_PARLAMENTAR,
            construir_silver_parlamentar,
        )

        df = construir_silver_parlamentar(_df_bronze_parlamentar())

        assert list(df.columns) == COLUNAS_SILVER_PARLAMENTAR
        assert df.loc[0, "fonte"] == "camara"
        assert df.loc[0, "id_parlamentar"] == 1
        assert df.loc[0, "nome"] == "ANA BEATRIZ"
        assert df.loc[0, "sigla_partido"] == "PSB"
        assert df.loc[0, "sigla_uf"] == "PE"
        assert df.loc[0, "id_legislatura"] == 57  # derivada do calendário (2026-08-07)
        assert df.loc[0, "id_legislatura_fonte"] == 57  # bruto da API
        assert df.loc[0, "situacao_bruta"] == "Exercício"
        assert df.loc[0, "situacao_normalizada"] == "ativo"
        assert str(df.loc[0, "data"])[:10] == "2026-08-07"

    def test_legislatura_derivada_fora_do_calendario_vira_zero(self):
        from pipeline.camara.transform import construir_silver_parlamentar

        df = construir_silver_parlamentar(
            _df_bronze_parlamentar(data_status=["2000-01-01T00:00:00"])
        )
        assert df.loc[0, "id_legislatura"] == 0
        # o gate gt(0) da Silver manda para a quarentena (ADR-024)
        assert df.loc[0, "id_legislatura_fonte"] == 57

    def test_data_nao_parseavel_vira_zero_na_derivacao(self):
        from pipeline.camara.transform import construir_silver_parlamentar

        df = construir_silver_parlamentar(
            _df_bronze_parlamentar(data_status=["valor_invalido"])
        )
        # NaT → 0 → capturado pelo gate gt(0) (ADR-024); não quebra o transform
        assert df.loc[0, "id_legislatura"] == 0
        assert pd.isna(df.loc[0, "data"])

    def test_situacao_desconhecida_vira_sentinela(self):
        from pipeline.camara.transform import construir_silver_parlamentar

        df = construir_silver_parlamentar(
            _df_bronze_parlamentar(situacao=["Inventada"])
        )
        assert df.loc[0, "situacao_bruta"] == "Inventada"
        assert df.loc[0, "situacao_normalizada"] == "nao_mapeado"

    def test_nome_recai_no_civil_quando_eleitoral_ausente(self):
        from pipeline.camara.transform import construir_silver_parlamentar

        df = construir_silver_parlamentar(
            _df_bronze_parlamentar(nome_eleitoral=[None])
        )
        assert df.loc[0, "nome"] == "ANA BEATRIZ OLIVEIRA"

    def test_vazio_retorna_schema(self):
        from pipeline.camara.transform import (
            COLUNAS_SILVER_PARLAMENTAR,
            construir_silver_parlamentar,
        )

        df = construir_silver_parlamentar(pd.DataFrame(columns=["id_deputado"]))
        assert df.empty
        assert list(df.columns) == COLUNAS_SILVER_PARLAMENTAR


class TestCarregarParlamentarCamara:
    def _carregar(self, tmp_path, df_bronze):
        import pipeline.config as config

        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        storage = LocalParquetStorage(root)
        storage.write_file(Path("parlamento/camara"), df_bronze, "run-1.parquet")

        db_path = tmp_path / "silver.duckdb"
        config.load_env_settings.cache_clear()
        old = os.environ.get("DUCKDB_DATABASE_PATH")
        os.environ["DUCKDB_DATABASE_PATH"] = str(db_path)
        try:
            from pipeline.camara.transform import carregar_silver_parlamentar

            return carregar_silver_parlamentar(storage=storage, run_id="run-0001")
        finally:
            if old is None:
                os.environ.pop("DUCKDB_DATABASE_PATH", None)
            else:
                os.environ["DUCKDB_DATABASE_PATH"] = old
            config.load_env_settings.cache_clear()

    def test_carga_integrada_persiste(self, tmp_path):
        resultado = self._carregar(tmp_path, _df_bronze_parlamentar())

        assert resultado is not None
        assert len(resultado.aceitos) == 1
        assert resultado.quarentena.empty

        import duckdb

        con = duckdb.connect(str(tmp_path / "silver.duckdb"))
        try:
            linhas = con.execute(
                "select id_parlamentar, nome from silver_parlamentar"
            ).fetchall()
        finally:
            con.close()
        assert linhas == [(1, "ANA BEATRIZ")]

    def test_snapshots_diferentes_dias_nao_colapsam(self, tmp_path):
        df = pd.concat(
            [
                _df_bronze_parlamentar(data_status=["2026-08-06T00:00:00"]),
                _df_bronze_parlamentar(data_status=["2026-08-07T00:00:00"]),
            ],
            ignore_index=True,
        )
        resultado = self._carregar(tmp_path, df)
        assert len(resultado.aceitos) == 2

        resultado = self._carregar(tmp_path, df)
        assert resultado is not None
        assert len(resultado.aceitos) == 2

    def test_snapshot_mesmo_dia_colapsa(self, tmp_path):
        df = pd.concat(
            [
                _df_bronze_parlamentar(id_deputado=[1], nome_eleitoral=["ANA BEATRIZ"]),
                _df_bronze_parlamentar(id_deputado=[1], nome_eleitoral=["ANA B. SIQUEIRA"]),
            ],
            ignore_index=True,
        )
        df["data_status"] = ["2026-08-07T00:00:00"] * len(df)
        resultado = self._carregar(tmp_path, df)
        assert len(resultado.aceitos) == 1
        assert len(resultado.deduplicadas) == 1

    def test_data_futura_quarentenada(self, tmp_path):
        df = _df_bronze_parlamentar(data_status=["2030-01-01T00:00:00"])
        resultado = self._carregar(tmp_path, df)

        assert resultado is not None
        assert resultado.aceitos.empty
        assert len(resultado.quarentena) == 1

    def test_bronze_vazio_retorna_none(self, tmp_path):
        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        from pipeline.camara.transform import carregar_silver_parlamentar

        assert carregar_silver_parlamentar(LocalParquetStorage(root), "run-0001") is None