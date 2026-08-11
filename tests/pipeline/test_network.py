# tests/pipeline/test_network.py
"""Grafo bipartido parlamentar↔fornecedor (Sprint 5, Onda 3).

Cobre `analytics/network/network.py` — ADR-030 (grafo bipartido, aresta = valor gasto,
nós = parlamentares/fornecedores), ADR-030.1 (recálculo total por execução,
PageRank global do período), ADR-027.5 (`network_influence_score` = PageRank
normalizado), ADR-030.3 (disjuntor de custo por volume de arestas) e a
persistência em `ml_staging.network_*` (ADR-026, Opção A — Python
single-writer no staging, schema próprio no mesmo DuckDB).

Verifica:
- Construção do grafo: bipartido, aresta agregada por (parlamentar, fornecedor)
  com peso `valor_total`, despesas sem fornecedor não geram aresta.
- PageRank global doi período (determinístico, soma 1) e centralidade de grau;
  comunidades por greedy modularity com rótulos ordenados determinísticos.
- `similaridade_parlamentares`: cosseno por fornecadores compartilhados, ordem
  canônica (a < b), pares sem sobreposição omitidos.
- Persistência `ml_staging.network_edges/nodes/politician_similarity`
  (recálculo total, run_id/pipeline_version/source_version) e `executar_carga_ml_rede`.
- Rastreabilidade da feature `network_influence_score` no registry (ADR-028).
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

import analytics.network.network as rede

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


# ── Nós e grafo ─────────────────────────────────────────────────


def test_no_prefixed_roundtrip():
    """Chaves de nó com namespace próprio e extração reversa (ADR-030)."""
    p = rede.no_parlamentar(12)
    f = rede.no_fornecedor(34)
    assert p == "p:12" and f == "f:34"
    assert rede._id_do_no(p) == 12 and rede._id_do_no(f) == 34
    assert rede._tipo_do_no(p) == rede.TIPO_PARLAMENTAR
    assert rede._tipo_do_no(f) == rede.TIPO_FORNECEDOR


def test_construir_grafo_agrega_por_par():
    """Aresta bipartida agrega o valor por (parlamentar, fornecedor)."""
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 1, 2],
            "id_fornecedor": [10, 10, 20, 10],
            "valor_liquido": [10.0, 5.0, 7.0, 3.0],
        }
    )
    grafo = rede.construir_grafo(fatos)
    # 3 pares únicos: (1,10)=15, (1,20)=7, (2,10)=3
    assert grafo.number_of_nodes() == 4
    assert grafo.number_of_edges() == 3
    assert grafo["p:1"]["f:10"]["valor_total"] == 15.0
    assert grafo["p:1"]["f:20"]["valor_total"] == 7.0
    assert grafo["p:2"]["f:10"]["valor_total"] == 3.0
    # Bipartido: os nós dividem-se em dois conjuntos disjuntos (parlamentares
    # vs fornecedores) e toda aresta liga exatamente um de cada lado.
    nos_parlamentares = {n for n in grafo.nodes() if n.startswith(rede.NO_PARLAMENTAR)}
    nos_fornecedores = set(grafo.nodes()) - nos_parlamentares
    assert not (nos_parlamentares & nos_fornecedores)
    assert all(
        (a in nos_parlamentares and b in nos_fornecedores)
        or (b in nos_parlamentares and a in nos_fornecedores)
        for a, b in grafo.edges()
    )


def test_construir_grafo_ignora_fornecedor_none():
    """Despesa sem fornecedor resolvido não gera aresta (relação exige 2 pontas)."""
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 1],
            "id_fornecedor": [10, None],
            "valor_liquido": [10.0, 50.0],
        }
    )
    grafo = rede.construir_grafo(fatos)
    assert grafo.number_of_edges() == 1
    assert "p:1" in grafo and "f:10" in grafo


def test_construir_grafo_vazio():
    """Sem fatos (ou sem coluna de fornecedor) → grafo vazio, sem erro."""
    assert rede.construir_grafo(None).number_of_nodes() == 0
    assert rede.construir_grafo(pd.DataFrame()).number_of_nodes() == 0
    sem_forn = pd.DataFrame({"id_parlamentar": [1], "valor_liquido": [1.0]})
    assert rede.construir_grafo(sem_forn).number_of_edges() == 0


# ── PageRank / centralidade / comunidades ───────────────────────


def _grafo_teste() -> object:
    """Grafo bipartido pequeno: 3 parlamentares, 2 fornecedores, pesos distintos."""
    from networkx import Graph

    g = Graph()
    for p, f, v in [
        ("p:1", "f:10", 100.0),
        ("p:1", "f:11", 50.0),
        ("p:2", "f:10", 30.0),
        ("p:3", "f:11", 20.0),
    ]:
        g.add_edge(p, f, valor_total=v)
    return g


def test_pagerank_global_deterministico_soma_um():
    """PageRank do grafo completo do período: soma 1, determinístico (ADR-027.5)."""
    g = _grafo_teste()
    pr = rede.calcular_pagerank(g)
    assert set(pr) == set(g.nodes())
    assert abs(sum(pr.values()) - 1.0) < 1e-6
    assert rede.calcular_pagerank(g) == pr  # determinismo por construção


def test_pagerank_reflete_volume_de_arestas_vizinhas():
    """Nó com mais volume nas arestas tem PageRank maior que nó mais periférico."""
    g = _grafo_teste()
    pr = rede.calcular_pagerank(g)
    # p:1 (mais gasto/mais vizinhos) supera p:3 (1 aresta pequena).
    assert pr["p:1"] > pr["p:3"]
    assert pr["f:10"] > 0 and pr["f:11"] > 0


def test_pagerank_grafo_vazio():
    from networkx import Graph

    assert rede.calcular_pagerank(Graph()) == {}


def test_centralidade_grau():
    """Degree centrality calculada por nó (grau / (N-1))."""
    g = _grafo_teste()
    cent = rede.calcular_centralidade_grau(g)
    # 5 nós: parlamentares têm grau 2 → 2/4 = 0.5.
    assert cent["p:1"] == pytest.approx(0.5)
    assert cent["f:10"] == pytest.approx(0.5)


def test_detectar_comunidades_deterministico():
    """Duas componentes disjuntas → 2 comunidades, rótulos ordenados (RF-12)."""
    from networkx import Graph

    g = Graph()
    for p, f in [("p:1", "f:10"), ("p:1", "f:11"), ("p:2", "f:10"), ("p:2", "f:11")]:
        g.add_edge(p, f, valor_total=1.0)
    g.add_edge("p:3", "f:22", valor_total=5.0)
    com = rede.detectar_comunidades(g)
    ids = set(com.values())
    assert ids == {0, 1}
    # Componente do p:3 é a segunda (min de nó maior) → id 1.
    assert com["p:3"] == 1
    assert com["p:1"] == com["p:2"]  # mesma comunidade
    assert com == rede.detectar_comunidades(g)  # determinismo


def test_detectar_comunidades_grafo_vazio():
    from networkx import Graph

    assert rede.detectar_comunidades(Graph()) == {}


# ── Similaridade entre parlamentares ────────────────────────────


def test_similaridade_cosseno_por_fornecedor_compartilhado():
    """Cosseno entre vetores de valor por fornecedor; pares sem sobreposição fora."""
    from networkx import Graph

    g = Graph()
    # P1 e P2 gastam só em F10 (com pesos 1:1) → cosseno 1; P3 em F20 só → sem
    # sobreposição com P1 (não persiste); P4 divide F10 e F11 com P1.
    for p, f, v in [
        ("p:1", "f:10", 1.0),
        ("p:2", "f:10", 1.0),
        ("p:3", "f:20", 5.0),
        ("p:4", "f:10", 2.0),
        ("p:4", "f:11", 2.0),
        ("p:1", "f:11", 1.0),
    ]:
        g.add_edge(p, f, valor_total=v)

    df = rede.similaridade_parlamentares(g)
    assert not df.empty
    assert list(df.columns) == [
        "id_parlamentar_a",
        "id_parlamentar_b",
        "num_fornecedores_compartilhados",
        "similaridade",
    ]
    # Ordem canônica a < b.
    assert (df["id_parlamentar_a"] < df["id_parlamentar_b"]).all()
    linhas = {
        (a, b): (n, sim)
        for a, b, n, sim in df.itertuples(index=False)
    }
    # (1,2): P1={10:1,11:1}, P2={10:1} — compartilha só F10; cosseno = 1/√2.
    assert linhas[(1, 2)][0] == 1
    assert float(linhas[(1, 2)][1]) == pytest.approx(1 / (2 ** 0.5))
    # (2,4): P2={10:1}, P4={10:2,11:2} — compartilha F10; cosseno = 2/(1·√8) = 1/√2.
    assert linhas[(2, 4)][0] == 1
    assert float(linhas[(2, 4)][1]) == pytest.approx(1 / (2 ** 0.5))
    # (1,4): vetores paralelos {10:1,11:1} vs {10:2,11:2} → cosseno 1, 2 fornecedores.
    assert linhas[(1, 4)] == (2, pytest.approx(1.0))
    # P3 (só f20) não tem sobreposição com ninguém → sem linha.
    assert all(3 not in (a, b) for a, b in linhas)


def test_similaridade_sem_sobreposicao_nao_persiste():
    """Pares sem sobreposição de fornecedor não geram registro (CU-08)."""
    from networkx import Graph

    g = Graph()
    g.add_edge("p:1", "f:10", valor_total=1.0)
    g.add_edge("p:2", "f:20", valor_total=1.0)
    assert rede.similaridade_parlamentares(g).empty


def test_similaridade_grafo_vazio_colunas_fixas():
    """Grafo vazio → DataFrame vazio com o schema de colunas."""
    from networkx import Graph

    df = rede.similaridade_parlamentares(Graph())
    assert df.empty
    assert list(df.columns) == [
        "id_parlamentar_a",
        "id_parlamentar_b",
        "num_fornecedores_compartilhados",
        "similaridade",
    ]


# ── Persistência em ml_staging (ADR-026/030) ────────────────────


def test_escrever_rede_duckdb_grava_ml_staging(tmp_path):
    """Python grava no schema `ml_staging`, não direto no Gold."""
    db = tmp_path / "pipe.duckdb"
    arestas = pd.DataFrame(
        {"id_parlamentar": [1], "id_fornecedor": [10], "periodo": [2019], "valor_total": [15.0]}
    )
    nos = pd.DataFrame(
        {"id_no": [1, 10], "tipo_no": ["parlamentar", "fornecedor"],
         "periodo": [2019, 2019], "pagerank": [0.6, 0.4],
         "degree_centrality": [0.5, 0.5], "comunidade_id": [0, 0]}
    )
    sim = pd.DataFrame(
        {"id_parlamentar_a": [1], "id_parlamentar_b": [2], "periodo": [2019],
         "num_fornecedores_compartilhados": [1], "similaridade": [1.0]}
    )
    rede.escrever_rede_duckdb(
        arestas, nos, sim, run_id="run-onda3", db_path=str(db), source_version="v1"
    )

    con = duckdb.connect(str(db))
    try:
        tabelas = {tuple(r) for r in con.execute(
            "select table_schema, table_name from information_schema.tables"
        ).fetchall()}
        assert ("ml_staging", "network_edges") in tabelas
        assert ("ml_staging", "network_nodes") in tabelas
        assert ("ml_staging", "politician_similarity") in tabelas
        assert con.execute(
            "select run_id, periodo from ml_staging.network_edges"
        ).fetchall() == [("run-onda3", 2019)]
        assert con.execute(
            "select pipeline_version is not null from ml_staging.network_nodes"
        ).fetchone()[0]
        assert all(
            r[0] == "v1"
            for r in con.execute(
                "select source_version from ml_staging.politician_similarity"
            ).fetchall()
        )
    finally:
        con.close()


def test_escrever_rede_duckdb_vazio_cria_tabelas(tmp_path):
    """Lote vazio: tabelas de staging criadas vazias (contrato dbt estável)."""
    db = tmp_path / "pipe.duckdb"
    rede.escrever_rede_duckdb(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        run_id="run-vazio", db_path=str(db),
    )
    con = duckdb.connect(str(db))
    try:
        for tabela in ["network_edges", "network_nodes", "politician_similarity"]:
            n = con.execute(f"select count(*) from ml_staging.{tabela}").fetchone()[0]
            assert n == 0
    finally:
        con.close()


def test_executar_carga_ml_rede_fluxo_completo(tmp_path):
    """Orquestração: grafo por ano, PageRank/comunidades/similaridade + staging.

    Espelha a task `executar_ml_rede` da DAG (ADR-030.1): fatos de 2 anos
    viram arestas/nós/similaridades chaveados por (run_id, periodo).
    """
    db = tmp_path / "pipe.duckdb"
    fatos = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 1, 2, 2],
            "id_fornecedor": [10, 10, 20, 10, 30],
            "valor_liquido": [10.0, 5.0, 7.0, 3.0, 4.0],
            "data_sk": [20190101, 20190102, 20190103, 20190201, 20190203],
        }
    )
    contagens = rede.executar_carga_ml_rede(
        fatos, run_id="run-onda3", db_path=str(db), source_version="v1"
    )
    assert contagens["edges"] > 0
    assert contagens["nodes"] > 0
    assert "similarities" in contagens

    con = duckdb.connect(str(db))
    try:
        periodos_edges = {r[0] for r in con.execute(
            "select distinct periodo from ml_staging.network_edges"
        ).fetchall()}
        assert periodos_edges == {2019}
        linhas = con.execute(
            "select run_id, pipeline_version from ml_staging.network_nodes limit 1"
        ).fetchone()
        assert linhas[0] == "run-onda3"
        assert linhas[1]
    finally:
        con.close()


def test_network_influence_registrado_no_registry():
    """A feature `network_influence_score` está registrada na Feature Store (ADR-028).

    O PageRank deste módulo alimenta o score (ADR-027.5) — sem o registro
    (categoria `ml`), o contrato do registry estaria quebrado.
    """
    assert rede.network_no_registry() is True


def test_limite_arestas_recorte_configurado():
    """Disjuntor de custo reage ao volume (ADR-030.3) via config (ADR-008)."""
    from pipeline.config import get_analytics

    limite = get_analytics().rede.limite_arestas_recorte
    assert limite > 0