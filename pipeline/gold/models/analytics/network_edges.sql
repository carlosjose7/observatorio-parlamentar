-- network_edges — arestas do grafo bipartido parlamentar↔fornecedor (ADR-030, Onda 3).
-- Grão: (id_parlamentar, id_fornecedor, periodo) por run. `valor_total` é o
-- peso da aresta `v_{p,f}` — valor agregado do período (ADR-030/030.1).
--
-- Fonte: `ml_staging.network_edges` — escrita EXCLUSIVA por pipeline/network.py
-- (ADR-026, Opção A: Python single-writer no staging; o dbt apenas consome
-- como source e materializa esta Gold, ADR-021/026.2). Recálculo total por
-- execução, chaveado por `(run_id, periodo)` (ADR-030.1). O mesmo princípio
-- ADR-018 (só promovido alimenta a analítica) é garantido por `exists` contra
-- as dimensões — NÃO por inner join: `dim_parlamentar` é SCD2 (ADR-020), com
-- várias versões por `id_parlamentar`, e um inner join pelo id natural
-- multiplicaria as arestas (mesma lógica anti-join do macro `fk_orphan_pct`).

select
    ne.id_parlamentar,
    ne.id_fornecedor,
    ne.periodo,
    ne.valor_total,
    ne.run_id,
    ne.pipeline_version,
    ne.execution_timestamp,
    ne.source_version
from {{ source('ml_staging', 'network_edges') }} ne
where exists (
    select 1 from {{ ref('dim_parlamentar') }} dp
    where dp.id_parlamentar = ne.id_parlamentar
)
and exists (
    select 1 from {{ ref('dim_fornecedor') }} df
    where df.id_fornecedor = ne.id_fornecedor
)