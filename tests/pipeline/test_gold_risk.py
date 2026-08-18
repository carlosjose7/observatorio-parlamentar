# tests/pipeline/test_gold_risk.py
"""Integração dbt Gold — risk_scores (ADR-027/029, Onda 4).

Regressão da tabela Gold `risk_scores` — materializada a partir do source
`ml_staging` (ADR-026, Opção A: Python single-writer no staging, o dbt
consome como `source()` e materializa o Gold via `exists` contra
`dim_parlamentar`, sem inner join por SCD2, ADR-020).

Fluxo realista de duas fases (espelha a DAG):
1. Dbt build resolve `silver_*` → Gold `fact_despesa` + `supplier_concentration`.
2. Python lê o `fact_despesa`/`supplier_concentration` DO DUCKDB (ids de
   verdade), roda as cargas das Ondas 2/3 (`ml_staging.expense_outliers` e
   `ml_staging.network_nodes` — raws de anomalia e PageRank) e compõe os
   scores + `risk_index` em `ml_staging.risk_scores`
   (`executar_carga_ml_risco`, ADR-026/029); o dbt então materializa a Gold.

Coberto aqui:
- `main.risk_scores` nasce vazia com o staging vazio (contrato ADR-026) e
  vira o split dos 5 scores com o staging populado.
- Grão correto `(periodo, id_parlamentar)` por run e `risk_index`
  = média das 5 scores (peso 0.2 uniforme do ADR-029).
- `exists` contra `dim_parlamentar`: score só para parlamentar PROMOVIDO
  no fato (ADR-018; quarentena não contamina as fontes).
- Contrato do schema.yml: `not_null` dos scores/`risk_index` e integridade
  referencial (warn) contra `dim_parlamentar`.
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

_CHAVE_TESTE = "Chave-de-teste-gold-risk-2026"
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

    Mesmo seed do `test_gold_expense_outliers.py`: 2 parlamentares
    (camara/senado), 6 despesas (5 resolvíveis + 1 fantasma que vai à
    quarentena) e as tabelas Silver vazias exigidas pelo build das demais
    pontes. Os raws da Onda 4 (`ml_staging.expense_outliers`,
    `network_nodes`, `risk_scores`) são criados VAZIOS — a Fase 1 builda os
    analytics com o staging ainda sem dados.
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
                   _CPF_HMAC, "CPF", "AUTONOMO X", 80, 0, "r", "p", "2026-01-01 00:00:00", "s"),
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
        # ml_staging VAZIA (contrato ADR-026): a Fase 1 builda os analytics com
        # o staging ainda sem dados; o conteúdo real chega nas cargas 2/3/4.
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
# `ml_staging` VAZIO (mesmo seed/molde de test_gold_expense_outliers).
# `+risk_scores` garante que a Gold seja criada e os testes de contrato do
# schema.yml valem a partir daqui.
_SELECAO_FATO = (
    "+supplier_concentration +supplier_growth +expense_outliers"
    " +network_edges +network_nodes +politician_similarity"
    " +risk_scores"
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


def _supplier_concentration(db: Path) -> pd.DataFrame:
    """Lê a Gold `supplier_concentration` (raw do score de concentração)."""
    con = duckdb.connect(str(db))
    try:
        return con.execute(
            "select ano, id_parlamentar, hhi from main.supplier_concentration"
        ).fetchdf()
    finally:
        con.close()


def _dim_data_para_fatos(fatos: pd.DataFrame) -> pd.DataFrame:
    """Constrói `dim_data` a partir das datas do fato (dia útil = seg-sex)."""
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


def _preparar_staging(db: Path, fatos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Popula os raws das Onda 2/3 e devolve os DataFrames para a Onda 4.

    Espelha a DAG: `executar_carga_outliers` grava `ml_staging.expense_outliers`
    (raw de anomalia) e `executar_carga_ml_rede` grava `ml_staging.network_nodes`
    (raw de PageRank); ambos são lidos de volta e entregues à
    `executar_carga_ml_risco` com a Gold `supplier_concentration`.
    """
    from analytics.anomalies.anomalies import executar_carga_outliers
    from analytics.network.network import executar_carga_ml_rede

    datas = _dim_data_para_fatos(fatos)
    executar_carga_outliers(
        fatos, run_id=_FATO_RUN_ID, dim_data=datas, db_path=str(db), source_version="v1"
    )
    executar_carga_ml_rede(fatos, run_id=_FATO_RUN_ID, db_path=str(db), source_version="v1")

    con = duckdb.connect(str(db))
    try:
        outliers = con.execute(
            "select id_despesa, id_parlamentar, id_fornecedor, data_sk,"
            " valor_liquido, is_anomalia from ml_staging.expense_outliers"
        ).fetchdf()
        nos = con.execute(
            "select id_no, tipo_no, periodo, pagerank, degree_centrality,"
            " comunidade_id from ml_staging.network_nodes"
        ).fetchdf()
    finally:
        con.close()
    return outliers, nos


