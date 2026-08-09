# tests/pipeline/test_gold_despesa.py
"""Integração dbt Gold — fato de despesa parlamentar (Onda 3, Sprint 4 Gold).

Regressão do fechamento da cadeia de identidade da despesa (BACKLOG.md): o
`fact_despesa` nasce com os JOINs reais das dimensões
(parlamentar/órgão/fornecedor/categoria + data), e o `id_parlamentar` NÃO vira
`parlamentar_nao_resolvido` em massa — a identidade é capturada na fonte:

- **Câmara** (silver_despesa.id_parlamentar = id_deputado): matching exato por
  id natural contra a versão de `dim_parlamentar` vigente na `data_documento`
  (SCD2, ADR-020).
- **Senado** (CEAPS só expõe `senador` → silver_despesa.nome_parlamentar,
  id_parlamentar NULL): matching exato do nome normalizado (macro
  `nome_normalizado`, regra ADR-017) restrito à versão vigente na data.
- **Fornecedor**: CNPJ por chave natural em texto claro; CPF casado via HMAC
  da UDF (ADR-011) — o valor na dimensão NUNCA é o CPF cru.

Coberto aqui (dbtRunner de verdade, como `test_gold_scd2_adr017.py`):

- ADR-017/ADR-020 adaptado à data: `parlamentar_resolvido` casa a versão
  vigente na `data_documento`; `parlamentar_ambiguo` nunca grava id;
  `parlamentar_fora_cobertura`; `parlamentar_nao_resolvido`; `data_nao_resolvida`.
- ADR-011: fornecedor de CPF entra no fato pelo id da dimensão (HMAC).
- ADR-022.1: órgão ausente da dimensão NÃO promove — vai à quarentena
  (`orgao_nao_resolvido`), nunca NULL silencioso.
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
    """Garante CPF_HMAC_SECRET_KEY determinístico para o plugin hmac_udf.

    O registro da UDF é exigido pelo `dim_fornecedor` (CPF pseudonimizado) e o
    build só roda se a chave estiver presente no ambiente — mesma garantia de
    `tests/pipeline/test_gold_hmac_udf.py`.
    """
    monkeypatch.setenv("CPF_HMAC_SECRET_KEY", "Chave-de-teste-gold-despesa-2026")


def _seed(db: Path) -> None:
    """Popula as Silver exigidas pelos modelos Gold alvo do despesa."""
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
        # `silver_emenda` VAZIA: necessária para os testes de FK do fact_emenda
        # (que compartilham as mesmas dimensões — o build do dbt roda os testes
        # que referenciam as dimensões selecionadas). Sem fatos, os testes passam.
        con.execute(
            "create table silver_emenda (ano bigint, codigo_emenda varchar,"
            " tipo_emenda varchar, nome_autor varchar, funcao varchar,"
            " subfuncao varchar, localidade_do_gasto varchar, valor_empenhado bigint,"
            " valor_liquidado bigint, valor_pago bigint, run_id varchar,"
            " pipeline_version varchar, execution_timestamp timestamp,"
            " source_version varchar)"
        )
        # `silver_cartao` VAZIA: fonte de dim_unidade_gestora (ADR-010/ADR-025),
        # que agora é modelo Gold e tem testes de FK agendados junto com
        # dim_orgao/dim_data nos builds selecionados aqui; sem linhas, passam.
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
                # JOSE SILVA troca de partido em 2019 (nova versão) e em 2023
                ("camara", 1, "JOSE SILVA", "PARTIDO A", "SP", 55, "Ativo", "2019-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, "JOSE SILVA", "PARTIDO B", "SP", 56, "Ativo", "2019-07-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("camara", 1, "JOSE SILVA", "PARTIDO B", "SP", 57, "Ativo", "2023-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                # PEDRO só vigente a partir de 2020
                ("camara", 2, "PEDRO ALVES", "PARTIDO C", "RJ", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                # homônimos no SENADO (ids 4 e 5) — despesa por nome → ambígua
                ("senado", 4, "JOAO DO NORTE", "PARTIDO D", "SP", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                ("senado", 5, "JOAO DO NORTE", "PARTIDO F", "SP", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
                # MARIA SANTOS conhecida, vigente só a partir de 2020
                ("senado", 6, "MARIA SANTOS", "PARTIDO G", "PR", 56, "Ativo", "2020-02-01", "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
        con.executemany(
            "INSERT INTO silver_despesa VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # D1: câmara por id (versão 1 vigente em 2019-05-10), fornecedor CNPJ
                ("camara", 1, None, 2019, 5, "D1", "2019-05-10", "PASSAGEM AEREA", "12345678000190", "CNPJ", "LATAM", 100, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D2: câmara por id, fornecedor CPF → HMAC na dimensão
                ("camara", 1, None, 2019, 6, "D2", "2019-06-15", "TAXI", "12345678901", "CPF", "AUTONOMO X", 50, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D3: senado — resolvido por nome (MARIA SANTOS → id 6)
                ("senado", None, "MARIA SANTOS", 2020, 3, "D3", "2020-03-10", "HOSPEDAGEM", "11111111000100", "CNPJ", "HOTEL CENTER", 200, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D4: senado — nome existe, sem versão vigente na data → fora de cobertura
                ("senado", None, "MARIA SANTOS", 2019, 5, "D4", "2019-05-20", "COMBUSTIVEL", "22222222000100", "CNPJ", "POSTO SOL", 30, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D5: senado — dois homônimos vigentes na data → ambígua
                ("senado", None, "JOAO DO NORTE", 2020, 5, "D5", "2020-05-10", "TELEFONIA", "33333333000100", "CNPJ", "OPERADORA A", 10, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D6: senado — nome desconhecido no cadastro → não resolvido
                ("senado", None, "ZONA FANTASMA", 2020, 5, "D6", "2020-05-11", "OUTROS", "44444444000100", "CNPJ", "EMPRESA X", 10, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D7: câmara — parlamentar resolvido, fornecedor sem documento
                ("camara", 1, None, 2019, 7, "D7", "2019-07-10", "PASSAGEM AEREA", None, None, None, 5, 0, "r", "p", "2026-01-01 00:00:00", "s"),
                # D8: senado — data_documento ausente → data_nao_resolvida
                ("senado", None, "ZONA FANTASMA", 2020, 9, "D8", None, "OUTROS", "55555555000100", "CNPJ", "EMPRESA Y", 1, 0, "r", "p", "2026-01-01 00:00:00", "s"),
            ],
        )
    finally:
        con.close()


def _conectar(db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db))


def _build(tmp_path, monkeypatch, selecao: str) -> None:
    """Roda `dbt build` no projeto Gold apontando o fixture como banco.

    Injeta `--vars` derivado de `config/pipeline.yaml` via
    `pipeline.config.get_dbt_vars()` — fonte única do threshold FK órfã
    (ADR-008); o projeto dbt não declara o número.
    """
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
    " +fact_emenda + dim_unidade_gestora"
    " +fact_cartao_cpgf +fact_cartao_cpgf_quarantine"
)


def test_despesa_promove_so_resolvido(tmp_path, monkeypatch):
    """fact_despesa: só parlamentar resolvido entra, com as dims JOINadas.

    D1 (câmara, por id) e D3 (senado, por nome) entram com as FKs resolvidas;
    D2 (CPF) entra com o fornecedor do HMAC da dimensão; D4–D8 ficam na
    quarentena com motivo explícito.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        fato = con.execute(
            "select cod_documento, id_parlamentar, surrogate_key, id_orgao, id_fornecedor,"
            " data_sk, cod_tipo from main.fact_despesa order by id_despesa"
        ).fetchall()
        parlam_quar = {
            (cod, motivo)
            for cod, motivo in con.execute(
                "select cod_documento, motivo from main.desp_parlamento_quarantine"
            ).fetchall()
        }
        fato_quar = {
            (cod, motivo)
            for cod, motivo in con.execute(
                "select cod_documento, motivo_quarentena"
                " from main.fact_despesa_quarantine"
            ).fetchall()
        }
        surrogates = dict(
            con.execute(
                "select cod_documento, surrogate_key from main.desp_parlamento"
            ).fetchall()
        )
        dim_sk = {k for (k,) in con.execute(
            "select surrogate_key from main.dim_parlamentar"
        ).fetchall()}
        fornecedor_cnpj = con.execute(
            "select id_fornecedor from main.dim_fornecedor"
            " where cnpj_cpf_valor = '12345678000190' and tipo_documento = 'CNPJ'"
        ).fetchone()[0]
        fornecedor_cpf_id = con.execute(
            "select id_fornecedor from main.dim_fornecedor where tipo_documento = 'CPF'"
        ).fetchone()[0]
        fornecedor_d3 = con.execute(
            "select id_fornecedor from main.dim_fornecedor"
            " where cnpj_cpf_valor = '11111111000100' and tipo_documento = 'CNPJ'"
        ).fetchone()[0]
        cpf_dim = con.execute(
            "select cnpj_cpf_valor from main.dim_fornecedor where tipo_documento = 'CPF'"
        ).fetchone()[0]
    finally:
        con.close()

    linhas = {row[0]: row for row in fato}
    assert set(linhas) == {"D1", "D2", "D3"}
    # colunas: 0=cod_documento 1=id_parlamentar 2=surrogate_key 3=id_orgao
    #          4=id_fornecedor 5=data_sk 6=cod_tipo
    # D1 — câmara → CD (id_orgao=1); data 2019-05-10 → data_sk 20190510
    #      versão vigente na data = JOSE SILVA v1 (partido A até 2019-07)
    assert linhas["D1"][1:5] == (1, 100000001001, 1, fornecedor_cnpj)
    assert linhas["D1"][5] == 20190510
    # D2 — mesma versão de D1; fornecedor CPF resolveu pelo HMAC da dimensão
    assert linhas["D2"][2] == 100000001001
    assert linhas["D2"][4] == fornecedor_cpf_id
    # D3 — senado → SF (id_orgao=2), resolvido por nome (id 6),
    #      versão vigente em 2020-03-10 = MARIA SANTOS senado v1
    assert linhas["D3"][1:5] == (6, 200000006001, 2, fornecedor_d3)
    assert linhas["D3"][5] == 20200310
    # FK 1:1 por versão exata: a chave do fato existe em dim_parlamentar
    assert {row[2] for row in fato} <= dim_sk
    assert surrogates["D1"] == 100000001001  # versão vigente em 2019-05-10
    assert surrogates["D3"] == 200000006001  # senado id 6, versão 1

    assert ("D4", "parlamentar_fora_cobertura") in parlam_quar
    assert ("D5", "parlamentar_ambiguo") in parlam_quar
    assert ("D6", "parlamentar_nao_resolvido") in parlam_quar
    assert ("D8", "data_nao_resolvida") in parlam_quar
    assert ("D7", "fornecedor_nao_resolvido") in fato_quar
    assert ("D8", "data_nao_resolvida") in fato_quar
    # CPF pseudonimizado: 64 hex, nunca o número cru (ADR-011)
    assert cpf_dim and len(cpf_dim) == 64 and cpf_dim != "12345678901"


