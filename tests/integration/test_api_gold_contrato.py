# tests/integration/test_api_gold_contrato.py
"""Integração pipeline → Gold → API (Sprint 6, Onda 1 — selo de contrato).

Fecha a lacuna apontada na revisão da Onda 1: os testes `tests/api` provam a
API contra um DuckDB ALREADY-menageado (Gold "disponível") e contra Gold
"indisponível", mas não provam que o Gold PRODUZIDO pelo pipeline atual
contém exatamente os modelos/colunas que os contratos da API esperam.

Este teste roda o **dbt real do projeto Gold** (mesma seleção comprovada de
`tests/pipeline/test_gold_despesa.py` — `_SELECAO_FATO`) sobre um DuckDB
determinístico seedado na Silver, e então direciona a API a esse banco via
`DUCKDB_DATABASE_PATH` (fronteira de leitura, ADR-026). Se o dbt do sprint
corrente mudar um nome/coluna de `dim_parlamentar`/`fact_despesa`/etc., este
teste quebra — é a trava que impede drift silencioso entre o que o pipeline
emite e o que a API consome.

Note: o rebuild do DuckDB real de dev está bloqueado por estado de dados (o
arquivo `data/silver/observatorio.duckdb` local não tem `silver_parlamentar`,
camada alimentada pela cadeia Bronze→Silver sobre fontes externas). O
contrato é, portanto, garantido deterministicamente aqui.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from pipeline.config import load_env_settings
from api.main import app

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD = _RAIZ / "pipeline" / "gold"
_CHAVE_TESTE = "Chave-de-teste-integracao-api-2026"

if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
if str(_GOLD) not in sys.path:
    sys.path.insert(0, str(_GOLD))


@pytest.fixture(autouse=True)
def _chave_hmac(monkeypatch):
    """Determinismo do HMAC do CPF (plugin `hmac_udf`) no build dbt."""
    monkeypatch.setenv("CPF_HMAC_SECRET_KEY", _CHAVE_TESTE)


def _seed(db: Path) -> None:
    """Silver mínima p/ a linhagem de despesa — espelha `test_gold_despesa`."""
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "create table silver_parlamentar (fonte varchar, id_parlamentar bigint,"
            " nome varchar, sigla_partido varchar, sigla_uf varchar, id_legislatura bigint,"
            " situacao_normalizada varchar, data date, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        con.execute(
            "create table silver_despesa (fonte varchar, id_parlamentar bigint,"
            " nome_parlamentar varchar, ano bigint, mes bigint, cod_documento varchar,"
            " data_documento date, tipo_despesa varchar, cnpj_cpf_valor varchar,"
            " tipo_documento varchar, nome_fornecedor varchar, valor_liquido double,"
            " valor_glosa double, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
        # silver_emenda e silver_cartao VAZIAS (mesma razão do test_gold_despesa)
        con.execute(
            "create table silver_emenda (ano bigint, codigo_emenda varchar,"
            " tipo_emenda varchar, nome_autor varchar, funcao varchar,"
            " subfuncao varchar, localidade_do_gasto varchar, valor_empenhado bigint,"
            " valor_liquidado bigint, valor_pago bigint, run_id varchar,"
            " pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        # data_quality_report (Silver, ADR-015/031) — promovido à Gold pelo dbt
        con.execute(
            "create table data_quality_report (run_id varchar, tabela varchar,"
            " total_registros bigint, registros_validos bigint,"
            " registros_quarentena bigint, registros_deduplicados bigint,"
            " regras_violadas varchar, percentual_nulos_criticos double,"
            " execution_timestamp varchar)"
        )
        con.executemany(
            "insert into data_quality_report values (?,?,?,?,?,?,?,?,?)",
            [
                ("run-integ-2026", "silver_despesa", 100, 98, 2, 0,
                 '["regra_violada_integ"]', 0.25, "2026-02-01 05:00:00"),
            ],
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
        con.executemany(
            "insert into silver_parlamentar values (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # JOSE SILVA: troca de partido em 2023 → versão SCD2 fechada + vigente
                ("camara", 1, "JOSE SILVA", "PARTIDO A", "SP", 55, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, "JOSE SILVA", "PARTIDO B", "SP", 57, "Ativo", "2023-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                # MARIA SANTOS: senado, resolvida por nome (id 6)
                ("senado", 6, "MARIA SANTOS", "PARTIDO G", "PR", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        con.executemany(
            "insert into silver_despesa values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # D1: câmara por id, CNPJ — 2023 (dentro da versão vigente de JOSE)
                ("camara", 1, None, 2023, 5, "D1", "2023-05-10", "PASSAGEM AEREA", "12345678000190", "CNPJ", "LATAM", 100, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D2: câmara por id, CPF → HMAC na dimensão
                ("camara", 1, None, 2023, 6, "D2", "2023-06-15", "TAXI", "12345678901", "CPF", "AUTONOMO X", 50, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D3: senado por nome (MARIA SANTOS → id 6)
                ("senado", None, "MARIA SANTOS", 2023, 3, "D3", "2023-03-10", "HOSPEDAGEM", "11111111000100", "CNPJ", "HOTEL CENTER", 200, 0, "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        # ml_staging VAZIA — mesmo contrato ADR-026/030 dos testes Gold
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


# Mesma seleção comprovada em `tests/pipeline/test_gold_despesa.py`.
_SELECAO_FATO = (
    "+desp_parlamento +desp_parlamento_quarantine"
    " +fact_despesa +fact_despesa_quarantine"
    " +fact_emenda + dim_unidade_gestora"
    " +fact_cartao_cpgf +fact_cartao_cpgf_quarantine"
    " +supplier_concentration +supplier_growth +expense_outliers"
    " +network_edges +network_nodes +politician_similarity"
    " +risk_scores"
    " +data_quality_report +pipeline_runs"
)


def _rodar_build_subprocess(db: Path, selecao: str) -> None:
    """Roda `dbt build` do Gold num SUBPROCESSO e aguarda o término.

    Necessário porque o adaptador dbt-duckdb mantém uma conexão
    read-write por processo: se o build rodasse no mesmo processo dos
    endpoints, a API não conseguiria reabrir o arquivo em `read_only`
    ("a different configuration than existing connections"). No teste, o
    build roda num processo efêmero que libera o arquivo ao sair — o
    processo dos endpoints então abre o Gold estritamente read-only
    (ADR-026), como ocorre em produção (pipeline e API são processos
    separados).
    """
    codigo = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(_RAIZ)!r})\n"
        f"sys.path.insert(0, {str(_GOLD)!r})\n"
        "from dbt.cli.main import dbtRunner\n"
        "from pipeline.config import get_dbt_vars\n"
        f"r = dbtRunner().invoke([\n"
        f"    'build',\n"
        f"    '--project-dir', {str(_GOLD)!r},\n"
        f"    '--profiles-dir', {str(_GOLD)!r},\n"
        f"    '--select', {selecao!r},\n"
        f"    '--vars', json.dumps(get_dbt_vars()),\n"
        "]\n"
        ")\n"
        "raise SystemExit(0 if r.success else 1)\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(bool, (str(_GOLD), os.environ.get("PYTHONPATH", "")))
        ),
        "DUCKDB_DATABASE_PATH": str(db),
        "CPF_HMAC_SECRET_KEY": _CHAVE_TESTE,
    }
    subprocess.run([sys.executable, "-c", codigo], env=env, check=True)


def _build_gold(tmp_path, monkeypatch) -> Path:
    """Constrói o Gold com o dbt real (pipeline) e devolve o caminho do DuckDB."""
    db = tmp_path / "gold.duckdb"
    _seed(db)
    _rodar_build_subprocess(db, _SELECAO_FATO)
    return db


@pytest.fixture()
def _cliente_gold(tmp_path, monkeypatch):
    """API apontando para o Gold construído pelo dbt real do pipeline."""
    db = _build_gold(tmp_path, monkeypatch)
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(db))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        yield client


def _dinheiro(valor: float) -> str:
    return str(valor)


def test_parlamentares_vem_do_gold_dbt(_cliente_gold):
    """`GET /parlamentares` reflete o SCD2 emitido pelo dbt: só versões vigentes.

    JOSE SILVA fechou a versão PARTIDO A (2019) e tem a vigente PARTIDO B
    (2023) — a listagem da API deve trazer apenas a vigente, sem duplicidade
    histórica, exatamente como `dim_parlamentar` foi construída pelo dbt.
    """
    corpo = _cliente_gold.get("/parlamentares").json()
    assert corpo["total"] == 2
    ids = [item["id_parlamentar"] for item in corpo["itens"]]
    assert ids == [1, 6]  # JOSE SILVA < MARIA SANTOS por nome_normalizado
    jose = corpo["itens"][0]
    assert jose["sigla_partido"] == "PARTIDO B"
    assert jose["sigla_uf"] == "SP"
    assert jose["fonte"] == "camara"
    assert jose["situacao_normalizada"] == "Ativo"


def test_parlamentares_filtro_sobre_coluna_do_dbt(_cliente_gold):
    """Filtros da API operam sobre colunas emitidas pelo dbt (nome/uf/partido)."""
    assert _cliente_gold.get("/parlamentares", params={"uf": "PR"}).json()["total"] == 1
    assert _cliente_gold.get("/parlamentares", params={"partido": "PARTIDO B"}).json()["total"] == 1
    assert _cliente_gold.get("/parlamentares", params={"nome": "maria"}).json()["total"] == 1


def test_gastos_resolvem_dimensions_do_gold_dbt(_cliente_gold):
    """`GET /parlamentares/1/gastos` resolve fornecedor/categoria/data no dbt."""
    corpo = _cliente_gold.get("/parlamentares/1/gastos").json()
    assert corpo["parlamentar"]["id_parlamentar"] == 1
    assert corpo["parlamentar"]["nome"] == "JOSE SILVA"
    assert corpo["total"] == 2
    datas = [item["data"] for item in corpo["itens"]]
    assert datas == ["2023-06-15", "2023-05-10"]  # ordem desc via dim_data
    dois = corpo["itens"][0]
    assert dois["tipo_despesa"] == "TAXI"
    assert dois["nome_fornecedor"] == "AUTONOMO X"
    assert dois["tipo_documento"] == "CPF"
    assert _dinheiro(dois["valor_liquido"]) == "50.0"
    um = corpo["itens"][1]
    assert um["tipo_despesa"] == "PASSAGEM AEREA"
    assert um["nome_fornecedor"] == "LATAM"
    assert um["tipo_documento"] == "CNPJ"


def test_gastos_senado_por_nome(_cliente_gold):
    """MARIA SANTOS (senado, resolvida por nome no ADR-017) tem seu gasto."""
    corpo = _cliente_gold.get("/parlamentares/6/gastos").json()
    assert corpo["parlamentar"]["id_parlamentar"] == 6
    assert corpo["parlamentar"]["sigla_uf"] == "PR"
    assert corpo["total"] == 1
    item = corpo["itens"][0]
    assert item["tipo_despesa"] == "HOSPEDAGEM"
    assert item["nome_fornecedor"] == "HOTEL CENTER"


def test_gastos_404_parlamentar_inexistente_no_gold(_cliente_gold):
    """Parlamentar inexistente no Gold construído pelo dbt → 404."""
    assert _cliente_gold.get("/parlamentares/999/gastos").status_code == 404


# ── Onda 2: perfil, fornecedores e rede contra o Gold do dbt ─────


def test_perfil_parlamentar_do_gold_dbt(_cliente_gold):
    """Perfil usa a versão vigente emitida pelo dbt (SCD2 → PARTIDO B)."""
    perfil = _cliente_gold.get("/parlamentares/1").json()
    assert perfil["id_parlamentar"] == 1
    assert perfil["nome"] == "JOSE SILVA"
    assert perfil["sigla_partido"] == "PARTIDO B"
    assert perfil["fonte"] == "camara"
    assert perfil["effective_date"] == "2023-02-01"
    assert perfil["end_date"] is None
    assert perfil["is_current"] is True


def test_fornecedores_vindos_do_gold_dbt(_cliente_gold):
    """`dim_fornecedor` emitida pelo dbt alimenta a listagem (CNPJ claro, CPF HMAC)."""
    corpo = _cliente_gold.get("/fornecedores").json()
    nomes = {item["nome_fornecedor"] for item in corpo["itens"]}
    assert {"LATAM", "AUTONOMO X", "HOTEL CENTER"} <= nomes
    latam = next(item for item in corpo["itens"] if item["nome_fornecedor"] == "LATAM")
    assert latam["cnpj_cpf_valor"] == "12345678000190"
    assert latam["tipo_documento"] == "CNPJ"


def test_perfil_fornecedor_do_gold_dbt(_cliente_gold):
    """Perfil do fornecedor = dimensão + agregados sobre `fact_despesa` do dbt."""
    perfil = _cliente_gold.get("/fornecedores/12345678000190").json()
    assert perfil["nome_fornecedor"] == "LATAM"
    assert perfil["tipo_documento"] == "CNPJ"
    assert perfil["num_despesas"] == 1
    assert abs(float(perfil["valor_liquido_total"]) - 100.0) < 1e-9


def test_parlamentares_do_fornecedor_do_gold_dbt(_cliente_gold):
    """Agregado parlamentar↔fornecedor sobre fato promovido + vigente do dbt."""
    corpo = _cliente_gold.get("/fornecedores/12345678000190/parlamentares").json()
    assert corpo["fornecedor"]["nome_fornecedor"] == "LATAM"
    assert corpo["total"] == 1
    jose = corpo["itens"][0]
    assert jose["nome"] == "JOSE SILVA"
    assert jose["sigla_partido"] == "PARTIDO B"
    assert abs(float(jose["total_gasto"]) - 100.0) < 1e-9


def test_rede_endpoint_liga_schema_de_rede_da_gold(_cliente_gold):
    """`/parlamentares/1/rede` liga as colunas de `network_nodes/edges` do dbt.

    `ml_staging` vazio → tabelas Gold de rede existem vazias (schema ainda
    assim validado no bind das colunas pagerank/degree/valor_total, ADR-030).
    Resposta 200 honesta com listas vazias — a API não recalcula análise.
    """
    corpo = _cliente_gold.get("/parlamentares/1/rede").json()
    assert corpo["parlamentar"]["id_parlamentar"] == 1
    assert corpo["nos"] == []
    assert corpo["arestas"] == []


# ── Onda 3: anomalias, comunidades, qualidade e pipeline ─────────


def test_anomalias_endpoint_liga_schema_de_outliers_da_gold(_cliente_gold):
    """`/anomalias` liga as colunas de `expense_outliers` emitidas pelo dbt.

    `ml_staging.expense_outliers` vazio → Gold vazia (schema ainda validado
    no bind de zscore/if_score/num_criterios, ADR-002). 200 honesto — a API
    não recalcula a regra.
    """
    corpo = _cliente_gold.get("/anomalias").json()
    assert corpo["total"] == 0
    assert corpo["itens"] == []


def test_comunidades_liga_schema_de_rede_da_gold(_cliente_gold):
    """`/rede/comunidades` liga `comunidade_id`/pagerank/degree do dbt (ADR-030)."""
    corpo = _cliente_gold.get("/rede/comunidades").json()
    assert corpo["total"] == 0
    assert corpo["itens"] == []


def test_qualidade_relatorio_vem_da_gold_dbt(_cliente_gold):
    """`/qualidade/relatorio` lê `data_quality_report` promovida à Gold (ADR-031).

    A linha semeada na Silver atravessa o model dbt (cast de
    `execution_timestamp`) e chega à API desserializada — se o model
    renomeasse/derrubasse colunas, o contrato quebra.
    """
    corpo = _cliente_gold.get("/qualidade/relatorio").json()
    assert corpo["total"] == 1
    linha = corpo["itens"][0]
    assert linha["run_id"] == "run-integ-2026"
    assert linha["tabela"] == "silver_despesa"
    assert linha["total_registros"] == 100
    assert linha["registros_validos"] == 98
    assert linha["registros_quarentena"] == 2
    assert linha["regras_violadas"] == ["regra_violada_integ"]
    assert linha["percentual_nulos_criticos"] == 0.25
    assert linha["execution_timestamp"] is not None


def test_pipeline_status_liga_schema_de_controle_da_gold(_cliente_gold):
    """`/pipeline/status` liga as colunas de `pipeline_runs` (ADR-019).

    Sem Parquet Bronze de controle → Gold vazia (model produz schema
    compatível, zero linhas — nunca linha fictícia); 200 honesto.
    """
    corpo = _cliente_gold.get("/pipeline/status").json()
    assert corpo["total"] == 0
    assert corpo["itens"] == []