# tests/pipeline/test_gold_scd2_adr017.py
"""Integração dbt Gold — `dim_parlamentar` SCD Type 2 + resolução de autor (ADR-017).

Regressão da Onda 2 (BACKLOG.md): a dimensão SCD2 (ADR-020) e o mecanismo de
resolução de autor de emenda (ADR-017) são modelos Gold e são exercitados de
verdade aqui (dbtRunner invocado por teste), não apenas compilados.

Este teste cria um DuckDB temporário com `silver_parlamentar` + `silver_emenda`
realistas, roda `dbt build` nos modelos correspondentes e confere:

- SCD2: mudança de partido abre nova versão com `end_date` na data as-of
  seguinte e `is_current` só na última.
- ADR-017: `autor_resolvido` (casa a versão vigente no ano da emenda),
  `autor_colegiado`, `autor_ambiguo`, `autor_fora_cobertura` e
  `autor_nao_resolvido` — cada status observável na saída.

Segue PROJECT_CONTEXT §15: nenhum `except` silencioso — erro do dbt derruba
o teste (assert result.success).
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD = _RAIZ / "pipeline" / "gold"

if str(_GOLD) not in sys.path:
    sys.path.insert(0, str(_GOLD))


def _seed(db: Path) -> None:
    """Popula as Silver exigidas pelos modelos Gold alvo."""
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "create table silver_parlamentar (fonte varchar, id_parlamentar bigint, nome varchar,"
            " sigla_partido varchar, sigla_uf varchar, id_legislatura bigint,"
            " situacao_normalizada varchar, data date, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        con.execute(
            "create table silver_emenda (ano bigint, codigo_emenda varchar, tipo_emenda varchar,"
            " nome_autor varchar, funcao varchar, subfuncao varchar, localidade_do_gasto varchar,"
            " valor_empenhado bigint, valor_liquidado bigint, valor_pago bigint,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        con.executemany(
            "insert into silver_parlamentar values (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # JOSE SILVA troca de partido em 2019 — vira versão nova
                ("camara", 1, "JOSE SILVA", "PARTIDO A", "SP", 55, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, "JOSE SILVA", "PARTIDO B", "SP", 56, "Ativo", "2019-07-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, "JOSE SILVA", "PARTIDO B", "SP", 57, "Ativo", "2023-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                # PEDRO só vigente a partir de 2020 (emenda de 2019 → fora de cobertura)
                ("camara", 2, "PEDRO ALVES", "PARTIDO C", "RJ", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                # homônimos em casas distintas, vigentes em 2020
                ("camara", 3, "JOAO DO NORTE", "PARTIDO D", "PA", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", 4, "JOAO DO NORTE", "PARTIDO E", "AM", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        con.executemany(
            "insert into silver_emenda values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # E1: resolvido — JOSE SILVA tem versão vigente em 2019
                (2019, "E1", "Emenda Individual - Transferências", "JOSE SILVA", "0", "0", "l", 100, 0, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # E2: colegiado (bancada)
                (2020, "E2", "Emenda de Bancada", "BANCADA DO NORTE", "0", "0", "l", 200, 0, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # E3: não resolvido — nome fora do cadastro
                (2019, "E3", "Emenda Individual", "YOSH TECH", "0", "0", "l", 300, 0, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # E4: fora de cobertura — PEDRO só vigente a partir de 2020
                (2019, "E4", "Emenda Individual - Transferências", "PEDRO ALVES", "0", "0", "l", 400, 0, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # E5: ambíguo — dois JOAO DO NORTE vigentes em 2020
                (2020, "E5", "Emenda Individual - Transferências", "JOAO DO NORTE", "0", "0", "l", 500, 0, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # E6: colegiado comissão (acento: macro normaliza antes do match)
                (2020, "E6", "Emenda de Comissão", "COMISSAO DE SAUDE", "0", "0", "l", 600, 0, 0, "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
    finally:
        con.close()


def _conectar(db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db))


def _build(tmp_path, monkeypatch, selecao: str) -> None:
    """Roda `dbt build` no projeto Gold apontando DUCKDB_DATABASE_PATH pro fixture."""
    from dbt.cli.main import dbtRunner

    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "gold.duckdb"))
    monkeypatch.setenv("PYTHONPATH", str(_GOLD))

    result = dbtRunner().invoke(
        ["build", "--project-dir", str(_GOLD), "--profiles-dir", str(_GOLD), "--select", selecao]
    )
    assert result.success, result.exception


def test_scd2_dim_parlamentar(tmp_path, monkeypatch):
    """SCD2: troca de partido abre nova versão; end_date na data as-of."""
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, "dim_parlamentar")

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        linhas = con.execute(
            "select fonte, id_parlamentar, sigla_partido, strftime(effective_date, '%Y-%m-%d'),"
            " strftime(end_date, '%Y-%m-%d'), is_current "
            "from main.dim_parlamentar order by fonte, id_parlamentar, effective_date"
        ).fetchall()
        chaves = con.execute("select surrogate_key from main.dim_parlamentar").fetchall()
    finally:
        con.close()

    assert ("camara", 1, "PARTIDO A", "2019-02-01", "2019-07-01", False) in linhas
    assert ("camara", 1, "PARTIDO B", "2019-07-01", None, True) in linhas
    assert ("camara", 2, "PARTIDO C", "2020-02-01", None, True) in linhas
    numeros = sorted(k[0] for k in chaves)
    assert len(numeros) == len(set(numeros))
    assert 100000001001 in numeros and 100000001002 in numeros


def test_adr017_classificacao_completa(tmp_path, monkeypatch):
    """ADR-017: cinco status distintos na saída dos dois modelos."""
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, "dim_parlamentar emenda_autor emenda_autor_quarantine")

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        resolvidos = {
            cod for (cod,) in con.execute("select codigo_emenda from main.emenda_autor").fetchall()
        }
        quarentena = {
            (cod, motivo)
            for cod, motivo in con.execute(
                "select codigo_emenda, motivo from main.emenda_autor_quarantine"
            ).fetchall()
        }
    finally:
        con.close()

    assert resolvidos == {"E1"}
    assert ("E2", "autor_colegiado") in quarentena
    assert ("E3", "autor_nao_resolvido") in quarentena
    assert ("E4", "autor_fora_cobertura") in quarentena
    assert ("E5", "autor_ambiguo") in quarentena
    assert ("E6", "autor_colegiado") in quarentena


def test_emenda_autor_usa_versao_vigente_no_ano(tmp_path, monkeypatch):
    """E1 (emenda de 2019) casa a versão 1 (vigente em 2019), não a última."""
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, "dim_parlamentar emenda_autor")

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        row = con.execute(
            "select id_parlamentar, surrogate_key from main.emenda_autor where codigo_emenda = 'E1'"
        ).fetchone()
    finally:
        con.close()

    assert row == (1, 100000001001)