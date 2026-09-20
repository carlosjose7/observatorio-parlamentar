-- fact_presenca — presença parlamentar por sessão (ADR-058, ADR-012).
--
-- Grão: 1 linha por (id_parlamentar, id_evento). Duas origens:
--   - `presente`: linha do arquivo em lote com parlamentar resolvido
--     (ponte `presenca_parlamento_classificacao`, status resolvido).
--   - `ausente`: DERIVADO — parlamentar com versão vigente na data de um
--     evento Encerrada sem linha de presença (a fonte é só-presença; falta
--     justificada não existe nela, então `is_ausencia_injustificada` nasce
--     NULL — desconhecido, não false — ADR-058 Decisão 3).
--
-- FKs (NOT NULL, ADR-010/012): id_parlamentar + surrogate_key da versão
-- exata casada (auditoria, paridade com fact_despesa/fact_emenda),
-- id_evento, id_orgao (CD, via sigla — ADR-022.1), data_sk (dim_data).
-- Contrato em pipeline/gold.py:FactPresenca.

with resolvidos as (
    select *
    from {{ ref('presenca_parlamento_classificacao') }}
    where status = 'resolvido'
),

presentes as (
    select
        id_parlamentar,
        surrogate_key,
        id_evento,
        id_orgao,
        data_sk,
        'presente' as resultado,
        cast(null as boolean) as is_ausencia_injustificada,
        run_id,
        pipeline_version,
        execution_timestamp,
        source_version
    from resolvidos
),

-- Parlamentares vigentes (Câmara) na data de cada evento Encerrada.
vigentes_evento as (
    select distinct
        dp.id_parlamentar,
        dp.surrogate_key,
        e.id_evento,
        o.id_orgao,
        cast(strftime(cast(e.data_inicio as date), '%Y%m%d') as bigint) as data_sk,
        e.run_id,
        e.pipeline_version,
        e.execution_timestamp,
        e.source_version
    from {{ ref('dim_parlamentar') }} dp
    inner join {{ source('silver', 'silver_evento') }} e
        on e.situacao_normalizada = 'encerrada'
        and e.data_inicio is not null
        and dp.fonte = 'camara'
        and dp.effective_date <= cast(e.data_inicio as date)
        and (
            dp.end_date is null
            or cast(e.data_inicio as date) < cast(dp.end_date as date)
        )
    inner join {{ ref('dim_orgao') }} o on o.sigla = 'CD'
    inner join {{ ref('dim_data') }} dd
        on dd.data_sk = cast(strftime(cast(e.data_inicio as date), '%Y%m%d') as bigint)
),

ausentes as (
    select
        v.id_parlamentar,
        v.surrogate_key,
        v.id_evento,
        v.id_orgao,
        v.data_sk,
        'ausente' as resultado,
        cast(null as boolean) as is_ausencia_injustificada,
        v.run_id,
        v.pipeline_version,
        v.execution_timestamp,
        v.source_version
    from vigentes_evento v
    where not exists (
        select 1
        from {{ source('silver', 'silver_presenca') }} p
        where p.id_evento = v.id_evento
          and p.id_deputado = v.id_parlamentar
    )
),

unido as (
    select * from presentes
    union all
    select * from ausentes
)

select
    row_number() over (order by id_evento, id_parlamentar) as id_presenca,
    id_parlamentar,
    surrogate_key,
    id_evento,
    id_orgao,
    data_sk,
    resultado,
    is_ausencia_injustificada,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version
from unido
