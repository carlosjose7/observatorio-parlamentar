-- network_nodes — nós do grafo bipartido com métricas de centralidade (ADR-030, Onda 3).
-- Grão: (id_no, tipo_no, periodo) por run. `pagerank` é o
-- `network_influence_score` cru (ADR-027.5 — normalizado no consumo);
-- `degree_centrality`/`comunidade_id` complementam a análise de rede.
--
-- Fonte: `ml_staging.network_nodes` — escrita EXCLUSIVA por analytics/network/network.py
-- (ADR-026, Opção A: Python single-writer no staging; o dbt apenas consome
-- como source e materializa esta Gold, ADR-021/026.2). Recálculo total por
-- execução, chaveado por `(run_id, periodo)` (ADR-030.1).
--
-- `id_no` NÃO é FK única: o nó é polimórfico — `tipo_no` discrimina se a
-- chave referencia `dim_parlamentar` ou `dim_fornecedor`. A existência do
-- nó na dimensão correta é garantida por `exists` condicionado ao tipo
-- (ADR-018; integridade referencial documentada no schema.yml).

select
    nn.id_no,
    nn.tipo_no,
    nn.periodo,
    nn.pagerank,
    nn.degree_centrality,
    nn.comunidade_id,
    nn.run_id,
    nn.pipeline_version,
    nn.execution_timestamp,
    nn.source_version
from {{ source('ml_staging', 'network_nodes') }} nn
where (
    nn.tipo_no = 'parlamentar'
    and exists (
        select 1 from {{ ref('dim_parlamentar') }} dp
        where dp.id_parlamentar = nn.id_no
    )
)
or (
    nn.tipo_no = 'fornecedor'
    and exists (
        select 1 from {{ ref('dim_fornecedor') }} df
        where df.id_fornecedor = nn.id_no
    )
)