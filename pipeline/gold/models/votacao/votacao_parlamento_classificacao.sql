-- votacao_parlamento_classificacao — ponte efêmera voto × parlamentar
-- (ADR-058, padrão ADR-017: modelo efêmero consumido pelo fato e pela
-- quarentena, regra determinística única).
--
-- Classifica cada linha de `silver_voto` contra a versão de
-- `dim_parlamentar` vigente na data do evento (SCD2 as-of, ADR-020), o gate
-- "só Encerrada conta" (ADR-058 Decisão 2) e a orientação da bancada do
-- parlamentar na mesma versão (insumo do `seguiu_partido`, Decisão 4):
-- orientação vazia/`Liberado` → NULL; voto fora do binário
-- (abstenção/artigo17/obstrução/nao_mapeado) → NULL; senão compara a
-- orientação normalizada (sem acento/caixa) com o voto.
--
-- Status (precedência: votação/evento → parlamentar → data → órgão):
--   resolvido | votacao_sem_evento | evento_nao_encerrado |
--   parlamentar_nao_resolvido | data_nao_resolvida | orgao_nao_resolvido

{{ config(materialized='ephemeral') }}

with votos as (
    select
        id_votacao,
        id_deputado,
        voto_normalizado,
        run_id,
        pipeline_version,
        execution_timestamp,
        source_version
    from {{ source('silver', 'silver_voto') }}
),

votacoes as (
    select
        id_votacao,
        id_evento,
        data_registro
    from {{ source('silver', 'silver_votacao') }}
),

eventos as (
    select
        id_evento,
        cast(data_inicio as date) as data_evento,
        situacao_normalizada
    from {{ source('silver', 'silver_evento') }}
),

base as (
    select
        v.id_votacao,
        v.id_deputado,
        v.voto_normalizado,
        vc.id_evento,
        e.data_evento,
        e.situacao_normalizada,
        v.run_id,
        v.pipeline_version,
        v.execution_timestamp,
        v.source_version
    from votos v
    left join votacoes vc on vc.id_votacao = v.id_votacao
    left join eventos e on e.id_evento = vc.id_evento
),

vigentes as (
    select
        b.id_votacao,
        b.id_deputado,
        dp.id_parlamentar,
        dp.surrogate_key,
        dp.sigla_partido
    from base b
    inner join {{ ref('dim_parlamentar') }} dp
        on dp.fonte = 'camara'
        and dp.id_parlamentar = b.id_deputado
        and dp.effective_date <= b.data_evento
        and (dp.end_date is null or b.data_evento < cast(dp.end_date as date))
    qualify row_number() over (
        partition by b.id_votacao, b.id_deputado order by dp.effective_date desc
    ) = 1
),

classificados as (
    select
        b.id_votacao,
        b.id_evento,
        b.id_deputado,
        b.data_evento,
        b.voto_normalizado,
        vg.id_parlamentar,
        vg.surrogate_key,
        o.id_orgao,
        cast(strftime(b.data_evento, '%Y%m%d') as bigint) as data_sk,
        case
            when lower(trim(coalesce(or_.orientacao_bruta, ''))) in ('', 'liberado')
                then cast(null as boolean)
            when b.voto_normalizado not in ('sim', 'nao')
                then cast(null as boolean)
            when translate(
                lower(trim(or_.orientacao_bruta)),
                'áàâãäåéèêëíìîïóòôõöúùûüç',
                'aaaaaaeeeeiiiiooooouuuuc'
            ) = b.voto_normalizado then true
            else false
        end as seguiu_partido,
        case
            when b.id_evento is null then 'votacao_sem_evento'
            when b.situacao_normalizada is distinct from 'encerrada' then 'evento_nao_encerrado'
            when vg.id_parlamentar is null then 'parlamentar_nao_resolvido'
            when dd.data_sk is null then 'data_nao_resolvida'
            when o.id_orgao is null then 'orgao_nao_resolvido'
            else 'resolvido'
        end as status,
        b.run_id,
        b.pipeline_version,
        b.execution_timestamp,
        b.source_version
    from base b
    left join vigentes vg
        on vg.id_votacao = b.id_votacao
        and vg.id_deputado = b.id_deputado
    left join {{ source('silver', 'silver_orientacao') }} or_
        on or_.id_votacao = b.id_votacao
        and upper(trim(or_.sigla_bancada)) = upper(trim(coalesce(vg.sigla_partido, '')))
    left join {{ ref('dim_data') }} dd
        on dd.data_sk = cast(strftime(b.data_evento, '%Y%m%d') as bigint)
    left join {{ ref('dim_orgao') }} o on o.sigla = 'CD'
)

select * from classificados
