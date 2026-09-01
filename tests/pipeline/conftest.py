"""Fixtures compartilhadas para testes pipeline Gold.

Reseta o cache de conexão do dbt-duckdb (DuckDBConnectionManager._ENV)
antes de cada teste para evitar que o adaptador reutilize uma conexão de um
arquivo DuckDB diferente (reflexo do problema ADR-042/Sprint 14).

Também configura search_path='gold' para conexões diretas ao DuckDB nos
testes de verificação (ADR-042: Gold vive no schema 'gold')."""

import duckdb
import pytest

from pipeline.config import load_pipeline_settings, load_sources_settings


@pytest.fixture(autouse=True)
def _reset_duckdb_env():
    """Força o dbt-duckdb a reabrir o arquivo DuckDB a cada teste."""
    from dbt.adapters.duckdb.connections import DuckDBConnectionManager

    DuckDBConnectionManager._ENV = None
    yield
    DuckDBConnectionManager._ENV = None


@pytest.fixture(autouse=True)
def _gold_search_path(monkeypatch):
    """Intercepta duckdb.connect para setar search_path='gold' em conexões de teste."""
    _orig = duckdb.connect

    def _patched_connect(db_or_conn=None, *args, **kwargs):
        con = _orig(db_or_conn, *args, **kwargs) if db_or_conn is not None else _orig(*args, **kwargs)
        # Seta search_path só para arquivos .duckdb (não :memory:)
        if db_or_conn and not str(db_or_conn).startswith(":"):
            try:
                con.execute("SET search_path = 'gold'")
            except Exception:
                pass
        return con

    monkeypatch.setattr(duckdb, "connect", _patched_connect)


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Reset lru_cache for pipeline config between tests.

    get_pipeline() and get_sources() are @lru_cache(maxsize=1). Tests that
    monkeypatch config sources or pipeline settings must not leak state.
    """
    yield
    load_pipeline_settings.cache_clear()
    load_sources_settings.cache_clear()
