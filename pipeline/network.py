"""pipeline/network.py — grafo bipartido parlamentar↔fornecedor (Sprint 5, Onda 3).

Constrói a rede de relacionamentos entre parlamentares e fornecedores a
partir do fato promovido `fact_despesa` (Sprint 4 Gold). O grafo é
**bipartido** (ADR-030):

- nós = parlamentares (`p` em Graf) e fornecedores (`f`);
- arestas = valor gasto (`v_{p,f}`) entre um parlamentar e um fornecedor,
  agregado no período — peso da aresta.

Para cada período (grão ano, coerente com as demais analíticas §7/ADR-021)
são computados PageRank (ADR-027.5 — `network_influence_score`),
centralidade de grau e comunidades (NetworkX, `greedy_modularity`), além
da similaridade entre parlamentares (`politician_similarity`, §7/CU-08)
por sobreposição de fornecedores. O PageRank é **global do período**
(ADR-030.1) — o recálculo é total por execução, nunca incremental.

Saída: por exigência do ADR-026 (Opção A), Python escreve **exclusivamente**
no schema `ml_staging` (DuckDB, single-writer) — aqui `ml_staging.network_
edges`, `ml_staging.network_nodes` e `ml_staging.politician_similarity`,
chaveados por `(run_id, periodo)` (ADR-030.1). O dbt consome como `source()`
e materializa as três Gold correspondentes (models `analytics/`, ADR-021).

Disjuntor de custo (ADR-030.3): o número de arestas por período é
comparado contra `config/analytics.yaml → rede.limite_arestas_recorte`
(fonte única ADR-008). Acima do limite, emite alerta estruturado no DQ
Report — sem bloquear a execução; o aumento persistente reabre a decisão
de estratégia incremental via ADR de superseding (nunca ajuste cego).
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import structlog

from pipeline.config import get_analytics
from pipeline.features import carregar_registry

logger = structlog.get_logger()

#: Prefixo dos nós parlamentares no grafo (evita colisão numérica com fornecedor).
NO_PARLAMENTAR = "p:"

#: Prefixo dos nós fornecedores no grafo.
NO_FORNECEDOR = "f:"

#: Tipos de nó persistidos em `ml_staging.network_nodes`.
TIPO_PARLAMENTAR = "parlamentar"
TIPO_FORNECEDOR = "fornecedor"

#: Damping factor do PageRank (NetworkX padrão, reconhecido como baseline).
PAGERANK_ALFA = 0.85

#: Tolerância de convergência do PageRank.
PAGERANK_TOL = 1e-06

#: Semente fixa — determinismo da detecção de comunidade (greedy modularity
#: não depende de semente; valor mantido por paridade com os demais módulos).
RANDOM_STATE = 42

#: Grão das colunas de auditoria persistidas (padrão Silver/Gold).
COLUNAS_AUDITORIA = [
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

#: Similaridade abaixo desse valor não é persistida em politician_similarity.
SIMILARIDADE_MINIMA = 1e-9

#: DDL das tabelas vazias do contrato `ml_staging` (dbt consome source mesmo
#: sem linhas — ADR-026; schema.yml testa FK sobre estas tabelas no build de
#: Fase 1). Tipos espelham o que o `CREATE TABLE AS SELECT` do lote produz.
_DDL_VAZIO = {
    "ml_staging.network_edges": (
        "CREATE TABLE ml_staging.network_edges ("
        " id_parlamentar bigint, id_fornecedor bigint, periodo bigint,"
        " valor_total double, run_id varchar, pipeline_version varchar,"
        " execution_timestamp varchar, source_version varchar)"
    ),
    "ml_staging.network_nodes": (
        "CREATE TABLE ml_staging.network_nodes ("
        " id_no bigint, tipo_no varchar, periodo bigint, pagerank double,"
        " degree_centrality double, comunidade_id bigint, run_id varchar,"
        " pipeline_version varchar, execution_timestamp varchar,"
        " source_version varchar)"
    ),
    "ml_staging.politician_similarity": (
        "CREATE TABLE ml_staging.politician_similarity ("
        " id_parlamentar_a bigint, id_parlamentar_b bigint, periodo bigint,"
        " num_fornecedores_compartilhados bigint, similaridade double,"
        " run_id varchar, pipeline_version varchar, execution_timestamp varchar,"
        " source_version varchar)"
    ),
}


def no_parlamentar(id_parlamentar: int) -> str:
    """Chave do nó parlamentar no grafo (namespace próprio, ADR-030)."""
    return f"{NO_PARLAMENTAR}{id_parlamentar}"


def no_fornecedor(id_fornecedor: int) -> str:
    """Chave do nó fornecedor no grafo (namespace próprio, ADR-030)."""
    return f"{NO_FORNECEDOR}{id_fornecedor}"


def _id_do_no(no: str) -> int:
    """Extrai o id numérico a partir de uma chave de nó (`p:12` → 12)."""
    return int(no.split(":", 1)[1])


def _tipo_do_no(no: str) -> str:
    """Deriva `tipo_no` (`parlamentar`/`fornecedor`) a partir da chave do nó."""
    return TIPO_PARLAMENTAR if no.startswith(NO_PARLAMENTAR) else TIPO_FORNECEDOR


def construir_grafo(
    fatos: pd.DataFrame,
    *,
    coluna_valor: str = "valor_liquido",
    coluna_parlamentar: str = "id_parlamentar",
    coluna_fornecedor: str = "id_fornecedor",
):
    """Constrói o grafo bipartido parlamentar↔fornecedor de um período.

    Arestas agregadas: para cada par `(parlamentar, fornecedor)` o peso é a
    soma do valor gasto no período (`v_{p,f}`, ADR-030). Despesas sem
    fornecedor resolvido (`NULL`) não geram aresta — o relacionamento exige
    as duas pontas.

    Args:
        fatos: DataFrame no grão de fato (uma linha por despesa), já filtrado
            para o período do grafo.
        coluna_valor / coluna_parlamentar / coluna_fornecedor: Colunas
            operacionais de valor e chaves naturais.

    Returns:
        `networkx.Graph` bipartido com peso de aresta `valor_total`.
    """
    import networkx as nx

    grafo = nx.Graph()
    if fatos is None or fatos.empty or coluna_fornecedor not in fatos.columns:
        return grafo

    trabalho = fatos.dropna(subset=[coluna_parlamentar, coluna_fornecedor]).copy()
    if trabalho.empty:
        return grafo

    trabalho[coluna_valor] = pd.to_numeric(trabalho[coluna_valor], errors="coerce")
    agregado = (
        trabalho.groupby([coluna_parlamentar, coluna_fornecedor])[coluna_valor]
        .sum()
        .reset_index()
    )
    for _, linha in agregado.iterrows():
        p = no_parlamentar(int(linha[coluna_parlamentar]))
        f = no_fornecedor(int(linha[coluna_fornecedor]))
        grafo.add_edge(p, f, valor_total=float(linha[coluna_valor]))
    return grafo


def calcular_pagerank(grafo) -> dict[str, float]:
    """PageRank do grafo bipartido (ADR-027.5, ADR-030.1).

    Calculado sobre o grafo **completo do período** — o valor de um nó
    depende da estrutura global da rede, jamais de subgrafo. Determinístico
    por construção (grafo + parâmetros fixos).

    Args:
        grafo: `networkx.Graph` com peso `valor_total` nas arestas.

    Returns:
        Dict `{chave_no: pagerank}`.
    """
    import networkx as nx

    if grafo.number_of_nodes() == 0:
        return {}
    return dict(
        nx.pagerank(
            grafo,
            alpha=PAGERANK_ALFA,
            tol=PAGERANK_TOL,
            weight="valor_total",
        )
    )


def calcular_centralidade_grau(grafo) -> dict[str, float]:
    """Centralidade de grau (`degree centrality`) dos nós do grafo."""
    import networkx as nx

    return dict(nx.degree_centrality(grafo))


def detectar_comunidades(grafo) -> dict[str, int]:
    """Comunidades do período via `greedy_modularity_communities` (NetworkX).

    Retorna um dict `{chave_no: comunidade_id}` com identificadores
    determinísticos (ordenação por menor chave de nó de cada comunidade),
    permitindo reprodução por `run_id` (RF-12).

    Args:
        grafo: `networkx.Graph` ponderado por `valor_total`.

    Returns:
        Dict `{chave_no: int}` com o `comunidade_id`.
    """
    import networkx as nx

    if grafo.number_of_nodes() == 0:
        return {}
    comunidades = sorted(
        nx.community.greedy_modularity_communities(
            grafo, weight="valor_total"
        ),
        key=lambda c: min(c),
    )
    rotulos: dict[str, int] = {}
    for indice, comunidade in enumerate(comunidades):
        for no in comunidade:
            rotulos[no] = indice
    return rotulos


def similaridade_parlamentares(
    grafo,
    *,
    coluna_valor: str = "valor_total",
) -> pd.DataFrame:
    """Similaridade entre parlamentares por sobreposição de fornecedores (§7).

    Para cada par de parlamentares `(a, b)` (a < b) que compartilha ao menos
    um fornecedor, computa a similaridade de cosseno entre os vetores de
    valor gasto por fornecedor no período. Pares sem sobreposição de
    fornecedores (similaridade 0) não são persistidos — os registros
    representam relacionamento efetivo de padrão de gasto (CU-08).

    Args:
        grafo: `networkx.Graph` bipartido com peso `valor_total`.
        coluna_valor: Atributo de peso da aresta.

    Returns:
        DataFrame com `id_parlamentar_a`, `id_parlamentar_b`,
        `num_fornecedores_compartilhados` e `similaridade`, ordenado por
        (a, b) — determinístico.
    """
    import networkx as nx

    if grafo.number_of_nodes() == 0:
        return pd.DataFrame(
            columns=[
                "id_parlamentar_a",
                "id_parlamentar_b",
                "num_fornecedores_compartilhados",
                "similaridade",
            ]
        )

    fornecedores_por_parlamentar: dict[int, dict[int, float]] = {}
    for no_a, no_b, dados in grafo.edges(data=True):
        # Grafo não-direcionado: a orientação da aresta no iterador é arbitrária
        # — normaliza para (parlamentar, fornecedor) pelo prefixo do nó.
        if no_b.startswith(NO_PARLAMENTAR) and no_a.startswith(NO_FORNECEDOR):
            no_a, no_b = no_b, no_a
        id_p = _id_do_no(no_a)
        id_f = _id_do_no(no_b)
        vetor = fornecedores_por_parlamentar.setdefault(id_p, {})
        vetor[id_f] = float(dados.get(coluna_valor, 0.0))

    linhas: list[dict] = []
    ids = sorted(fornecedores_por_parlamentar)
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            vetor_a = fornecedores_por_parlamentar[id_a]
            vetor_b = fornecedores_por_parlamentar[id_b]
            compartilhados = sorted(set(vetor_a) & set(vetor_b))
            if not compartilhados:
                continue
            num = len(compartilhados)
            produtos = [vetor_a[f] * vetor_b[f] for f in compartilhados]
            norm_a = np.sqrt(sum(v * v for v in vetor_a.values()))
            norm_b = np.sqrt(sum(v * v for v in vetor_b.values()))
            if not norm_a or not norm_b:
                continue
            similaridade = float(sum(produtos) / (norm_a * norm_b))
            if similaridade < SIMILARIDADE_MINIMA:
                continue
            linhas.append(
                {
                    "id_parlamentar_a": id_a,
                    "id_parlamentar_b": id_b,
                    "num_fornecedores_compartilhados": num,
                    "similaridade": similaridade,
                }
            )
    if not linhas:
        return pd.DataFrame(
            columns=[
                "id_parlamentar_a",
                "id_parlamentar_b",
                "num_fornecedores_compartilhados",
                "similaridade",
            ]
        )
    return pd.DataFrame(linhas).sort_values(
        ["id_parlamentar_a", "id_parlamentar_b"]
    ).reset_index(drop=True)


def _periodos_do_fato(fatos: pd.DataFrame, coluna_data: str = "data_sk") -> list[int]:
    """Anos distintos presentes no fato (deriva de `data_sk` YYYYMMDD)."""
    if fatos is None or fatos.empty:
        return []
    anos = sorted({int(str(int(ts))[:4]) for ts in fatos[coluna_data].dropna().unique()})
    return anos


def _df_arestas_do_periodo(
    grafo,
    ano: int,
    run_id: str,
    pipeline_version: str,
    execution_timestamp: str,
    source_version: str,
) -> pd.DataFrame:
    """Perspectiva tabular das arestas (`network_edges`) para o período."""
    linhas = []
    for no_a, no_b, dados in grafo.edges(data=True):
        # Orientação normalizada (parlamentar, fornecedor) — grafo não-direcionado.
        if no_b.startswith(NO_PARLAMENTAR) and no_a.startswith(NO_FORNECEDOR):
            no_a, no_b = no_b, no_a
        linhas.append(
            {
                "id_parlamentar": _id_do_no(no_a),
                "id_fornecedor": _id_do_no(no_b),
                "periodo": ano,
                "valor_total": float(dados.get("valor_total", 0.0)),
            }
        )
    df = pd.DataFrame(linhas)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "id_parlamentar",
                "id_fornecedor",
                "periodo",
                "valor_total",
            ]
        )
    return _completar_auditoria(
        df, run_id, pipeline_version, execution_timestamp, source_version
    )


def _df_nos_do_periodo(
    grafo,
    ano: int,
    pagerank: dict[str, float],
    centralidade: dict[str, float],
    comunidades: dict[str, int],
    run_id: str,
    pipeline_version: str,
    execution_timestamp: str,
    source_version: str,
) -> pd.DataFrame:
    """Perspectiva tabular dos nós (`network_nodes`) para o período."""
    linhas = []
    for no in grafo.nodes():
        linhas.append(
            {
                "id_no": _id_do_no(no),
                "tipo_no": _tipo_do_no(no),
                "periodo": ano,
                "pagerank": float(pagerank.get(no, 0.0)),
                "degree_centrality": float(centralidade.get(no, 0.0)),
                "comunidade_id": comunidades.get(no),
            }
        )
    df = pd.DataFrame(linhas)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "id_no",
                "tipo_no",
                "periodo",
                "pagerank",
                "degree_centrality",
                "comunidade_id",
            ]
        )
    return _completar_auditoria(
        df, run_id, pipeline_version, execution_timestamp, source_version
    )


def _completar_auditoria(
    df: pd.DataFrame,
    run_id: str,
    pipeline_version: str,
    execution_timestamp: str,
    source_version: str,
) -> pd.DataFrame:
    """Reordena para [colunas de negócio] + [auditoria] (padrão Silver/Gold)."""
    colunas_negocio = [c for c in df.columns if c not in COLUNAS_AUDITORIA]
    return df.assign(
        run_id=run_id,
        pipeline_version=pipeline_version,
        execution_timestamp=execution_timestamp,
        source_version=source_version,
    )[colunas_negocio + COLUNAS_AUDITORIA]


def _conectar_duckdb(db_path: str | None = None):
    """Abre uma conexão DuckDB no caminho de `DUCKDB_DATABASE_PATH`."""
    import duckdb

    from pipeline.config import get_env

    return duckdb.connect(db_path or get_env().duckdb_database_path)


def _registrar_alerta_custo(num_arestas: int, num_nodes: int) -> None:
    """Disjuntor de custo do grafo (ADR-030.3) — alerta SEM bloquear.

    No limite (`rede.limite_arestas_recorte`), registra alerta no DQ Report;
    o build segue. Para o futuro, o crescimento persistente do volume acima
    do limite é insumo para ADR de superseding (reavaliar incremental).
    """
    limite = get_analytics().rede.limite_arestas_recorte
    if num_arestas > limite:
        logger.warning(
            "rede_volume_acima_do_limite_recorte",
            arestas=num_arestas,
            nos=num_nodes,
            limite_arestas_recorte=limite,
            acao="alerta no DQ Report sem bloquear — reavaliar incremental via ADR de superseding (ADR-030.3)",
        )


def escrever_rede_duckdb(
    arestas: pd.DataFrame,
    nos: pd.DataFrame,
    similaridades: pd.DataFrame,
    run_id: str,
    *,
    db_path: str | None = None,
    pipeline_version: str | None = None,
    source_version: str = "",
) -> None:
    """Persiste `ml_staging.network_*` (ADR-026/030, recálculo total).

    Substitui íntegramente as três tabelas do staging por execução
    (single-writer DuckDB) — recálculo total chaveado por `(run_id,
    periodo)` (ADR-030.1). Tabelas vazias são criadas mesmo sem dados, para
    manter o contrato dbt estável.

    Args:
        arestas: DataFrame de `network_edges`.
        nos: DataFrame de `network_nodes`.
        similaridades: DataFrame de `politician_similarity`.
        run_id: Identificador da execução.
        db_path: Caminho DuckDB alternativo (testes).
        pipeline_version: Versão do pipeline; padrão lido de `pyproject.toml`.
        source_version: Versão da fonte do lote.
    """
    import duckdb

    from pipeline.config import get_pipeline_version

    pipeline_version = pipeline_version or get_pipeline_version()
    agora = datetime.now(timezone.utc).isoformat()
    # Completa colunas de auditoria (idempotente: frames já completados pelos
    # `_df_*_do_periodo` são apenas reordenados) — mesmo contrato do
    # `escrever_expense_outliers_duckdb` (ADR-026).
    arestas = _completar_auditoria(
        arestas, run_id, pipeline_version, agora, source_version
    )
    nos = _completar_auditoria(nos, run_id, pipeline_version, agora, source_version)
    similaridades = _completar_auditoria(
        similaridades, run_id, pipeline_version, agora, source_version
    )
    # Alerta de custo antes da persistência (ADR-030.3, sem bloquear).
    _registrar_alerta_custo(
        num_arestas=len(arestas) if not arestas.empty else 0,
        num_nodes=len(nos) if not nos.empty else 0,
    )

    con = _conectar_duckdb(db_path)
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS ml_staging")
        _gravar_tabela(con, "ml_staging.network_edges", arestas)
        _gravar_tabela(con, "ml_staging.network_nodes", nos)
        _gravar_tabela(con, "ml_staging.politician_similarity", similaridades)
        logger.info(
            "ml_staging_rede_gravado",
            run_id=run_id,
            arestas=len(arestas),
            nos=len(nos),
            similaridades=len(similaridades),
            db_path=db_path or "padrao",
        )
    finally:
        con.close()


def _gravar_tabela(con, tabela: str, df: pd.DataFrame) -> None:
    """Cria/recria uma tabela do staging com o conteúdo do lote corrente.

    Lote vazio (ou DataFrame sem colunas) ainda cria a tabela VAZIA com o
    schema do contrato — o dbt consome a source mesmo sem linhas e os testes
    de integridade referencial do `schema.yml` dependem da tabela existir.
    """
    con.execute(f"DROP TABLE IF EXISTS {tabela}")
    if df is None or df.empty or df.shape[1] == 0:
        con.execute(_DDL_VAZIO.get(tabela, ""))
        return
    con.register("tmp_rede", df)
    con.execute(f"CREATE TABLE {tabela} AS SELECT * FROM tmp_rede")


def executar_carga_ml_rede(
    fatos: pd.DataFrame,
    run_id: str,
    *,
    coluna_data: str = "data_sk",
    db_path: str | None = None,
    source_version: str = "",
) -> dict[str, int]:
    """Fluxo completo da Onda 3: grafo + PageRank/comunidades + staging.

    Para cada período (ano) do fato, reconstrói o grafo bipartido completo,
    calcula PageRank/centralidade/comunidades/similaridade e persiste o lote
    em `ml_staging.network_*` (ADR-026 single-writer). Espelha a execução da
    futura task `executar_ml_rede` da DAG da Sprint 5 (ADR-030.1).

    Args:
        fatos: DataFrame `fact_despesa` (grão despesa, com `coluna_data`).
        run_id: Identificador da execução.
        coluna_data: Coluna de data (data_sk YYYYMMDD) para derivar período.
        db_path: Caminho DuckDB alternativo.
        source_version: Versão da fonte do lote.

    Returns:
        Dict com a contagem por tabela gravada (`edges`/`nodes`/`similarities`).
    """
    from pipeline.config import get_pipeline_version

    pipeline_version = get_pipeline_version()
    agora = datetime.now(timezone.utc).isoformat()

    dfs_arestas: list[pd.DataFrame] = []
    dfs_nos: list[pd.DataFrame] = []
    dfs_similaridades: list[pd.DataFrame] = []

    for ano in _periodos_do_fato(fatos, coluna_data=coluna_data):
        do_ano = fatos[fatos[coluna_data].astype(str).str.startswith(str(ano))]
        grafo = construir_grafo(do_ano)
        pagerank = calcular_pagerank(grafo)
        centralidade = calcular_centralidade_grau(grafo)
        comunidades = detectar_comunidades(grafo)

        if grafo.number_of_edges() > 0:
            dfs_arestas.append(
                _df_arestas_do_periodo(
                    grafo,
                    ano,
                    run_id,
                    pipeline_version,
                    agora,
                    source_version,
                )
            )
            similaridades_do_periodo = similaridade_parlamentares(grafo)
            if not similaridades_do_periodo.empty:
                similaridades_do_periodo.insert(0, "periodo", ano)
                dfs_similaridades.append(
                    _completar_auditoria(
                        similaridades_do_periodo,
                        run_id,
                        pipeline_version,
                        agora,
                        source_version,
                    )
                )
        dfs_nos.append(
            _df_nos_do_periodo(
                grafo,
                ano,
                pagerank,
                centralidade,
                comunidades,
                run_id,
                pipeline_version,
                agora,
                source_version,
            )
        )

    arestas = pd.concat(dfs_arestas, ignore_index=True) if dfs_arestas else pd.DataFrame()
    nos = pd.concat(dfs_nos, ignore_index=True) if dfs_nos else pd.DataFrame()
    similaridades = (
        pd.concat(dfs_similaridades, ignore_index=True)
        if dfs_similaridades
        else pd.DataFrame()
    )

    escrever_rede_duckdb(
        arestas,
        nos,
        similaridades,
        run_id,
        db_path=db_path,
        pipeline_version=pipeline_version,
        source_version=source_version,
    )
    return {
        "edges": len(arestas),
        "nodes": len(nos),
        "similarities": len(similaridades),
    }


def network_no_registry(registry_path: str | None = None) -> bool:
    """Confere se a feature `network_influence_score` está registrada (ADR-028).

    O `network_influence_score` (ADR-027.5, alimentado pelo PageRank deste
    módulo) é a feature da Feature Store correspondente à Onda 3 — sem
    registro, o contrato ADR-028 estaria quebrado. Não bloqueia a execução.

    Args:
        registry_path: Caminho alternativo do registry (para testes).

    Returns:
        `True` se a feature estiver registrada como categoria `ml`.
    """
    from pathlib import Path

    registry = carregar_registry(Path(registry_path) if registry_path else None)
    feature = registry.obter("network_influence_score")
    ok = feature is not None and feature.categoria.value == "ml"
    logger.info(
        "network_influence_score_registrada",
        registrada=ok,
        consumidores=feature.consumidores if feature else [],
    )
    return ok