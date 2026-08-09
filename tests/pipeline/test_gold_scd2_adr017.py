# tests/pipeline/test_gold_scd2_adr017.py
"""Integração dbt Gold — `dim_parlamentar` SCD Type 2 + resolução de autor
(ADR-017) + contratos de qualidade dos fatos (ADR-022.1/3a).

Regressão da Onda 2/3 (BACKLOG.md): a dimensão SCD2 (ADR-020), o mecanismo de
resolução de autor de emenda (ADR-017) e as duas camadas de integridade
referencial do ADR-022 são modelos Gold exercitados de verdade aqui (dbtRunner
invocado por teste), não apenas compilados.

Este teste cria um DuckDB temporário com `silver_parlamentar` + `silver_emenda`
realistas, roda os modelos correspondentes e confere:

- SCD2: mudança de partido abre nova versão com `end_date` na data as-of
  seguinte e `is_current` só na última.
- ADR-017: `autor_resolvido` (casa a versão vigente no ano da emenda),
  `autor_colegiado`, `autor_ambiguo`, `autor_fora_cobertura` e
  `autor_nao_resolvido` — cada status observável na saída.
- ADR-022.1: `id_orgao` de `fact_emenda` resolve por JOIN de `dim_orgao` via
  `sigla` (CD/SF) derivada da `fonte` da versão casada — sem literal hardcoded;
  fonte cujo órgão está ausente da dimensão (lag) vai para a quarentena
  (`orgao_nao_resolvido`), nunca NULL silencioso.
- ADR-022.3a: o test genérico customizado `fk_orphan_pct` computa a razão
  órfãos/total por fato e só dispara quando a razão ultrapassa o threshold
  `var('fk_orfas_threshold_pct')` — injetado via `--vars` de
  `config/pipeline.yaml` (fonte única, ADR-008); coberto acima e abaixo do
  limiar, não só no caso feliz de zero órfãos.

Segue PROJECT_CONTEXT §15: nenhum `except` silencioso, erro do dbt derruba o
teste (assert result.success).
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD = _RAIZ / "pipeline" / "gold"

if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
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
        # `silver_despesa` VAZIA: evita erro íntegro quando os testes de FK do
        # fact_despesa (que compartilham dim_orgao/dim_data/dim_parlamentar)
        # são agendados junto com as dimensões selecionadas; sem fatos, passam.
        con.execute(
            "create table silver_despesa (fonte varchar, id_parlamentar bigint,"
            " nome_parlamentar varchar, ano bigint, mes bigint, cod_documento varchar,"
            " data_documento date, tipo_despesa varchar, cnpj_cpf_valor varchar,"
            " tipo_documento varchar, nome_fornecedor varchar, valor_liquido double,"
            " valor_glosa double, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
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
    finally:
        con.close()


def _conectar(db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db))


def _build(tmp_path, monkeypatch, selecao: str) -> None:
    """Roda `dbt build` no projeto Gold apontando DUCKDB_DATABASE_PATH pro fixture.

    Injeta `--vars` derivado de `config/pipeline.yaml` via
    `pipeline.config.get_dbt_vars()` — fonte única do threshold FK órfã
    (ADR-008); o projeto dbt não declara o número e o test `fk_orphan_pct`
    exige a var (falha se ausente). Igual à DAG futura do Gold.
    """
    from dbt.cli.main import dbtRunner

    from pipeline.config import get_dbt_vars

    import json

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
    "dim_orgao dim_data dim_parlamentar dim_unidade_gestora"
    " emenda_autor emenda_autor_quarantine"
    " fact_emenda fact_emenda_quarantine"
    " +fact_despesa +fact_despesa_quarantine"
    " +fact_cartao_cpgf +fact_cartao_cpgf_quarantine"
    " +supplier_concentration +supplier_growth"
)


def test_scd2_dim_parlamentar(tmp_path, monkeypatch):
    """SCD2: troca de partido abre nova versão; end_date na data as-of."""
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

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
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

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
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        row = con.execute(
            "select id_parlamentar, surrogate_key from main.emenda_autor where codigo_emenda = 'E1'"
        ).fetchone()
    finally:
        con.close()

    assert row == (1, 100000001001)


def test_fact_emenda_promove_so_resolvido(tmp_path, monkeypatch):
    """fact_emenda (Onda 3, ADR-012/017): apenas autor resolvido entra no fato.

    A emenda E1 (2019) entra com id_parlamentar=1 (versão vigente no ano) e
    id_orgao=1 (Câmara); as demais (colegiada, ambígua, fora de cobertura,
    não resolvida) ficam na quarentena com motivo explícito.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        fato = con.execute(
            "select ano, codigo_emenda, id_parlamentar, id_orgao, data_sk, tipo_emenda,"
            " valor_empenhado from main.fact_emenda order by codigo_emenda"
        ).fetchall()
        quarentena = {
            (codigo, motivo)
            for codigo, motivo in con.execute(
                "select codigo_emenda, motivo_quarentena from main.fact_emenda_quarantine"
            ).fetchall()
        }
    finally:
        con.close()

    # só E1 entra; autores não-resolvidos nunca ganham id_parlamentar; nenhum
    # órfão de órgão no cenário base (todas as fontes têm sigla em dim_orgao)
    assert fato == [
        (2019, "E1", 1, 1, 20191231, "Emenda Individual - Transferências", 100)
    ]
    assert ("E2", "autor_colegiado") in quarentena
    assert ("E3", "autor_nao_resolvido") in quarentena
    assert ("E4", "autor_fora_cobertura") in quarentena
    assert ("E5", "autor_ambiguo") in quarentena
    assert ("E6", "autor_colegiado") in quarentena
    assert all(m != "orgao_nao_resolvido" for _, m in quarentena)


