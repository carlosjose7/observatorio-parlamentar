# tests/pipeline/test_gold_network.py
"""Integração dbt Gold — grafo parlamentar↔fornecedor (ADR-030, Onda 3).

Regressão das Gold `network_edges`/`network_nodes`/`politician_similarity` —
materializadas a partir do source `ml_staging` (ADR-026, Opção A: Python
single-writer no staging, o dbt consome como `source()` e materializa o Gold
com `exists` contra as dimensões).

Fluxo realista de duas fases (espelha a DAG):
1. Dbt build resolve `silver_*` → Gold `fact_despesa` (dimensões + pontes).
2. Python lê o `fact_despesa` DO DUCKDB (ids de verdade), reconstrói o grafo
   bipartido por período e grava `ml_staging.network_*`
   (`executar_carga_ml_rede`, ADR-026 single-writer / ADR-030.1 recálculo
   total por `(run_id, periodo)`); o dbt então materializa as três Gold.

Coberto aqui:
- Arestas/nós/similaridades nascem só de parlamentar/fornecedor PROMOVIDOS em
  `fact_despesa` (quarentena não contamina; `exists` no model = ADR-018).
- Grão correto: edges `(id_parlamentar, id_fornecedor, periodo)`, nodes
  `(id_no, tipo_no, periodo)` com `pagerank`/`degree_centrality`/
  `comunidade_id`, similarity `(a, b, periodo)` com ordem canônica a < b.
- Contrato do schema.yml: `not_null`, `accepted_values` de `tipo_no` e
  integridade referencial (warn) contra dimensões.
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


from pipeline.pseudonymize import pseudonymize_cpf  # noqa: E402

_CHAVE_TESTE = "Chave-de-teste-gold-network-2026"
# CPF pseudonimizado na Silver (ADR-033): o seed do DuckDB carrega o HASH, não
# os dígitos — mesmo contrato do transform.py das fontes. O Gold repassa.
_CPF_HMAC = pseudonymize_cpf("12345678901", _CHAVE_TESTE.encode("utf-8"))


@pytest.fixture(autouse=True)
def _chave_hmac(monkeypatch):
    """Garante CPF_HMAC_SECRET_KEY determinístico (testes Silver e API).

    A pseudonimização na Silver (`pipeline/pseudonymize.py`) usa a chave do
    ambiente — mesma chave do `_CPF_HMAC` para que o hash dos testes seja
    exatamente o persistido pelo dbt quando há fornecedores CPF.
    """
    monkeypatch.setenv("CPF_HMAC_SECRET_KEY", _CHAVE_TESTE)


def _seed_silver(db: Path) -> None:
    """Popula Silver suficiente para materializar fact_despesa (molde analytics).

    Mesmo seed do `test_gold_analytics.py`/`test_gold_expense_outliers.py`:
    2 parlamentares (camara/senado), 6 despesas (5 resolvíveis + 1 fantasma
    que vai à quarentena) e as tabelas Silver vazias exigidas pelo build das
    demais pontes. Acrescenta as tabelas VAZIAS de `ml_staging.network_*`
    (contrato ADR-026/030 — a Fase 1 builda os analytics com o staging ainda
    sem dados e os testes de FK/built-in do schema.yml agendam junto as
    dimensões; o schema/tabela precisam existir).
    """
    con = duckdb.connect(str(db))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS silver")
        con.execute(
            "create table silver.silver_parlamentar (fonte varchar, id_parlamentar bigint,"
            " nome varchar, sigla_partido varchar, sigla_uf varchar, id_legislatura bigint,"
            " situacao_normalizada varchar, data date, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, url_foto varchar, source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_parlamentar values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("camara", 1, "JOSE SILVA", "PARTIDO A", "SP", 56, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", None, "s"),
                ("senado", 6, "MARIA SANTOS", "PARTIDO G", "PR", 56, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", None, "s"),
            ],
        )
        con.execute(
            "create table silver.silver_despesa (fonte varchar, id_parlamentar bigint,"
            " nome_parlamentar varchar, ano bigint, mes bigint, cod_documento varchar,"
            " data_documento date, tipo_despesa varchar, cnpj_cpf_valor varchar,"
            " tipo_documento varchar, nome_fornecedor varchar, valor_liquido double,"
            " valor_glosa double, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_despesa values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("camara", 1, None, 2019, 5, "D1", "2019-05-10", "HOSPEDAGEM",
                 "12345678000190", "CNPJ", "COMERCIO X", 120, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, None, 2019, 6, "D2", "2019-06-15", "TAXI",
                   _CPF_HMAC, "CPF", "AUTONOMO X", 80, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, None, 2020, 3, "D3", "2020-03-10", "HOSPEDAGEM",
                   "12345678000190", "CNPJ", "COMERCIO Y", 50, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", None, "MARIA SANTOS", 2019, 3, "D4", "2019-03-10", "HOSPEDAGEM",
                   "11111111000100", "CNPJ", "HOTEL A", 60, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", None, "MARIA SANTOS", 2019, 4, "D5", "2019-04-10", "HOSPEDAGEM",
                   "22222222000100", "CNPJ", "HOTEL B", 140, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D7: MARIA usa o MESMO CNPJ de JOSE (12345678000190) em 2019 —
                # cria sobreposição de fornecedor entre os dois (politician_similarity).
                ("senado", None, "MARIA SANTOS", 2019, 5, "D7", "2019-05-20", "HOSPEDAGEM",
                   "12345678000190", "CNPJ", "COMERCIO X", 30, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", None, "ZONA FANTASMA", 2019, 5, "D6", "2019-05-11", "CORREIOS",
                   "33333333000100", "CNPJ", "EMPRESA X", 100, 0, "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        con.execute(
            "create table silver.silver_emenda (ano bigint, codigo_emenda varchar,"
            " tipo_emenda varchar, nome_autor varchar, funcao varchar,"
            " subfuncao varchar, localidade_do_gasto varchar, valor_empenhado bigint,"
            " valor_liquidado bigint, valor_pago bigint, run_id varchar,"
            " pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        con.execute(
            "create table silver.silver_cartao (id bigint, data_transacao date,"
            " valor_transacao double, estabelecimento_cnpj_valor varchar,"
            " estabelecimento_tipo_documento varchar, estabelecimento_nome varchar,"
            " portador_nome varchar, portador_cpf_mascarado varchar,"
            " unidade_gestora_codigo varchar, unidade_gestora_nome varchar,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        # ml_staging VAZIA (contrato ADR-026/030): a Fase 1 builda os analytics
        # com o staging ainda sem dados e o build de `+fact_despesa`/`+supplier_*`
        # agenda junto os testes de FK/built-in das Onda 2/3 que apontam para as
        # sources — o schema/tabelas precisam existir mesmo quando o lote Python
        # ainda não gravou. O conteúdo real chega via `executar_carga_ml_rede`.
        con.execute("create schema if not exists ml_staging")
        con.execute(
            "create table if not exists ml_staging.network_edges ("
            " id_parlamentar bigint, id_fornecedor bigint, periodo bigint,"
            " valor_total double, run_id varchar, pipeline_version varchar,"
            " execution_timestamp varchar, source_version varchar)"
        )
        con.execute(
            "create table if not exists ml_staging.network_nodes ("
            " id_no bigint, tipo_no varchar, periodo bigint, pagerank double,"
            " degree_centrality double, comunidade_id bigint, run_id varchar,"
            " pipeline_version varchar, execution_timestamp varchar,"
            " source_version varchar)"
        )
        con.execute(
            "create table if not exists ml_staging.politician_similarity ("
            " id_parlamentar_a bigint, id_parlamentar_b bigint, periodo bigint,"
            " num_fornecedores_compartilhados bigint, similaridade double,"
            " run_id varchar, pipeline_version varchar, execution_timestamp varchar,"
            " source_version varchar)"
        )
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
        con.execute(
            "create table if not exists ml_staging.risk_scores ("
            " periodo bigint, id_parlamentar bigint,"
            " supplier_concentration_score double, political_exposure_score double,"
            " supplier_dependency_score double, expense_anomaly_score double,"
            " network_influence_score double, risk_index double,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
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

    from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    DuckDBConnectionManager._ENV = None

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


def _conectar(db: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db))
    con.execute("SET search_path = 'gold'")
    return con


# FASE 1 — materializar a malha dimensional + fatos + analytics com o
# `ml_staging` VAZIO (mesmo seed/molde de test_gold_analytics): resolve ids
# reais de fact_despesa e valida os models. As Gold network nascem vazias
# (sem dados no staging) — os testes de contrato passam no vazio.
_SELECAO_FATO = (
    "+network_edges +network_nodes +politician_similarity"
    " +supplier_concentration +supplier_growth +expense_outliers"
    " +risk_scores"
    " +fact_emenda +fact_cartao_cpgf +fact_cartao_cpgf_quarantine"
)


def _fact_despesa(db: Path) -> pd.DataFrame:
    """Lê o `fact_despesa` materializado (ids de verdade para o ml_staging)."""
    con = _conectar(db)
    try:
        return con.execute(
            "select id_despesa, id_parlamentar, id_fornecedor, data_sk,"
            " valor_liquido, run_id, pipeline_version, source_version"
            " from fact_despesa"
        ).fetchdf()
    finally:
        con.close()


def _escrever_ml_staging(db: Path, fatos: pd.DataFrame) -> None:
    """Reconstrói o grafo do run corrente e grava `ml_staging` (ADR-030.1)."""
    from analytics.network.network import executar_carga_ml_rede

    executar_carga_ml_rede(
        fatos,
        run_id=_FATO_RUN_ID,
        db_path=str(db),
        source_version="v1",
    )


_DB = "gold.duckdb"
_FATO_RUN_ID = "r-gold-network"


def test_network_gold_fluxo_duas_fases(tmp_path, monkeypatch):
    """Gold `network_*` nasce do fato promovido, por período e run.

    Após a Fase 2 (staging populado), as três Gold têm dados chaveados por
    `(run_id, periodo)`; toda aresta/nó/similaridade referencia parlamentar e
    fornecedor REAIS do `fact_despesa` (quarentena não contamina).
    """
    db = tmp_path / _DB
    _seed_silver(db)
    _build_selecao(tmp_path, monkeypatch, _SELECAO_FATO)

    # FASE 1 — staging vazio → Gold network vazias (contrato ADR-026).
    con = _conectar(db)
    try:
        for tabela in ["network_edges", "network_nodes", "politician_similarity"]:
            assert con.execute(
                f"select count(*) from {tabela}"
            ).fetchone()[0] == 0
    finally:
        con.close()

    fatos = _fact_despesa(db)
    assert not fatos.empty
    _escrever_ml_staging(db, fatos)

    # FASE 2 — com o staging populado, rebuild das drei Gold de rede.
    _build_selecao(tmp_path, monkeypatch, "+network_edges +network_nodes +politician_similarity")

    con = _conectar(db)
    try:
        arestas = con.execute(
            "select id_parlamentar, id_fornecedor, periodo, run_id"
            " from network_edges"
        ).fetchall()
        nos = con.execute(
            "select id_no, tipo_no, periodo, pagerank, degree_centrality, comunidade_id"
            " from network_nodes"
        ).fetchall()
        sim = con.execute(
            "select id_parlamentar_a, id_parlamentar_b, periodo,"
            " num_fornecedores_compartilhados"
            " from politician_similarity order by id_parlamentar_a, id_parlamentar_b"
        ).fetchall()

        assert arestas
        assert all(r[2] in {2019, 2020} and r[3] == _FATO_RUN_ID for r in arestas)
        assert nos
        assert {r[1] for r in nos} == {"parlamentar", "fornecedor"}
        assert all(r[0] > 0 and r[3] >= 0 for r in nos)
        assert sim
        assert all(r[0] < r[1] and r[2] == 2019 for r in sim)  # ordem canônica

        # Todo id de aresta/nó pertence a fact_despesa / dimensões reais.
        pares_fato = {
            (r[0], r[1], int(str(r[2])[:4]))
            for r in con.execute(
                "select id_parlamentar, id_fornecedor, data_sk from fact_despesa"
            ).fetchall()
        }
        for a, f, periodo, _ in arestas:
            assert (a, f, periodo) in pares_fato
    finally:
        con.close()


def test_network_gold_edges_lado_duplo_dimensionado(tmp_path, monkeypatch):
    """Aresta une parlamentar E fornecedor — ambos existem nas dimensões.

    O model `network_edges` usa `exists` contra `dim_parlamentar` e
    `dim_fornecedor` (sem inner join: dim_parlamentar é SCD2, ADR-020).
    Verificamos que cada ponta da aresta resolve em sua dimensão e que o
    peso `valor_total` é a soma real do fato no par/periodo.
    """
    db = tmp_path / _DB
    _seed_silver(db)
    _build_selecao(tmp_path, monkeypatch, _SELECAO_FATO)
    _escrever_ml_staging(db, _fact_despesa(db))
    _build_selecao(tmp_path, monkeypatch, "+network_edges")

    con = _conectar(db)
    try:
        arestas = con.execute(
            "select id_parlamentar, id_fornecedor, periodo, valor_total"
            " from network_edges"
        ).fetchall()
        dim_parlam = {r[0] for r in con.execute(
            "select id_parlamentar from dim_parlamentar"
        ).fetchall()}
        dim_fornecedor = {r[0] for r in con.execute(
            "select id_fornecedor from dim_fornecedor"
        ).fetchall()}
        assert arestas
        for a, f, periodo, valor in arestas:
            assert a in dim_parlam and f in dim_fornecedor
            # `data_sk` é YYYYMMDD: soma do fato valida pelo ano = periodo.
            soma_fato = con.execute(
                "select sum(valor_liquido) from fact_despesa"
                " where id_parlamentar = ? and id_fornecedor = ?"
                " and cast(substr(cast(data_sk as varchar), 1, 4) as integer) = ?",
                [a, f, periodo],
            ).fetchone()[0]
            assert float(valor) == pytest.approx(float(soma_fato))
    finally:
        con.close()
