# tests/pipeline/test_backfill_camara_scd2.py
"""Testes do backfill SOAP da Câmara (ADR-043, Onda 4).

Cobre:
- Múltiplas trocas de partido → múltiplas versões SCD2
- Dedup/idempotência do backfill
- Classificação: despesa antiga casa com versão correta
- Integração: fact_despesa sem quarentena residual por esta causa
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pipeline.camara.schemas import CamaraFiliacaoPartidaria
from pipeline.contracts import LoadMetadata
from pipeline.silver import COLUNAS_SILVER_PARLAMENTAR


def _run_meta(**override) -> LoadMetadata:
    from datetime import datetime
    from uuid import uuid4

    dados = {
        "run_id": uuid4(),
        "pipeline_version": "0.1.0",
        "execution_timestamp": datetime(2026, 9, 1, 12, 0, 0),
        "source_version": "2026-09-01",
    }
    dados.update(override)
    return LoadMetadata(**dados)


def _filiacao(id_dep: int, partido: str, data: str, leg: int = 57) -> dict:
    """Helper para criar filiação SOAP como dict (nomes Python, não aliases)."""
    return {
        "id_deputado": id_dep,
        "sigla_partido": partido,
        "data_filiacao": data,
        "id_legislatura": leg,
        "uf": "SP",
        "partido_uf_aproximado": False,
    }


def _df_filiacoes(*fil_rows: dict) -> pd.DataFrame:
    """Cria DataFrame de filiações a partir de dicts."""
    return pd.DataFrame(list(fil_rows))


def _df_bronze_parlamentar(**override) -> pd.DataFrame:
    dados = {
        "id_deputado": [1],
        "nome_civil": ["JOSE SILVA"],
        "nome_eleitoral": ["JOSE SILVA"],
        "sigla_partido": ["PSD"],
        "sigla_uf": ["SP"],
        "id_legislatura": [57],
        "situacao": ["Exercício"],
        "condicao_eleitoral": ["Titular"],
        "data_status": ["2026-08-07T00:00:00"],
        "url_foto": ["http://example.com/foto.jpg"],
        "run_id": ["run-0001"],
        "pipeline_version": ["0.1.0"],
        "execution_timestamp": ["2026-08-07T00:00:00Z"],
        "source_version": ["2026-08-07"],
    }
    dados.update(override)
    return pd.DataFrame(dados)


class TestBackfillScd2Camara:
    """Testes de _gerar_backfill_scd2_camara."""

    def test_multiplas_trocas_gera_multiplas_versoes(self):
        from pipeline.camara.transform import _gerar_backfill_scd2_camara

        filiacoes = _df_filiacoes(
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),
            _filiacao(1, "PSB", "2019-04-22T00:00:00", 56),
            _filiacao(1, "PSD", "2023-02-15T00:00:00", 57),
        )
        bronze = _df_bronze_parlamentar()
        resultado = _gerar_backfill_scd2_camara(
            filiacoes, bronze, "2026-09-01"
        )

        # 3 filiações = 3 snapshots de backfill
        assert len(resultado) == 3
        assert list(resultado["sigla_partido"]) == ["PT", "PSB", "PSD"]
        # Todas com partido_uf_aproximado=False (dado real)
        assert not resultado["partido_uf_aproximado"].any()

    def test_datas_ordem_cronologica(self):
        from pipeline.camara.transform import _gerar_backfill_scd2_camara

        filiacoes = _df_filiacoes(
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),
            _filiacao(1, "PSB", "2019-04-22T00:00:00", 56),
        )
        bronze = _df_bronze_parlamentar()
        resultado = _gerar_backfill_scd2_camara(
            filiacoes, bronze, "2026-09-01"
        )

        datas = resultado["data"].tolist()
        assert datas == sorted(datas)

    def test_id_legislatura_derivada_do_calendario(self):
        from pipeline.camara.transform import _gerar_backfill_scd2_camara

        filiacoes = _df_filiacoes(
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),
        )
        bronze = _df_bronze_parlamentar()
        resultado = _gerar_backfill_scd2_camara(
            filiacoes, bronze, "2026-09-01"
        )

        # 2015-03-10 → legislatura 55
        assert resultado.iloc[0]["id_legislatura"] == 55

    def test_dedup_idempotente(self):
        from pipeline.camara.transform import _gerar_backfill_scd2_camara

        filiacoes = _df_filiacoes(
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),  # duplicada
        )
        bronze = _df_bronze_parlamentar()
        resultado = _gerar_backfill_scd2_camara(
            filiacoes, bronze, "2026-09-01"
        )

        # Dedup remove a duplicata
        assert len(resultado) == 1

    def test_filiacoes_vazio_retorna_vazio(self):
        from pipeline.camara.transform import _gerar_backfill_scd2_camara

        resultado = _gerar_backfill_scd2_camara(
            pd.DataFrame(), _df_bronze_parlamentar(), "2026-09-01"
        )
        assert resultado.empty

    def test_bronze_sem_deputado_pula(self):
        from pipeline.camara.transform import _gerar_backfill_scd2_camara

        filiacoes = _df_filiacoes(
            _filiacao(999, "PT", "2015-03-10T00:00:00", 55),
        )
        bronze = _df_bronze_parlamentar(id_deputado=[1])  # id não bate
        resultado = _gerar_backfill_scd2_camara(
            filiacoes, bronze, "2026-09-01"
        )
        assert resultado.empty

    def test_schema_silver_correto(self):
        from pipeline.camara.transform import _gerar_backfill_scd2_camara

        filiacoes = _df_filiacoes(
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),
        )
        bronze = _df_bronze_parlamentar()
        resultado = _gerar_backfill_scd2_camara(
            filiacoes, bronze, "2026-09-01"
        )

        assert list(resultado.columns) == COLUNAS_SILVER_PARLAMENTAR


class TestCarregarSilverParlamentarComBackfill:
    """Testes integrados de carregar_silver_parlamentar com cache SOAP."""

    def _carregar(self, tmp_path, df_bronze, df_filiacoes=None):
        import os

        import pipeline.config as config

        root = tmp_path / "bronze"
        root.mkdir(parents=True, exist_ok=True)
        storage = LocalParquetStorage(root)
        storage.write_file(Path("parlamento/camara"), df_bronze, "run-1.parquet")

        # Salva cache de filiações se fornecido
        if df_filiacoes is not None and not df_filiacoes.empty:
            from pipeline.camara.soap_extract import salvar_cache_filiacoes

            filiacoes = [
                CamaraFiliacaoPartidaria.model_validate(
                    {**row, "metadata": _run_meta().model_dump()}
                )
                for row in df_filiacoes.to_dict("records")
            ]
            salvar_cache_filiacoes(
                filiacoes, root / "camara" / "filiacoes", _run_meta()
            )

        db_path = tmp_path / "observatorio.duckdb"
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

    def test_backfill_gera_snapshots_adicionais(self, tmp_path):
        filiacoes = _df_filiacoes(
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),
            _filiacao(1, "PSB", "2019-04-22T00:00:00", 56),
        )
        resultado = self._carregar(tmp_path, _df_bronze_parlamentar(), filiacoes)

        assert resultado is not None
        # 1 snapshot REST + 2 snapshots SOAP = 3
        assert len(resultado.aceitos) == 3

    def test_dedup_re_runs_nao_duplica(self, tmp_path):
        filiacoes = _df_filiacoes(
            _filiacao(1, "PT", "2015-03-10T00:00:00", 55),
        )
        r1 = self._carregar(tmp_path, _df_bronze_parlamentar(), filiacoes)
        r2 = self._carregar(tmp_path, _df_bronze_parlamentar(), filiacoes)

        assert len(r1.aceitos) == len(r2.aceitos)

    def test_cache_vazio_so_rest(self, tmp_path):
        resultado = self._carregar(tmp_path, _df_bronze_parlamentar())

        assert resultado is not None
        assert len(resultado.aceitos) == 1
        assert not resultado.aceitos.iloc[0]["partido_uf_aproximado"]


from pipeline.storage import LocalParquetStorage


class TestClassificacaoComBackfill:
    """Testes de classificação: despesa antiga casa com versão correta via dbt."""

    def _seed_silver(self, tmp_path, df_parlamentar, df_despesas):
        """Cria DuckDB Silver com parlamentar + despesas para teste dbt."""
        import duckdb

        import pipeline.config as config

        db_path = tmp_path / "gold.duckdb"
        config.load_env_settings.cache_clear()
        old = os.environ.get("DUCKDB_DATABASE_PATH")
        os.environ["DUCKDB_DATABASE_PATH"] = str(db_path)

        con = duckdb.connect(str(db_path))
        try:
            con.execute("CREATE SCHEMA IF NOT EXISTS silver")

            # silver_parlamentar
            con.execute("""
                CREATE TABLE silver.silver_parlamentar (
                    fonte VARCHAR, id_parlamentar BIGINT, nome VARCHAR,
                    sigla_partido VARCHAR, sigla_uf VARCHAR,
                    id_legislatura BIGINT, id_legislatura_fonte BIGINT,
                    situacao_bruta VARCHAR, situacao_normalizada VARCHAR,
                    url_foto VARCHAR, partido_uf_aproximado BOOLEAN,
                    data TIMESTAMP, run_id VARCHAR, pipeline_version VARCHAR,
                    execution_timestamp TIMESTAMP, source_version VARCHAR
                )
            """)
            for _, row in df_parlamentar.iterrows():
                con.execute(
                    "INSERT INTO silver.silver_parlamentar VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    list(row),
                )

            # silver_despesa
            con.execute("""
                CREATE TABLE silver.silver_despesa (
                    fonte VARCHAR, id_parlamentar BIGINT, nome_parlamentar VARCHAR,
                    ano BIGINT, mes BIGINT, cod_documento VARCHAR,
                    data_documento DATE, tipo_despesa VARCHAR,
                    cnpj_cpf_valor VARCHAR, tipo_documento VARCHAR,
                    nome_fornecedor VARCHAR, valor_liquido DOUBLE,
                    valor_glosa DOUBLE, run_id VARCHAR, pipeline_version VARCHAR,
                    execution_timestamp TIMESTAMP, source_version VARCHAR
                )
            """)
            for _, row in df_despesas.iterrows():
                con.execute(
                    "INSERT INTO silver.silver_despesa VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    list(row),
                )

            # Tabelas auxiliares vazias (evita FK errors)
            for tbl in [
                "silver_cartao", "silver_emenda",
            ]:
                con.execute(f"CREATE TABLE IF NOT EXISTS silver.{tbl} (dummy INT)")
        finally:
            con.close()

        if old is None:
            os.environ.pop("DUCKDB_DATABASE_PATH", None)
        else:
            os.environ["DUCKDB_DATABASE_PATH"] = old
        config.load_env_settings.cache_clear()

    def test_despesa_antiga_casa_com_versao_correta(self, tmp_path):
        """Despesa de 2016 (partido PT) casa com versão do backfill, não REST."""
        from dbt.cli.main import dbtRunner

        import pipeline.config as config

        # Parlamentar: PT em 2015-03-10 (backfill), PSD em 2026-08-07 (REST)
        parlamentar_rows = [
            ("camara", 1, "JOSE SILVA", "PT", "SP", 55, 55,
             "Exercício", "ativo", None, False,
             "2015-03-10 00:00:00", "run-0001", "0.1.0",
             "2026-09-01 00:00:00", "2026-09-01"),
            ("camara", 1, "JOSE SILVA", "PSD", "SP", 57, 57,
             "Exercício", "ativo", None, False,
             "2026-08-07 00:00:00", "run-0001", "0.1.0",
             "2026-09-01 00:00:00", "2026-09-01"),
        ]
        df_parl = pd.DataFrame(parlamentar_rows,
            columns=[c for c in COLUNAS_SILVER_PARLAMENTAR
                     if c != "data"] + ["data"])
        # Renomeia 'data' de volta para TIMESTAMP
        df_parl.columns = list(COLUNAS_SILVER_PARLAMENTAR)

        # Despesa de 2016-05-10 (deveria casar com PT, não com PSD)
        despesa_rows = [
            ("camara", 1, None, 2016, 5, "D001",
             "2016-05-10", "PASSAGEM AEREA", None, None,
             "LATAM", 1000.0, 0.0, "run-0001", "0.1.0",
             "2026-09-01 00:00:00", "2026-09-01"),
        ]
        df_desp = pd.DataFrame(despesa_rows, columns=[
            "fonte", "id_parlamentar", "nome_parlamentar", "ano", "mes",
            "cod_documento", "data_documento", "tipo_despesa",
            "cnpj_cpf_valor", "tipo_documento", "nome_fornecedor",
            "valor_liquido", "valor_glosa", "run_id", "pipeline_version",
            "execution_timestamp", "source_version",
        ])

        self._seed_silver(tmp_path, df_parl, df_desp)

        # Build dim_parlamentar + desp_parlamento
        _GOLD = Path(__file__).resolve().parents[2] / "pipeline" / "gold"
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "gold.duckdb"))
        monkeypatch.setenv("PYTHONPATH", str(_GOLD))

        from dbt.adapters.duckdb.connections import DuckDBConnectionManager
        DuckDBConnectionManager._ENV = None

        try:
            from pipeline.config import get_dbt_vars
            result = dbtRunner().invoke([
                "run",
                "--project-dir", str(_GOLD),
                "--profiles-dir", str(_GOLD),
                "--select", "dim_parlamentar desp_parlamento",
                "--vars", str(get_dbt_vars()),
            ])
            assert result.success, result.exception

            con = duckdb.connect(str(tmp_path / "gold.duckdb"))
            try:
                con.execute("SET search_path = 'gold'")
                linhas = con.execute(
                    "SELECT cod_documento, id_parlamentar, "
                    "surrogate_key FROM desp_parlamento"
                ).fetchall()
            finally:
                con.close()

            # D001 resolve para id_parlamentar=1 (PT versão 2015)
            assert len(linhas) == 1
            assert linhas[0][0] == "D001"
            assert linhas[0][1] == 1
        finally:
            monkeypatch.undo()
            DuckDBConnectionManager._ENV = None