def _escrever_ml_staging(db: Path) -> None:
    """Compoe scores + `risk_index` e grava `ml_staging.risk_scores` (ADR-026/029)."""
    from analytics.parliamentarians.risk import executar_carga_ml_risco

    fatos = _fact_despesa(db)
    outlieres, nos = _preparar_staging(db, fatos)
    executar_carga_ml_risco(
        _supplier_concentration(db),
        fatos,
        outlieres,
        nos,
        run_id=_FATO_RUN_ID,
        db_path=str(db),
        source_version="v1",
    )


_DB = "gold.duckdb"
_FATO_RUN_ID = "r-gold-risk"
_SCORES = [
    "supplier_concentration_score",
    "political_exposure_score",
    "supplier_dependency_score",
    "expense_anomaly_score",
    "network_influence_score",
]


def test_risk_gold_fluxo_duas_fases(tmp_path, monkeypatch):
    """Gold `risk_scores` nasce vazia e passa a ter split do staging populado."""
    db = tmp_path / _DB
    _seed_silver(db)
    _build_selecao(tmp_path, monkeypatch, _SELECAO_FATO)

    # FASE 1 — staging vazio → Gold risk_scores vazia (contrato ADR-026).
    con = duckdb.connect(str(db))
    try:
        assert con.execute("select count(*) from main.risk_scores").fetchone()[0] == 0
    finally:
        con.close()

    _escrever_ml_staging(db)

    # FASE 2 — com o staging populado, rebuild da Gold risk_scores.
    _build_selecao(tmp_path, monkeypatch, "risk_scores")

    con = duckdb.connect(str(db))
    try:
        linhas = con.execute(
            "select periodo, id_parlamentar, "
            + ", ".join(_SCORES)
            + ", risk_index, run_id from main.risk_scores"
        ).fetchall()
        assert linhas
        assert all(r[-1] == _FATO_RUN_ID for r in linhas)

        ids_dim = {r[0] for r in con.execute(
            "select id_parlamentar from main.dim_parlamentar"
        ).fetchall()}
        for periodo, id_parlamentar, *valores, risk_index, _ in linhas:
            # Grão (periodo, id_parlamentar) — parlamentar PROMOVIDO (ADR-018).
            assert id_parlamentar in ids_dim
            assert periodo in {2019, 2020}
            # Todos os scores e o índice vivem em [0, 1] (Min-Max ADR-003).
            assert all(0.0 <= float(v) <= 1.0 for v in valores)
            assert 0.0 <= float(risk_index) <= 1.0
            # ADR-029 (baseline 0.2 uniforme): risk_index = 0.2 × Σ scores.
            assert float(risk_index) == pytest.approx(0.2 * sum(float(v) for v in valores))
    finally:
        con.close()


def test_risk_gold_so_parlamentar_promovido(tmp_path, monkeypatch):
    """O `exists` do model rejeita parlamentar que não resolve em dim_parlamentar.

    Como as fontes da Onda 4 nascem só de `fact_despesa`/`ml_staging` (cujos
    ids são os PROMOVIDOS de verdade), todo score Gold resolve na dimensão —
    a ZONA FANTASMA nunca chega a nenhuma fonte (quarentena na Fase 1).
    """
    db = tmp_path / _DB
    _seed_silver(db)
    _build_selecao(tmp_path, monkeypatch, _SELECAO_FATO)
    _escrever_ml_staging(db)
    _build_selecao(tmp_path, monkeypatch, "risk_scores")

    con = duckdb.connect(str(db))
    try:
        ids_gold = {int(r[0]) for r in con.execute(
            "select distinct id_parlamentar from main.risk_scores"
        ).fetchall()}
        ids_dim = {int(r[0]) for r in con.execute(
            "select id_parlamentar from main.dim_parlamentar"
        ).fetchall()}
        assert ids_gold
        assert ids_gold <= ids_dim
        # ZONA FANTASMA (id 9999 se houvesse) não aparece — quarentena.
        ids_fato = {int(r[0]) for r in con.execute(
            "select distinct id_parlamentar from main.fact_despesa"
        ).fetchall()}
        assert ids_gold <= ids_fato
    finally:
        con.close()
