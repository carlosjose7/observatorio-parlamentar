-- risk_scores — scores de risco por parlamentar e o risk_index (ADR-027/029, Onda 4).
-- Grão: (periodo, id_parlamentar) por run. As 5 colunas de score são os
-- scores individuais do ADR-027 JÁ normalizados Min-Max em [0, 1] (feature
-- `minmax`, ADR-028); `risk_index` é a composição ponderada
-- `Σ_i w_i · score_i(p)` com pesos de `config/analytics.yaml → risk.pesos`
-- (ADR-029 — baseline 0.2 uniforme, revisão empírica pós-Sprint 6.5).
--
-- Fonte: `ml_staging.risk_scores` — escrita EXCLUSIVA por analytics/parliamentarians/risk.py
-- (ADR-026, Opção A: Python single-writer no staging; o dbt apenas consome
-- como source e materializa esta Gold, ADR-021/026.2). Recálculo total por
-- execução, chaveado por `(run_id, periodo)`.
--
-- O princípio ADR-018 (só parlamentar promovido alimenta a analítica) é
-- garantido por `exists` contra `dim_parlamentar` — NÃO por inner join:
-- `dim_parlamentar` é SCD2 (ADR-020), com várias versões por `id_parlamentar`,
-- e um inner join pelo id natural multiplicaria as linhas (mesma lógica
-- anti-join do macro `fk_orphan_pct`).

select
    rs.periodo,
    rs.id_parlamentar,
    rs.supplier_concentration_score,
    rs.political_exposure_score,
    rs.supplier_dependency_score,
    rs.expense_anomaly_score,
    rs.network_influence_score,
    rs.risk_index,
    rs.run_id,
    rs.pipeline_version,
    rs.execution_timestamp,
    rs.source_version
from {{ source('ml_staging', 'risk_scores') }} rs
where exists (
    select 1 from {{ ref('dim_parlamentar') }} dp
    where dp.id_parlamentar = rs.id_parlamentar
)