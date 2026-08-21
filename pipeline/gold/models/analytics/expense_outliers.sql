-- expense_outliers — anomalias estatísticas de despesa (ADR-002/§10, Onda 2).
-- Grão: uma despesa anômala — PELO MENOS 2 dos 6 critérios do §10
-- (Z-score > 2.5, Isolation Forest score < -0.1, fornecedor < 3 clientes,
-- empresa < 12 meses, valores idênticos >= 3 no mês, dia sem sessão).
--
-- Fonte: `ml_staging.expense_outliers` — escrita EXCLUSIVA por
-- analytics/anomalies/anomalies.py (ADR-026, Opção A: Python single-writer no staging;
-- o dbt apenas consome como source e materializa esta Gold, ADR-021/026.2).
-- Só as despesas ANÔMALAS (is_anomalia = true) entram na Gold; o staging
-- guarda o avaliado completo para auditoria e para o `expense_anomaly_score`
-- (ADR-027). Inner join com `fact_despesa` garante que só o que foi
-- promovido ao fato alimenta a analítica (mesmo princípio ADR-018).

with anomalias as (
    select
        id_despesa,
        id_parlamentar,
        id_fornecedor,
        data_sk,
        valor_liquido,
        zscore,
        if_score,
        criterio_zscore,
        criterio_if,
        criterio_fornecedor_poucos_clientes,
        criterio_empresa_nova,
        criterio_valores_identicos,
        criterio_dia_sem_sessao,
        num_criterios,
        run_id,
        pipeline_version,
        execution_timestamp,
        source_version
    from {{ source('ml_staging', 'expense_outliers') }}
    where is_anomalia
)

select
    a.id_despesa,
    a.id_parlamentar,
    a.id_fornecedor,
    a.data_sk,
    a.valor_liquido,
    a.zscore,
    a.if_score,
    a.criterio_zscore,
    a.criterio_if,
    a.criterio_fornecedor_poucos_clientes,
    a.criterio_empresa_nova,
    a.criterio_valores_identicos,
    a.criterio_dia_sem_sessao,
    a.num_criterios,
    a.run_id,
    a.pipeline_version,
    a.execution_timestamp,
    a.source_version
from anomalias a
inner join {{ ref('fact_despesa') }} fd on fd.id_despesa = a.id_despesa