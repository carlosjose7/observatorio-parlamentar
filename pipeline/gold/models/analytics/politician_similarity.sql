-- politician_similarity — similaridade de cosseno entre parlamentares (ADR-030.5, Onda 3).
-- Grão: (id_parlamentar_a, id_parlamentar_b, periodo) por run, ordem canônica
-- a < b. Pares sem sobreposição de fornecedor (similaridade 0) não são
-- persistidos no staging — o registro representa relacionamento EFETIVO de
-- padrão de gasto (CU-08).
--
-- Fonte: `ml_staging.politician_similarity` — escrita EXCLUSIVA por
-- pipeline/network.py (ADR-026, Opção A: Python single-writer no staging; o
-- dbt apenas consome como source e materializa esta Gold, ADR-021/026.2).
-- Deriva do mesmo grafo do run corrente (comunidades/similaridade,
-- ADR-030.5). `exists` contra `dim_parlamentar` garante que só promovido
-- alimenta a analítica (ADR-018; sem inner join por SCD2 — `dim_parlamentar`
-- tem várias versões por id, e um inner join multiplicaria os pares).

select
    ps.id_parlamentar_a,
    ps.id_parlamentar_b,
    ps.periodo,
    ps.num_fornecedores_compartilhados,
    ps.similaridade,
    ps.run_id,
    ps.pipeline_version,
    ps.execution_timestamp,
    ps.source_version
from {{ source('ml_staging', 'politician_similarity') }} ps
where exists (
    select 1 from {{ ref('dim_parlamentar') }} dpa
    where dpa.id_parlamentar = ps.id_parlamentar_a
)
and exists (
    select 1 from {{ ref('dim_parlamentar') }} dpb
    where dpb.id_parlamentar = ps.id_parlamentar_b
)