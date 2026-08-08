# tests/pipeline/test_transform_senado.py
"""Testes do transform Bronze → Silver do Senado (ADR-023, Trilha B)."""

from __future__ import annotations

import pandas as pd
from decimal import Decimal
from pathlib import Path

from pipeline.normalize import normalizar_nome_proprio, parse_decimal_ptbr
from pipeline.senado.transform import COLUNAS_SILVER, construir_silver
from pipeline.storage import LocalParquetStorage


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


def _df_bronze_parlamentar(**override) -> pd.DataFrame:
    dados = {
        "id_senador": [5672],
        "nome_parlamentar": ["ALAN RICK"],
        "nome_completo": ["ALAN RICK MIRANDA"],
        "sigla_partido": ["REPUBLICANOS"],
        "sigla_uf": ["AC"],
        "id_legislatura": [58],
        "situacao": ["Titular"],
        "data_status": ["2026-08-07T00:00:00"],
        "run_id": ["run-0001"],
        "pipeline_version": ["0.1.0"],
        "execution_timestamp": ["2026-08-07T00:00:00Z"],
        "source_version": ["2026-08-07"],
    }
    dados.update(override or {})
    return pd.DataFrame(dados)


class TestConstruirParlamentarSenado:
    def test_mapeamento_canonico(self):
        from pipeline.senado.transform import (
            COLUNAS_SILVER_PARLAMENTAR,
            construir_silver_parlamentar,
        )

        df = construir_silver_parlamentar(_df_bronze_parlamentar())

        assert list(df.columns) == COLUNAS_SILVER_PARLAMENTAR
        assert df.loc[0, "fonte"] == "senado"
        assert df.loc[0, "id_parlamentar"] == 5672
        assert df.loc[0, "nome"] == "ALAN RICK"
        assert df.loc[0, "sigla_partido"] == "REPUBLICANOS"
        assert df.loc[0, "sigla_uf"] == "AC"
        assert df.loc[0, "id_legislatura"] == 57  # derivada do calendário (2026-08-07)
        assert df.loc[0, "id_legislatura_fonte"] == 58  # primeira legislação do mandato
        assert df.loc[0, "situacao_bruta"] == "Titular"
        assert df.loc[0, "situacao_normalizada"] == "ativo"
        assert str(df.loc[0, "data"])[:10] == "2026-08-07"

    def test_legislatura_bruta_zero_nao_e_a_regra_de_negocio(self):
        # ADR-024: a API pode entregar 0 (sem campo); a Silver deriva do
        # calendário e isola o 0 do bruto em `id_legislatura_fonte`.
        from pipeline.senado.transform import construir_silver_parlamentar

        df = construir_silver_parlamentar(
            _df_bronze_parlamentar(id_legislatura=[0])
        )
        assert df.loc[0, "id_legislatura"] == 57
        assert df.loc[0, "id_legislatura_fonte"] == 0

    def test_situacao_desconhecida_vira_sentinela(self):
        from pipeline.senado.transform import construir_silver_parlamentar

        df = construir_silver_parlamentar(
            _df_bronze_parlamentar(situacao=["Inventada"])
        )
        assert df.loc[0, "situacao_bruta"] == "Inventada"
        assert df.loc[0, "situacao_normalizada"] == "nao_mapeado"

    def test_nome_recai_no_completo_quando_parlamentar_ausente(self):
        from pipeline.senado.transform import construir_silver_parlamentar

        df = construir_silver_parlamentar(
            _df_bronze_parlamentar(nome_parlamentar=[None])
        )
        assert df.loc[0, "nome"] == "ALAN RICK MIRANDA"

    def test_vazio_retorna_schema(self):
        from pipeline.senado.transform import (
            COLUNAS_SILVER_PARLAMENTAR,
            construir_silver_parlamentar,
        )

        df = construir_silver_parlamentar(pd.DataFrame(columns=["id_senador"]))
        assert df.empty
        assert list(df.columns) == COLUNAS_SILVER_PARLAMENTAR


class TestCarregarParlamentarSenado:
    def _carregar(self, tmp_path, df_bronze):
        import os

        import pipeline.config as config

        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        storage = LocalParquetStorage(root)
        storage.write_file(Path("parlamento/senado"), df_bronze, "run-1.parquet")

        db_path = tmp_path / "silver.duckdb"
        config.load_env_settings.cache_clear()
        old = os.environ.get("DUCKDB_DATABASE_PATH")
        os.environ["DUCKDB_DATABASE_PATH"] = str(db_path)
        try:
            from pipeline.senado.transform import carregar_silver_parlamentar

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
        assert linhas == [(5672, "ALAN RICK")]

    def test_bronze_vazio_retorna_none(self, tmp_path):
        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        from pipeline.senado.transform import carregar_silver_parlamentar

        assert carregar_silver_parlamentar(LocalParquetStorage(root), "run-0001") is None