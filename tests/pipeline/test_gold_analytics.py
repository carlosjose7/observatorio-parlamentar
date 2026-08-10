# tests/pipeline/test_gold_analytics.py
"""Integração dbt Gold — agregados analíticos puros (ADR-021, Onda 3).

Regressão das tabelas `supplier_concentration` (HHI por parlamentar/ano) e
`supplier_growth` (crescimento de receita por fornecedor/ano, YoY) — as duas
tabelas puramente agregadas do §7 que a Sprint 4 popula como models dbt
regulares (ADR-021), sem ML.

Coberto aqui (dbtRunner de verdade, molde de `test_gold_despesa.py`):

- `supplier_concentration`: HHI = SUM(participacao^2) por (ano, id_parlamentar),
  com `num_fornecedores` e `total_valor` no grão correto; HHI = 1 quando o
  parlamentar gastou em um único fornecedor no ano.
- `supplier_growth`: `valor_ano_anterior`/`variacao_pct` corretos (YoY),
  nulos no primeiro período do fornecedor.
- Não-nulidade/validade: só fatos promovidos entram (quarentena não contaminam
  os agregados).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
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

    O `dim_fornecedor` (requisito dos agregados via fact_despesa) exige a chave
    quando há fornecedores CPF — mesma garantia dos demais testes Gold.
    """
    monkeypatch.setenv("CPF_HMAC_SECRET_KEY", "Chave-de-teste-gold-analytics-2026")