def test_despesa_orgao_nao_resolvido_na_quarentena(tmp_path, monkeypatch):
    """ADR-022.1: órgão ausente da dimensão NÃO promove; vai à quarentena.

    Simula dessincronização de dimensão (cenário do ADR-022): `dim_orgao`
    built uma vez; o registro `CD` é removido e só os fatos são re-executados.
    D1/D2 (fonte 'camara' → sigla CD) passam a ter `id_orgao` NULL no
    `desp_orgao` → `fact_despesa` exclui e `fact_despesa_quarantine` registra
    `orgao_nao_resolvido` — nunca NULL silencioso.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        assert con.execute(
            "select sigla, id_orgao from main.dim_orgao order by id_orgao"
        ).fetchall() == [("CD", 1), ("SF", 2), ("EX", 3)]
        con.execute("delete from main.dim_orgao where sigla = 'CD'")
    finally:
        con.close()

    _build(tmp_path, monkeypatch, "fact_despesa fact_despesa_quarantine")

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        fato = {cod for (cod,) in con.execute("select cod_documento from main.fact_despesa").fetchall()}
        quar = {
            (cod, motivo)
            for cod, motivo in con.execute(
                "select cod_documento, motivo_quarentena"
                " from main.fact_despesa_quarantine"
            ).fetchall()
        }
    finally:
        con.close()

    # D1/D2 têm parlamentar e fornecedor resolvidos, mas órgão não → quarentena
    assert "D1" not in fato and "D2" not in fato
    assert ("D1", "orgao_nao_resolvido") in quar
    assert ("D2", "orgao_nao_resolvido") in quar
    # D3 (senado → SF) segue no fato; motivos de autor das demais intactos
    assert "D3" in fato
    assert ("D4", "parlamentar_fora_cobertura") in quar


def _injetar_orfos(con, id_fornecedor_valido: int, n_orfos: int, n_totais: int) -> None:
    """Substitui `fact_despesa` por um cenário com razão de órfãos controlada.

    `n_totais - n_orfos` registros válidos usam `id_parlamentar=1`,
    `id_fornecedor=id_fornecedor_valido`, `id_orgao=1`, `cod_tipo`/`data_sk`
    existentes nas dimensões (só a FK de parlamentar é desviada); os `n_orfos`
    usam `id_parlamentar=999` (ausente em dim_parlamentar).
    """
    from hashlib import md5

    cod_tipo = md5(b"PASSAGEM AEREA").hexdigest()[:12]
    con.execute("delete from main.fact_despesa")
    linhas_validas = [
        (
            i + 1, 1, 100000001001, id_fornecedor_valido, 1, None, cod_tipo, 20190101,
            f"V{i}", 10, 0, "r", "p", "2026-01-01 00:00:00", "s",
        )
        for i in range(n_totais - n_orfos)
    ]
    linhas_orfas = [
        (
            1000 + i, 999, 999999999999, id_fornecedor_valido, 1, None, cod_tipo, 20190101,
            f"O{i}", 20, 0, "r", "p", "2026-01-01 00:00:00", "s",
        )
        for i in range(n_orfos)
    ]
    con.executemany(
        "INSERT INTO main.fact_despesa (id_despesa, id_parlamentar, surrogate_key,"
        " id_fornecedor, id_orgao, id_unidade_gestora, cod_tipo, data_sk, cod_documento,"
        " valor_liquido, valor_glosa, run_id, pipeline_version,"
        " execution_timestamp, source_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        linhas_validas + linhas_orfas,
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
            "fact_despesa,test_name:fk_orphan_pct",
            "--vars",
            json.dumps(get_dbt_vars()),
        ]
    )
    return {r.node.name: r.status for r in result.result.results}


def test_adr022_fk_orphan_pct_abaixo_do_limiar(tmp_path, monkeypatch):
    """ADR-022.3a: razão de órfãos ≤ threshold padrão (5%) NÃO dispara o test.

    9/200 = 4.5% — abaixo do limiar, `fk_orphan_pct` passa mesmo com órfãos
    presentes (quem dispara com um órfão isolado é o `relationships`).
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)
    con = _conectar(tmp_path / "gold.duckdb")
    try:
        id_f = con.execute(
            "select id_fornecedor from main.dim_fornecedor"
            " where cnpj_cpf_valor = '12345678000190'"
        ).fetchone()[0]
        _injetar_orfos(con, id_f, n_orfos=9, n_totais=200)
    finally:
        con.close()

    statuses = _test_fk_orphan(tmp_path, monkeypatch)
    assert statuses, "nenhum teste fk_orphan_pct selecionado"
    for nome, status in statuses.items():
        assert status == "pass", (nome, status)


def test_adr022_fk_orphan_pct_acima_do_limiar(tmp_path, monkeypatch):
    """ADR-022.3a: razão > 5% dispara o alerta (reportado, sem bloquear).

    15/200 = 7.5% — supera o threshold: `fk_orphan_pct` para `id_parlamentar`
    retorna linhas (falha/warn), alimentando o Data Quality Report.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)
    con = _conectar(tmp_path / "gold.duckdb")
    try:
        id_f = con.execute(
            "select id_fornecedor from main.dim_fornecedor"
            " where cnpj_cpf_valor = '12345678000190'"
        ).fetchone()[0]
        _injetar_orfos(con, id_f, n_orfos=15, n_totais=200)
    finally:
        con.close()

    statuses = _test_fk_orphan(tmp_path, monkeypatch)
    assert statuses, "nenhum teste fk_orphan_pct selecionado"
    assert any(v != "pass" for v in statuses.values()), statuses
