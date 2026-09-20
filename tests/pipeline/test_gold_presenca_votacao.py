# tests/pipeline/test_gold_presenca_votacao.py
"""Integração dbt Gold — presença e votação da Câmara (Sprint 27 — Onda 1, ADR-058).

Cobre com dbtRunner de verdade:
- Gate "só Encerrada conta": presença/voto em evento Em Andamento vai à
  quarentena (`evento_nao_encerrado`), nunca ao fato.
- Resolução SCD2 as-of data do evento (nunca `is_current`): vigente casa,
  ausente cai em `parlamentar_nao_resolvido`.
- Ausência derivada: vigente sem linha no lote vira `ausente` (nunca
  quarentena); `is_ausencia_injustificada` sempre NULL.
- `seguiu_partido`: orientação igual → true; Liberado → NULL.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD = _RAIZ / "pipeline" / "gold"

if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
if str(_GOLD) not in sys.path:
    sys.path.insert(0, str(_GOLD))

_R = ("r", "p", "2026-01-01 00:00:00", "s")

# Deputados do fixture em IDs próprios (101–103) para não interferir em
# nenhum outro seed; desconhecido = 999.


def _seed(db: Path) -> None:
    """Silver do domínio votação com dados + demais Silver vazias.

    O `+fato` agenda junto os testes de FK de todos os fatos que
    compartilham as dimensões (precedente em test_gold_despesa.py:147):
    as Silver alheias e o `ml_staging` precisam existir (vazios).
    """
    con = duckdb.connect(str(db))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS silver")
        con.execute(
            "create table silver.silver_parlamentar (fonte varchar, id_parlamentar bigint,"
            " nome varchar, sigla_partido varchar, sigla_uf varchar, id_legislatura bigint,"
            " situacao_normalizada varchar, data date, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, url_foto varchar, partido_uf_aproximado boolean,"
            " source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_parlamentar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("camara", 101, "JOSE SILVA", "PARTIDO B", "SP", 57, "ativo",
                 "2023-02-01", *_R, None, False),
                ("camara", 102, "PEDRO ALVES", "PARTIDO C", "RJ", 57, "ativo",
                 "2023-02-01", *_R, None, False),
                ("camara", 103, "MARIA SOUZA", "PARTIDO D", "MG", 57, "ativo",
                 "2023-02-01", *_R, None, False),
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
        con.execute("create schema if not exists ml_staging")
        con.execute(
            "create table ml_staging.network_edges ("
            " id_parlamentar bigint, id_fornecedor bigint, periodo bigint,"
            " valor_total double, run_id varchar, pipeline_version varchar,"
            " execution_timestamp varchar, source_version varchar)"
        )
        con.execute(
            "create table ml_staging.network_nodes ("
            " id_no bigint, tipo_no varchar, periodo bigint, pagerank double,"
            " degree_centrality double, comunidade_id bigint, run_id varchar,"
            " pipeline_version varchar, execution_timestamp varchar,"
            " source_version varchar)"
        )
        con.execute(
            "create table ml_staging.politician_similarity ("
            " id_parlamentar_a bigint, id_parlamentar_b bigint, periodo bigint,"
            " num_fornecedores_compartilhados bigint, similaridade double,"
            " run_id varchar, pipeline_version varchar, execution_timestamp varchar,"
            " source_version varchar)"
        )
        con.execute(
            "create table ml_staging.expense_outliers ("
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
            "create table ml_staging.risk_scores ("
            " periodo bigint, id_parlamentar bigint,"
            " supplier_concentration_score double, political_exposure_score double,"
            " supplier_dependency_score double, expense_anomaly_score double,"
            " network_influence_score double, risk_index double,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        con.execute(
            "create table silver.silver_evento (id_evento bigint, data_inicio timestamp,"
            " data_fim timestamp, descricao_tipo varchar, situacao_bruta varchar,"
            " situacao_normalizada varchar, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_evento values (?,?,?,?,?,?,?,?,?,?)",
            [
                (10, "2024-05-15 14:00:00", "2024-05-15 18:00:00", "Sessão Deliberativa",
                 "Encerrada", "encerrada", *_R),
                (11, "2024-05-16 14:00:00", None, "Sessão Deliberativa",
                 "Em Andamento", "em_andamento", *_R),
            ],
        )
        con.execute(
            "create table silver.silver_presenca (id_evento bigint, id_deputado bigint,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_presenca values (?,?,?,?,?,?)",
            [
                (10, 101, *_R),  # presente resolvido
                (10, 102, *_R),  # presente resolvido
                (10, 999, *_R),  # parlamentar inexistente → quarentena
                (11, 101, *_R),  # evento não-encerrado → quarentena
            ],
        )
        con.execute(
            "create table silver.silver_votacao (id_votacao bigint, id_evento bigint,"
            " descricao varchar, aprovacao varchar, data_registro timestamp,"
            " run_id varchar, pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_votacao values (?,?,?,?,?,?,?,?,?)",
            [
                (100, 10, "PL 1/2024", "Aprovada", "2024-05-15 15:00:00", *_R),
                (101, 11, "PL 2/2024", "Aprovada", "2024-05-16 15:00:00", *_R),
            ],
        )
        con.execute(
            "create table silver.silver_voto (id_votacao bigint, id_deputado bigint,"
            " tipo_voto_bruto varchar, voto_normalizado varchar, run_id varchar,"
            " pipeline_version varchar, execution_timestamp timestamp, source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_voto values (?,?,?,?,?,?,?,?)",
            [
                (100, 101, "Sim", "sim", *_R),
                (100, 102, "Não", "nao", *_R),
                (100, 999, "Sim", "sim", *_R),
                (101, 101, "Sim", "sim", *_R),
            ],
        )
        con.execute(
            "create table silver.silver_orientacao (id_votacao bigint, sigla_bancada varchar,"
            " orientacao_bruta varchar, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        con.executemany(
            "insert into silver.silver_orientacao values (?,?,?,?,?,?,?)",
            [
                (100, "PARTIDO B", "Sim", *_R),
                (100, "PARTIDO C", "Liberado", *_R),
            ],
        )
    finally:
        con.close()


def _build(tmp_path, monkeypatch) -> None:
    from dbt.cli.main import dbtRunner

    from pipeline.config import get_dbt_vars

    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "gold.duckdb"))
    monkeypatch.setenv("PYTHONPATH", str(_GOLD))

    from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    DuckDBConnectionManager._ENV = None

    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir", str(_GOLD),
            "--profiles-dir", str(_GOLD),
            "--select",
            "+fact_presenca +fact_presenca_quarantine +fact_votacao +fact_votacao_quarantine"
            " +fact_despesa +fact_despesa_quarantine +fact_emenda +fact_emenda_quarantine"
            " +fact_cartao_cpgf +fact_cartao_cpgf_quarantine +dim_unidade_gestora"
            " +supplier_concentration +supplier_growth +expense_outliers"
            " +network_edges +network_nodes +politician_similarity +risk_scores",
            "--vars", json.dumps(get_dbt_vars()),
        ]
    )
    assert result.success, result.exception


def _conectar(db: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db))
    con.execute("SET search_path = 'gold'")
    return con


def test_presenca_promove_deriva_e_isola(tmp_path, monkeypatch):
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch)
    con = _conectar(tmp_path / "gold.duckdb")
    try:
        fato = con.execute(
            "select id_parlamentar, id_evento, resultado, is_ausencia_injustificada"
            " from fact_presenca order by id_evento, id_parlamentar"
        ).fetchall()
        # (1,10) e (2,10) presentes; (3,10) ausente derivado; nada do evento 11.
        assert fato == [
            (101, 10, "presente", None),
            (102, 10, "presente", None),
            (103, 10, "ausente", None),
        ]
        quarentena = con.execute(
            "select id_parlamentar, motivo_quarentena from fact_presenca_quarantine"
            " order by id_parlamentar"
        ).fetchall()
        assert quarentena == [
            (101, "evento_nao_encerrado"),
            (999, "parlamentar_nao_resolvido"),
        ]
    finally:
        con.close()


def test_votacao_promove_com_seguiu_e_isola(tmp_path, monkeypatch):
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch)
    con = _conectar(tmp_path / "gold.duckdb")
    try:
        fato = con.execute(
            "select id_parlamentar, id_votacao, voto, seguiu_partido"
            " from fact_votacao order by id_parlamentar"
        ).fetchall()
        # dep1: voto sim + orientação Sim do PARTIDO B → true;
        # dep2: voto nao + PARTIDO C Liberado → NULL.
        assert fato == [
            (101, 100, "sim", True),
            (102, 100, "nao", None),
        ]
        quarentena = con.execute(
            "select id_parlamentar, motivo_quarentena from fact_votacao_quarantine"
            " order by id_parlamentar"
        ).fetchall()
        assert quarentena == [
            (101, "evento_nao_encerrado"),
            (999, "parlamentar_nao_resolvido"),
        ]
    finally:
        con.close()
