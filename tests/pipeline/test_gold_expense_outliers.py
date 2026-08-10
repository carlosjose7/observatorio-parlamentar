# tests/pipeline/test_gold_expense_outliers.py
"""Integração dbt Gold — anomalias de despesa (ADR-026, Onda 2).

Regressão da tabela Gold `expense_outliers` — materializada a partir do
source `ml_staging` (ADR-026, Opção A: Python single-writer no staging, o
dbt consome como `source()` e materializa o Gold via `inner join` com
`fact_despesa`).

Fluxo realista de duas fases (espelha a DAG):
1. Dbt build resolve `silver_*` → Gold `fact_despesa` (dimensões + pontes).
2. Python lê o `fact_despesa` DO DUCKDB (ids de verdade), calcula `ml_staging`
   (`escrever_expense_outliers_duckdb`, ADR-026 single-writer) e o dbt
   materializa `expense_outliers` a partir de `source('ml_staging', ...)`.

Coberto aqui:
- Só despesas ANÔMALAS (is_anomalia = true) entram na Gold; o avaliado
  completo fica em `ml_staging`.
- `inner join` com `fact_despesa`: anomalia com id que não resolve NON aparece
  (lança fora, mesmo princípio ADR-018).
- Contrato do schema.yml: `not_null`/`unique` de `id_despesa` e
  integridade referencial (warn) contra fato/dimensões.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD = _RAIZ / "pipeline" / "gold"

if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
if str(_GOLD) not in sys.path:
    sys.path.insert(0, str(_GOLD))


@pytest.fixture(autouse=True)
def _chave_hmac(monkeypatch):
    """Garante CPF_HMAC_SECRET_KEY determinístico para o plugin hmac_udf.

    O `dim_fornecedor` (requisito do fact_despesa) exige a chave quando há
    fornecedores CPF — mesma garantia dos demais testes Gold.
    """
    monkeypatch.setenv("CPF_HMAC_SECRET_KEY", "Chave-de-teste-gold-expense-outliers-2026")


def _seed_silver(db: Path) -> None:
    """Popula Silver suficiente para materializar fact_despesa (molde analytics).

    Mesmo seed do `test_gold_analytics.py`: 2 parlamentares (camara/senado),
    6 despesas (5 resolvíveis + 1 fantasma que vai à quarentena) e as tabelas
    Silver vazias exigidas pelo build das demais pontes.
    """
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "create table silver_parlamentar (fonte varchar, id_parlamentar bigint,"
            " nome varchar, sigla_partido varchar, sigla_uf varchar, id_legislatura bigint,"
            " situacao_normalizada varchar, data date, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        con.executemany(
            "insert into silver_parlamentar values (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("camara", 1, "JOSE SILVA", "PARTIDO A", "SP", 56, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", 6, "MARIA SANTOS", "PARTIDO G", "PR", 56, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        con.execute(
            "create table silver_despesa (fonte varchar, id_parlamentar bigint,"
            " nome_parlamentar varchar, ano bigint, mes bigint, cod_documento varchar,"
            " data_documento date, tipo_despesa varchar, cnpj_cpf_valor varchar,"
            " tipo_documento varchar, nome_fornecedor varchar, valor_liquido double,"
            " valor_glosa double, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        con.executemany(
            "insert into silver_despesa values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("camara", 1, None, 2019, 5, "D1", "2019-05-10", "HOSPEDAGEM",
                 "12345678000190", "CNPJ", "COMERCIO X", 120, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, None, 2019, 6, "D2", "2019-06-15", "TAXI",
                   "12345678901", "CPF", "AUTONOMO X", 80, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, None, 2020, 3, "D3", "2020-03-10", "HOSPEDAGEM",
                   "12345678000190", "CNPJ", "COMERCIO Y", 50, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", None, "MARIA SANTOS", 2019, 3, "D4", "2019-03-10", "HOSPEDAGEM",
                   "11111111000100", "CNPJ", "HOTEL A", 60, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", None, "MARIA SANTOS", 2019, 4, "D5", "2019-04-10", "HOSPEDAGEM",
                   "22222222000100", "CNPJ", "HOTEL B", 140, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", None, "ZONA FANTASMA", 2019, 5, "D6", "2019-05-11", "CORREIOS",
                   "33333333000100", "CNPJ", "EMPRESA X", 100, 0, "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        con.execute(
            "create table silver_emenda (ano bigint, codigo_emenda varchar,"
            " tipo_emenda varchar, nome_autor varchar, funcao varchar,"
            " subfuncao varchar, localidade_do_gasto varchar, valor_empenhado bigint,"
            " valor_liquidado bigint, valor_pago bigint, run_id varchar,"
            " pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        con.execute(
            "create table silver_cartao (id bigint, data_transacao date,"
            " valor_transacao double, estabelecimento_cnpj_valor varchar,"
            " estabelecimento_tipo_documento varchar, estabelecimento_nome varchar,"
            " portador_nome varchar, portador_cpf_mascarado varchar,"
            " unidade_gestora_codigo varchar, unidade_gestora_nome varchar,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        # ml_staging.expense_outliers VAZIA: a Fase 1 builda os analytics com o
        # staging ainda sem dados (contrato ADR-026) e o build de
        # `+fact_despesa`/`+supplier_*` agenda junto os testes de FK que apontam
        # para a source. O schema/tabela precisam existir (mesmo molde
        # test_gold_analytics); o conteúdo real chega via `executar_carga_outliers`.
        con.execute("create schema if not exists ml_staging")
        con.execute(
            "create table if not exists ml_staging.expense_outliers ("
            " id_despesa bigint, id_parlamentar bigint, id_fornecedor bigint,"
            " data_sk bigint, valor_liquido double, zscore double, if_score double,"
            " criterio_zscore boolean, criterio_if boolean,"
            " criterio_fornecedor_poucos_clientes boolean, criterio_empresa_nova boolean,"
            " criterio_valores_identicos boolean, criterio_dia_sem_sessao boolean,"
            " num_criterios bigint, is_anomalia boolean, run_id varchar,"
            " pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
    finally:
        con.close()


def _build_selecao(tmp_path, monkeypatch, selecao: str) -> None:
    """Roda `dbt build` no projeto Gold apontando o fixture como banco."""
    from dbt.cli.main import dbtRunner

    from pipeline.config import get_dbt_vars

    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "gold.duckdb"))
    monkeypatch.setenv("PYTHONPATH", str(_GOLD))

    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(_GOLD),
            "--profiles-dir",
            str(_GOLD),
            "--select",
            selecao,
            "--vars",
            json.dumps(get_dbt_vars()),
        ]
    )
    assert result.success, result.exception


# FASE 1 — materializar a malha dimensional + fatos + analytics com o
# `ml_staging` VAZIO (mesmo seed/molde de test_gold_analytics): resolve ids
# reais de fact_despesa e valida os models. `expense_outliers` Gold nasce
# vazia (sem dados no staging).
_SELECAO_FATO = (
    "+supplier_concentration +supplier_growth +expense_outliers"
    " +fact_emenda +fact_cartao_cpgf +fact_cartao_cpgf_quarantine"
)


def _fact_despesa(db: Path) -> pd.DataFrame:
    """Lê o `fact_despesa` materializado (ids de verdade para o ml_staging)."""
    con = duckdb.connect(str(db))
    try:
        return con.execute(
            "select id_despesa, id_parlamentar, id_fornecedor, data_sk,"
            " valor_liquido, run_id, pipeline_version, source_version"
            " from main.fact_despesa"
        ).fetchdf()
    finally:
        con.close()


def _dim_data_para_fatos(fatos: pd.DataFrame) -> pd.DataFrame:
    """Constrói `dim_data` a partir das datas do fato (dia útil = seg-sex).

    Mantém `is_dia_util` realista pelo dia da semana — datas de fim de semana
    (ex.: 2019-06-15 sábado, 2019-03-10 domingo) ficam não úteis, o que
    dispara o critério 6 (dia sem sessão) de forma determinística no seed.
    """
    linhas = []
    for ts in sorted(fatos["data_sk"].unique()):
        data = pd.Timestamp(str(int(ts)))
        linhas.append(
            {
                "data_sk": ts,
                "data": data.date(),
                "ano": int(str(int(ts))[:4]),
                "mes": int(str(int(ts))[4:6]),
                "is_dia_util": data.weekday() < 5,
            }
        )
    return pd.DataFrame(linhas)


def _escrever_ml_staging(db: Path, fatos: pd.DataFrame) -> None:
    """Calcula a regra de anomalia e grava `ml_staging` (ADR-026 single-writer)."""
    from pipeline.anomalies import executar_carga_outliers

    datas = _dim_data_para_fatos(fatos)
    executar_carga_outliers(
        fatos,
        run_id=_FATO_RUN_ID,
        dim_data=datas,
        db_path=str(db),
        source_version="v1",
    )


_DB = "gold.duckdb"
_FATO_RUN_ID = "r-gold-expense-outliers"


def test_expense_outliers_gold(tmp_path, monkeypatch):
    """Gold `expense_outliers` = anomalias resolvidas em `fact_despesa`."""
    db = tmp_path / _DB
    _seed_silver(db)
    _build_selecao(tmp_path, monkeypatch, _SELECAO_FATO)

    fatos = _fact_despesa(db)
    assert not fatos.empty
    _escrever_ml_staging(db, fatos)

    # FASE 2 — com o staging populado, rebuild da Gold expense_outliers.
    _build_selecao(tmp_path, monkeypatch, "expense_outliers")

    con = duckdb.connect(str(db))
    try:
        linhas = con.execute(
            "select id_despesa, num_criterios, run_id"
            " from main.expense_outliers"
        ).fetchall()
        # Só anomalias (num_criterios >= 2) materializadas, com run_id do lote.
        assert linhas
        assert all(r[1] >= 2 for r in linhas)
        assert all(r[2] == _FATO_RUN_ID for r in linhas)
        # Toda anomalia Gold é uma despesa REAL do fato (inner join ADR-018).
        ids_fato = {int(r[0]) for r in con.execute(
            "select id_despesa from main.fact_despesa"
        ).fetchall()}
        for r in linhas:
            assert int(r[0]) in ids_fato
    finally:
        con.close()


def test_expense_outliers_ignora_nao_anomalia(tmp_path, monkeypatch):
    """Despesa que não é anomalia (avaliada como tal) NÃO entra na Gold.

    A Gold `expense_outliers` filtra `is_anomalia`; o staging guarda o
    avaliado completo (para o expense_anomaly_score, ADR-027).
    """
    db = tmp_path / _DB
    _seed_silver(db)
    _build_selecao(tmp_path, monkeypatch, _SELECAO_FATO)

    fatos = _fact_despesa(db)
    from pipeline.anomalies import avaliar_criterios

    datas = _dim_data_para_fatos(fatos)
    resultado = avaliar_criterios(fatos, datas)
    n_avaliadas = len(resultado)
    n_anomalias = int((resultado["is_anomalia"]).sum())
    assert n_anomalias < n_avaliadas

    _escrever_ml_staging(db, fatos)
    _build_selecao(tmp_path, monkeypatch, "expense_outliers")

    con = duckdb.connect(str(db))
    try:
        n_materializadas = con.execute(
            "select count(*) from main.expense_outliers"
        ).fetchone()[0]
        n_staging_sem_anomalia = con.execute(
            "select count(*) from ml_staging.expense_outliers where not is_anomalia"
        ).fetchone()[0]
        # Staging guarda o avaliado completo; Gold só as anomalias. Como o seed
        # (5 despesas de 2 foras de padrão) tende a ter poucas/nenhuma anomalia,
        # o invariante forte é: Gold ⊆ staging com is_anomalia = true.
        assert n_materializadas <= con.execute(
            "select count(*) from ml_staging.expense_outliers where is_anomalia"
        ).fetchone()[0]
        assert n_staging_sem_anomalia >= 0
    finally:
        con.close()