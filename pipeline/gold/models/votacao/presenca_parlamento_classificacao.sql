-- presenca_parlamento_classificacao — ponte efêmera presença × parlamentar
-- (ADR-058, padrão ADR-017: modelo efêmero consumido pelo fato e pela
-- quarentena, regra determinística única).
--
-- Classifica cada linha de `silver_presenca` contra a versão de
-- `dim_parlamentar` vigente na data do evento (SCD2, intervalo
-- `[effective_date, end_date)` — nunca `is_current` do momento da execução,
-- ADR-020) e contra o gate "só Encerrada conta" (ADR-058 Decisão 2).
--
-- Status (precedência: evento → parlamentar → data → órgão):
--   resolvido | evento_nao_resolvido | evento_nao_encerrado |
--   parlamentar_nao_resolvido | data_nao_resolvida | orgao_nao_resolvido

{{ config(materialized='ephemeral') }}

with eventos as (
    select
        id_evento,
        cast(data_inicio as date) as data_evento,
        situacao_normalizada,
        run_id,
        pipeline_version,
        execution_timestamp,
        source_version
    from {{ source('silver', 'silver_evento') }}
),

presentes as (
    select id_evento, id_deputado
    from {{ source('silver', 'silver_presenca') }}
),

-- Versão vigente as-of data do evento (Câmara), determinística (rn = 1
-- = effective_date mais recente; SCD2 recomputado não gera sobreposição).
vigentes as (
    select
        p.id_evento,
        p.id_deputado,
        dp.id_parlamentar,
        dp.surrogate_key,
        dp.sigla_partido
    from presentes p
    inner join eventos e on e.id_evento = p.id_evento
    inner join {{ ref('dim_parlamentar') }} dp
        on dp.fonte = 'camara'
        and dp.id_parlamentar = p.id_deputado
        and dp.effective_date <= e.data_evento
        and (dp.end_date is null or e.data_evento < cast(dp.end_date as date))
    qualify row_number() over (
        partition by p.id_evento, p.id_deputado order by dp.effective_date desc
    ) = 1
),

classificados as (
    select
        p.id_evento,
        p.id_deputado,
        e.data_evento,
        v.id_parlamentar,
        v.surrogate_key,
        o.id_orgao,
        cast(strftime(e.data_evento, '%Y%m%d') as bigint) as data_sk,
        case
            when e.id_evento is null then 'evento_nao_resolvido'
            when e.situacao_normalizada is distinct from 'encerrada' then 'evento_nao_encerrado'
            when v.id_parlamentar is null then 'parlamentar_nao_resolvido'
            when dd.data_sk is null then 'data_nao_resolvida'
            when o.id_orgao is null then 'orgao_nao_resolvido'
            else 'resolvido'
        end as status,
        e.run_id,
        e.pipeline_version,
        e.execution_timestamp,
        e.source_version
    from presentes p
    left join eventos e on e.id_evento = p.id_evento
    left join vigentes v
        on v.id_evento = p.id_evento
        and v.id_deputado = p.id_deputado
    left join {{ ref('dim_data') }} dd
        on dd.data_sk = cast(strftime(e.data_evento, '%Y%m%d') as bigint)
    left join {{ ref('dim_orgao') }} o on o.sigla = 'CD'
)

select * from classificados