def test_fact_emenda_orgao_nao_resolvido_na_quarentena(tmp_path, monkeypatch):
    """ADR-022.1: órgão ausente da dimensão NÃO promove; vai à quarentena.

    Simula dessincronização de dimensão (o cenário do ADR-022): `dim_orgao`
    built uma vez; o registro `CD` é removido da tabela e só os fatos são
    re-executados. E1 (fonte 'camara' → sigla CD) passa a ter `id_orgao` NULL
    no `emenda_autor_orgao` → `fact_emenda` exclui e `fact_emenda_quarantine`
    registra `orgao_nao_resolvido` — nunca NULL silencioso.
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

    _build(tmp_path, monkeypatch, "fact_emenda fact_emenda_quarantine")

    con = _conectar(tmp_path / "gold.duckdb")
    try:
        fato = {
            cod for (cod,) in con.execute("select codigo_emenda from main.fact_emenda").fetchall()
        }
        quarentena = {
            (codigo, motivo)
            for codigo, motivo in con.execute(
                "select codigo_emenda, motivo_quarentena from main.fact_emenda_quarantine"
            ).fetchall()
        }
    finally:
        con.close()

    # E1 tem autor resolvido, mas órgão não-resolvido → quarentena, não fato
    assert "E1" not in fato
    assert ("E1", "orgao_nao_resolvido") in quarentena
    # E2 (colegiada) segue quarentenada — o cenário estende, não quebra as
    # classificações base (motivos de autor continuam intactos).
    assert ("E2", "autor_colegiado") in quarentena


def _injetar_orfos(con, n_orfos: int, n_totais: int) -> None:
    """Substitui as linhas de `fact_emenda` por um cenário com razão de órfãos.

    Gera `n_totais` registros: os `n_totais - n_orfos` válidos usam
    `id_parlamentar=1`/`surrogate_key=100000001001`/`id_orgao=1` (existem nas
    dimensões); os `n_orfos` órfãos usam `id_parlamentar=999`/
    `surrogate_key=999` (ausentes em `dim_parlamentar`). `id_orgao` e `data_sk`
    ficam sempre válidos, isolando o disparo nas FKs de parlamentar.
    """
    con.execute("delete from main.fact_emenda")
    con.executemany(
        "INSERT INTO main.fact_emenda (id_emenda, ano, codigo_emenda,"
        " id_parlamentar, surrogate_key, id_orgao, id_unidade_gestora, data_sk,"
        " tipo_emenda, nome_autor, funcao, subfuncao, localidade_do_gasto,"
        " valor_empenhado, valor_liquidado, valor_pago, run_id,"
        " pipeline_version, execution_timestamp, source_version)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                i + 1,
                2019,
                f"V{i}",
                1,
                100000001001,
                1,
                None,
                20191231,
                "Emenda Individual - Transferências",
                "JOSE SILVA",
                "0",
                "0",
                "l",
                10,
                0,
                0,
                "r",
                "p",
                "2026-01-01 00:00:00",
                "s",
            )
            for i in range(n_totais - n_orfos)
        ],
    )
    con.executemany(
        "INSERT INTO main.fact_emenda (id_emenda, ano, codigo_emenda,"
        " id_parlamentar, surrogate_key, id_orgao, id_unidade_gestora, data_sk,"
        " tipo_emenda, nome_autor, funcao, subfuncao, localidade_do_gasto,"
        " valor_empenhado, valor_liquidado, valor_pago, run_id,"
        " pipeline_version, execution_timestamp, source_version)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                1000 + i,
                2019,
                f"O{i}",
                999,
                999999999999,
                1,
                None,
                20191231,
                "Emenda Individual",
                "Z",
                "0",
                "0",
                "l",
                20,
                0,
                0,
                "r",
                "p",
                "2026-01-01 00:00:00",
                "s",
            )
            for i in range(n_orfos)
        ],
    )


def _test_fk_orphan(tmp_path, monkeypatch) -> dict[str, str]:
    """Roda `dbt test --select fact_emenda,test_name:fk_orphan_pct` e devolve status por node.

    A seleção fica ESCOTADA ao fato de emenda: `test_name:fk_orphan_pct` global
    casaria também os testes do `fact_despesa` (que não existe neste fixture) e
    quebraria a medição aqui.

    Injeta `--vars` de `config/pipeline.yaml` (fonte única, ADR-008) — a var
    `fk_orfas_threshold_pct` é exigida pelo test e não existe no projeto dbt.
    """
    from dbt.cli.main import dbtRunner

    from pipeline.config import get_dbt_vars

    import json

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
            "fact_emenda,test_name:fk_orphan_pct",
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
        _injetar_orfos(con, n_orfos=9, n_totais=200)
    finally:
        con.close()

    statuses = _test_fk_orphan(tmp_path, monkeypatch)
    assert statuses, "nenhum teste fk_orphan_pct selecionado"
    for nome, status in statuses.items():
        assert status == "pass", (nome, status)


def test_adr022_fk_orphan_pct_acima_do_limiar(tmp_path, monkeypatch):
    """ADR-022.3a: razão > 5% dispara o alerta (reportado, sem bloquear build).

    15/200 = 7.5% — supera o threshold: `fk_orphan_pct` para `id_parlamentar`
    retorna linhas (falha/warn), alimentando o Data Quality Report.
    """
    _seed(tmp_path / "gold.duckdb")
    _build(tmp_path, monkeypatch, _SELECAO_FATO)
    con = _conectar(tmp_path / "gold.duckdb")
    try:
        _injetar_orfos(con, n_orfos=15, n_totais=200)
    finally:
        con.close()

    statuses = _test_fk_orphan(tmp_path, monkeypatch)
    assert statuses, "nenhum teste fk_orphan_pct selecionado"
    assert any(v != "pass" for v in statuses.values()), statuses