def _seed(db: Path) -> None:
    """Popula Silver suficiente para materializar fact_despesa e os agregados.

    Três anos (2019-2021) para exercitar YoY do `supplier_growth` e HHI com
    1 e 2 fornecedores no mesmo parlamentar/ano:

    - Parlamentar 1 (JOSE SILVA, camara, id 1) com 2 fornecedores em 2019
      (CNPJ + CPF) e 1 só em 2020;
    - Parlamentar 2 (MARIA, senado, id 6) com 2 fornecedores em 2019;
    - Fornecedores CNPJ/CPF resolvem no `dim_fornecedor` compartilhado.
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
                # P1/2019: dois fornecedores — CNPJ (120) + CPF (80) → HHI = (120/200)^2+(80/200)^2
                ("camara", 1, None, 2019, 5, "D1", "2019-05-10", "HOSPEDAGEM",
                 "12345678000190", "CNPJ", "COMERCIO X", 120, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, None, 2019, 6, "D2", "2019-06-15", "TAXI",
                   "12345678901", "CPF", "AUTONOMO X", 80, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # P1/2020: único fornecedor (CNPJ 123) → hhi = 1
                ("camara", 1, None, 2020, 3, "D3", "2020-03-10", "HOSPEDAGEM",
                   "12345678000190", "CNPJ", "COMERCIO Y", 50, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # P2/2019: MARIA com dois fornecedores (111 e 222)
                ("senado", None, "MARIA SANTOS", 2019, 3, "D4", "2019-03-10", "HOSPEDAGEM",
                   "11111111000100", "CNPJ", "HOTEL A", 60, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", None, "MARIA SANTOS", 2019, 4, "D5", "2019-04-10", "HOSPEDAGEM",
                   "22222222000100", "CNPJ", "HOTEL B", 140, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D6: senado — nome_fornecedor desconhecido → não resolve
                ("senado", None, "ZONA FANTASMA", 2019, 5, "D6", "2019-05-11", "CORREIOS",
                   "33333333000100", "CNPJ", "EMPRESA X", 100, 0, "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        # silver_emenda / silver_cartao VAZIAS: exigidas pelos testes de FK de
        # fact_emenda/fact_cartao que o build com `+` agenda junto das dimensões.
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
        # ml_staging VAZIA: desde a Onda 2/3 (Sprint 5) os models analytics
        # (`expense_outliers`, `network_edges`, `network_nodes`,
        # `politician_similarity`) disparam testes de FK que apontam para
        # fact_despesa/dimensões — o build destes agregados agenda junto esses
        # testes, exigindo que as sources `ml_staging` existam no DuckDB (schema
        # próprio + tabelas, contrato ADR-026/030). Vazias aqui porque este teste
        # exercita apenas agregados puros; a fonte real é escrita pelo Python.
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
    finally:
        con.close()


def _conectar(db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db))


def _build(tmp_path, monkeypatch, selecao: str) -> None:
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


_SELECAO = (
    "+supplier_concentration +supplier_growth +expense_outliers"
    " +network_edges +network_nodes +politician_similarity"
    " +fact_emenda +fact_cartao_cpgf +fact_cartao_cpgf_quarantine"
)


def _fornecedor(db: Path, doc: str) -> int:
    con = _conectar(db)
    try:
        return con.execute(
            "select id_fornecedor from main.dim_fornecedor where cnpj_cpf_valor = ?",
            [doc],
        ).fetchone()[0]
    finally:
        con.close()


def test_analytics_supplier_concentration(tmp_path, monkeypatch):
    """supplier_concentration: HHI por (ano, parlamentar) com participações corretas."""
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        # HHI esperado por parlamentar/ano
        rows = {
            (ano, id_par): (num_f, total, round(float(hhi), 6))
            for ano, id_par, num_f, total, hhi in con.execute(
                "select ano, id_parlamentar, num_fornecedores, total_valor, hhi"
                " from main.supplier_concentration order by ano, id_parlamentar"
            ).fetchall()
        }
        # P1 2019: (120/200)^2 + (80/200)^2 = .36 + .16 = .52
        assert rows[(2019, 1)] == (2, 200, 0.52)
        # P1 2020: só um fornecedor → hhi = 1
        assert rows[(2020, 1)] == (1, 50, 1.0)
        # P2 (MARIA) 2019: (60/200)^2 + (140/200)^2 = .09 + .49 = .58
        assert rows[(2019, 6)] == (2, 200, 0.58)
    finally:
        con.close()


def test_analytics_supplier_growth_yoy(tmp_path, monkeypatch):
    """supplier_growth: YoY correto, nulo no primeiro período."""
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        rows = {
            (ano, id_f): (valor, ant, var)
            for ano, id_f, valor, ant, var in con.execute(
                "select ano, id_fornecedor, valor_recebido, valor_ano_anterior, variacao_pct"
                " from main.supplier_growth"
            ).fetchall()
        }
        forne_cnpj = _fornecedor(tmp_path / "gold.duckdb", "12345678000190")
        # CNPJ 123: 2019 → 120 (sem anterior), 2020 → 50 ; YoY = (50-120)/120 = -0.5833...
        assert rows[(2019, forne_cnpj)] == (120, None, None)
        assert rows[(2020, forne_cnpj)][0] == 50
        assert rows[(2020, forne_cnpj)][1] == 120
        assert abs(float(rows[(2020, forne_cnpj)][2]) - (-0.583333)) < 1e-6
    finally:
        con.close()


def test_analytics_nao_contamina_quarentena(tmp_path, monkeypatch):
    """Só fatos PROMOVIDOS entram nos agregados (D6 não os contamina).

    O CNPJ removido do evento (ZONA FANTASMA, D6) existe em `dim_fornecedor`
    (derivado de toda silver_despesa), mas a despesa vai à quarentena de
    parlamentar — logo o fornecedor NÃO aparece nos agregados (que só leem
    `fact_despesa`), e o parlamentar ZONA FANTASMA não gera linha fantasma.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        cnpj_d6 = con.execute(
            "select id_fornecedor from main.dim_fornecedor"
            " where cnpj_cpf_valor = '33333333000100'"
        ).fetchone()
        # O fornecedor existe na dimensão (dimensão deriva da silver inteira)...
        assert cnpj_d6 is not None
        # ...mas não vaza para os agregados, que só leem o fato promovido.
        ids_growth = {r[0] for r in con.execute(
            "select id_fornecedor from main.supplier_growth"
        ).fetchall()}
        assert cnpj_d6[0] not in ids_growth
        # Nenhuma linha fantasma de um parlamentar não resolvido.
        assert con.execute(
            "select count(*) from main.supplier_concentration"
        ).fetchone()[0] == 3
    finally:
        con.close()
