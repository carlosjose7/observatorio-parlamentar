# tests/pipeline/test_gold_cartao.py
"""Integração dbt Gold — fato de transações CPGF (Onda 3, Sprint 4).

Regressão da materialização inaugural de `dim_unidade_gestora` (ADR-010/ADR-025)
e do `fact_cartao_cpgf` (ADR-012): a CGU entrega `unidadeGestora.codigo`
nativamente por transação, contrato exige `id_unidade_gestora` NOT NULL — e o
órgão é resolvido por JOIN em `dim_orgao.sigla = EX` (Poder Executivo genérico,
ADR-025), sem literal de id (ADR-022.1).

Coberto aqui (dbtRunner de verdade, molde de `test_gold_despesa.py`):

- Promoção: transações resolvidas entram no fato com `id_orgao=3` (EX),
  `id_unidade_gestora` da dimensão que as próprias transações alimentaram e
  `data_sk` de `data_transacao`; CNPJ do estabelecimento casa no
  `dim_fornecedor` compartilhado (texto claro, ADR-011).
- `id_fornecedor` NULLABLE por contrato (ADR-012): transação sem documento de
  estabelecimento é PROMOVIDA com NULL — não vai à quarentena.
- Quarentena por construção (ADR-018/022): `data_nao_resolvida` (fora do
  horizonte de dim_data) e `orgao_nao_resolvido` (lag da dimensão EX).
- ADR-022.3a: `fk_orphan_pct` por fato, coberto acima e abaixo do limiar
  `var('fk_orfas_threshold_pct')` (fonte única `config/pipeline.yaml`).
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
    """Garante CPF_HMAC_SECRET_KEY determinístico para o plugin hmac_udf."""
    monkeypatch.setenv("CPF_HMAC_SECRET_KEY", "Chave-de-teste-gold-cartao-2026")


def _seed(db: Path) -> None:
    """Popula as Silver exigidas pelo caminho Gold do cartão.

    Espelha a `_seed` do `test_gold_despesa` porque os modelos da despesa
    compartilham dimensões com o cartão (dim_orgao/dim_data/dim_fornecedor): o
    `build` selecionado com `+` agenda os testes de FK desses fatos junto com as
    dimensões, então eles precisam ser buildados (vazios ou não). A despesa
    também alimenta o `dim_fornecedor` compartilhado (chave natural
    (cnpj_cpf_valor, tipo_documento)) — o CNPJ do estabelecimento da transação
    casa por texto claro. `silver_cartao` é a fonte real do fato.

    Transações:
      1 — CNPJ '12345678000190' resolve no dim_fornecedor → promovida.
      2 — sem documento de estabelecimento → promovida com id_fornecedor NULL.
      3 — data 2013 (fora de dim_data 2015-2035) → data_nao_resolvida.
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
                # parlamentar do despesa (id 1, camara), para dim_parlamentar
                ("camara", 1, "JOSE SILVA", "PARTIDO A", "SP", 56, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
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
                # D1: câmara resolve por id; fornecedor CNPJ = o do estabelecimento
                ("camara", 1, None, 2019, 5, "D1", "2019-05-10", "PASSAGEM AEREA",
                 "12345678000190", "CNPJ", "COMERCIO X", 100, 0, "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        # silver_emenda VAZIA: necessária para os testes de FK do fact_emenda
        # (compartilha as mesmas dimensões selecionadas no build). Sem fatos
        # neste fixture do cartão, os testes passam.
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
        con.executemany(
            "insert into silver_cartao values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # C1: tudo resolve — setor cnpj casa no dim_fornecedor
                (1, "2026-02-10", 100.50, "12345678000190", "CNPJ", "COMERCIO X",
                 "EDUARDO CPGF", "***.123.456-**", "150001", "FUNDO A",
                 "r", "p", "2026-01-01 00:00:00", "s"),
                # C2: napo tem documento — fornecedor NULL (nullable), promovida
                (2, "2026-02-11", 50.00, None, None, None,
                 "MARIA PEX", "***.123.456-**", "150001", "FUNDO A",
                 "r", "p", "2026-01-01 00:00:00", "s"),
                # C3: data fora do horizonte (2013 < 2015) → data_nao_resolvida
                (3, "2013-05-20", 30.00, "12345678000190", "CNPJ", "COMERCIO X",
                 "JOAO NORTE", "***.123.456-**", "150001", "FUNDO A",
                 "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        # ml_staging.expense_outliers VAZIA (contrato ADR-026): o build de
        # `+fact_despesa`/`+supplier_*` agenda junto os testes de FK da Onda 2
        # que apontam para a source — o schema/tabela precisam existir mesmo
        # quando o lote Python ainda não gravou.
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


_SELECAO_FATO = (
    "+desp_parlamento +desp_parlamento_quarantine"
    " +fact_despesa +fact_despesa_quarantine"
    " +fact_emenda"
    " +fact_cartao_cpgf +fact_cartao_cpgf_quarantine"
    " +supplier_concentration +supplier_growth +expense_outliers"
)


def test_cartao_promove_so_resolvido(tmp_path, monkeypatch):
    """fact_cartao_cpgf: promovidas as transações com FKs resolvidas.

    C1 (CNPJ resolve) e C2 (fornecedor NULL — nullable por contrato) entram no
    fato com id_orgao=3 (EX), id_unidade_gestora da dimensão inaugurada e
    data_sk correto; C3 (data 2013) fica na quarentena `data_nao_resolvida`.
    O `dim_unidade_gestora` nasce populado pela UG da própria fonte (150001).
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        fato = con.execute(
            "select portador_nome, id_orgao, id_unidade_gestora, id_fornecedor, data_sk"
            " from main.fact_cartao_cpgf"
        ).fetchall()
        quar = {
            (id_, motivo)
            for id_, motivo in con.execute(
                "select id, motivo_quarentena"
                " from main.fact_cartao_cpgf_quarantine"
            ).fetchall()
        }
        dim_ug = con.execute(
            "select id_unidade_gestora, codigo from main.dim_unidade_gestora"
        ).fetchall()
        id_forne_cnpj = con.execute(
            "select id_fornecedor from main.dim_fornecedor"
            " where cnpj_cpf_valor = '12345678000190'"
        ).fetchone()[0]
    finally:
        con.close()

    linhas = {row[0]: row for row in fato}
    assert set(linhas) == {"EDUARDO CPGF", "MARIA PEX"}
    # C1 — colunas: 0=portador 1=id_orgao 2=id_ug 3=id_forne (CNPJ) 4=data_sk
    assert linhas["EDUARDO CPGF"][1:5] == (3, linhas["EDUARDO CPGF"][2], id_forne_cnpj, 20260210)
    # C2 — id_fornedor NULL, id_orgao=3, data
    assert linhas["MARIA PEX"][1] == 3
    assert linhas["MARIA PEX"][3] is None
    assert linhas["MARIA PEX"][4] == 20260211
    # dim_unidade_gestor inaugurou das próprias transações
    assert dim_ug and all(ug[1] == "150001" for ug in dim_ug)
    assert (3, "data_nao_resolvida") in quar
    assert (1, "data_nao_resolvida") not in quar
    assert (2, "data_nao_resolvida") not in quar


def test_cartao_orgao_nao_resolvido_na_quarentena(tmp_path, monkeypatch):
    """ADR-022.1: órgão ausente da dimensão NÃO promove; vai à quarentena.

    Simula dessincronização da dimensão (cenário do ADR-022): `dim_orgao` nasce
    com o seed; o registro `EX` é removido e só os fatos são re-executados.
    C1/C2 (que dependem do EX por construção) passam a `id_orgao` NULL na ponte
    `cartao_unidade` → protagonista a quarentena `orgao_nao_resolvido`.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        assert con.execute(
            "select sigla, id_orgao from main.dim_orgao order by id_orgao"
        ).fetchall() == [("CD", 1), ("SF", 2), ("EX", 3)]
        con.execute("delete from main.dim_orgao where sigla = 'EX'")
    finally:
        con.close()

    _build(tmp_path, monkeypatch, "fact_cartao_cpgf fact_cartao_cpgf_quarantine")

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        portadores_no_fato = {
            p for (p,) in con.execute(
                "select portador_nome from main.fact_cartao_cpgf"
            ).fetchall()
        }
        quar = {
            (id_, motivo)
            for id_, motivo in con.execute(
                "select id, motivo_quarentena"
                " from main.fact_cartao_cpgf_quarantine"
            ).fetchall()
        }
    finally:
        con.close()

    assert "EDUARDO CPGF" not in portadores_no_fato
    assert "MARIA PEX" not in portadores_no_fato
    assert (1, "orgao_nao_resolvido") in quar
    assert (2, "orgao_nao_resolvido") in quar


def _injetar_orfos(con, id_ug_valido: int, n_orfos: int, n_totais: int) -> None:
    """Substitui `fact_cartao_cpgf` por cenário com razão de órfãos controlada.

    Válidos usam id_orgao=3 (EX), id_unidade_gestor=id_ug_valido, data_sk
    existente na dim 20230201 e id_fornecedor NULL (fora do escopo do pct —
    nullable, não é contado). Órfãos desviam SÓ id_orgao=999 (ausente da
    dim, ADR-022.3a); as demais FKs continuam apontando para dimensões.
    """
    con.execute("delete from main.fact_cartao_cpgf")
    validas = [
        (
            i + 1, 3, id_ug_valido, None, 20230201, f"V{i}", "P V", 10,
            "r", "p", "2026-01-01 00:00:00", "s",
        )
        for i in range(n_totais - n_orfos)
    ]
    orfas = [
        (
            1000 + i, 999, id_ug_valido, None, 20230201, f"O{i}", "P O", 20,
            "r", "p", "2026-01-01 00:00:00", "s",
        )
        for i in range(n_orfos)
    ]
    con.executemany(
        "insert into main.fact_cartao_cpgf (id_transacao, id_orgao,"
        " id_unidade_gestora, id_fornecedor, data_sk, portador_nome,"
        " portador_cpf_mascarado, valor_transacao, run_id, pipeline_version,"
        " execution_timestamp, source_version) values (?,?,?,?,?,?,?,?,?,?,?,?)",
        validas + orfas,
    )


def _test_fk_orphan(tmp_path, monkeypatch) -> dict[str, str]:
    """Roda `dbt test --select test_name:fk_orphan_pct` e devolve status por node."""
    from dbt.cli.main import dbtRunner

    from pipeline.config import get_dbt_vars

    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "gold.duckdb"))
    monkeypatch.setenv("PYTHONPATH", str(_GOLD))
    result = dbtRunner().invoke(
        [
            "test",
            "--project-dir",
            str(_GOLD),
            "--profiles-dir",
            str(_GOLD),
            "--select",
            "fact_cartao_cpgf,test_name:fk_orphan_pct",
            "--vars",
            json.dumps(get_dbt_vars()),
        ]
    )
    return {r.node.name: r.status for r in result.result.results}


def test_adr022_fk_orphan_pct_abaixo_do_limiar(tmp_path, monkeypatch):
    """ADR-022.3a: razão de órfãos ≤ threshold padrão (5%) NÃO dispara.

    9/200 = 4.5% — abaixo do limiar, `fk_orphan_pct` passa mesmo com órfãos
    presentes (quem dispara com um órfão isolado é o `relationships`).
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)
    con = _conectar(tmp_path / "gold.duckdb")
    try:
        id_ug = con.execute(
            "select id_unidade_gestora from main.dim_unidade_gestora"
        ).fetchone()[0]
        _injetar_orfos(con, id_ug, n_orfos=9, n_totais=200)
    finally:
        con.close()

    statuses = _test_fk_orphan(tmp_path, monkeypatch)
    assert statuses, "nenhum teste fk_orphan_pct selecionado"
    for nome, status in statuses.items():
        assert status == "pass", (nome, status)


def test_adr022_fk_orphan_pct_acima_do_limiar(tmp_path, monkeypatch):
    """ADR-022.3a: razão > 5% dispara o alerta (reportado, sem bloquear).

    15/200 = 7.5% — supera o threshold: `fk_orphan_pct` para id_orgao retorna
    linhas, alimentando o Data Quality Report.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)
    con = _conectar(tmp_path / "gold.duckdb")
    try:
        id_ug = con.execute(
            "select id_unidade_gestora from main.dim_unidade_gestora"
        ).fetchone()[0]
        _injetar_orfos(con, id_ug, n_orfos=15, n_totais=200)
    finally:
        con.close()

    statuses = _test_fk_orphan(tmp_path, monkeypatch)
    assert statuses, "nenhum teste fk_orphan_pct selecionado"
    assert any(v != "pass" for v in statuses.values()), statuses