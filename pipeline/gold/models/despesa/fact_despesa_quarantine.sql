-- fact_despesa_quarantine — despesas NÃO promovidas a fact_despesa
-- (padrão ADR-017/ADR-018), com motivo explícito para auditoria:
--
--   parlamentar_nao_resolvido  — identidade não casou com dim_parlamentar.
--   parlamentar_ambiguo        — mais de um parlamentar vigente na data.
--   parlamentar_fora_cobertura — identidade conhecida, sem versão vigente na
--                                data_documento.
--   data_nao_resolvida         — data_documento inválida/ausente.
--   fornecedor_nao_resolvido   — parlamentar resolvido, mas a FK de fornecedor
--                                não resolveu (documento indefinido/inválido
--                                ou lag de dim_fornecedor, ADR-022.3a).
--   orgao_nao_resolvido        — fonte não mapeia para sigla de dim_orgao
--                                (lag da dimensão, ADR-022.1).
--   categoria_nao_resolvida    — tipo_despesa ausente → sem cod_tipo.
--   data_nao_resolvida (base)  — data_documento fora do horizonte de dim_data.
--
-- `id_parlamentar` permanece sempre NULL quando a despesa ficou de fora pela
-- identidade parlamentar; quando ela resolveu mas a quarentena é por outra FK
-- (fornecedor/órgão/categoria/data), a identidade NÃO se perde — a linha sai
-- com os FKs preenchidos, reconstruível pela chave natural (fonte,
-- cod_documento). Nenhum registro de despesa é descartado em silêncio.

with base as (
    select
        s.fonte,
        s.cod_documento,
        dp.id_parlamentar,
        dp.surrogate_key,
        eao.id_orgao,
        dfo.id_fornecedor,
        cat.cod_tipo,
        dd.data_sk,
        s.valor_liquido,
        s.valor_glosa,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version,
        case
            when dfo.id_fornecedor is null then 'fornecedor_nao_resolvido'
            when eao.id_orgao is null then 'orgao_nao_resolvido'
            when cat.cod_tipo is null then 'categoria_nao_resolvida'
            when dd.data_sk is null then 'data_nao_resolvida'
        end as motivo_quarentena
    from {{ source('silver', 'silver_despesa') }} s
    inner join {{ ref('desp_parlamento') }} dp using (fonte, cod_documento)
    left join {{ ref('desp_orgao') }} eao using (fonte, cod_documento)
    left join {{ ref('desp_fornecedor') }} dfo using (fonte, cod_documento)
    left join {{ ref('dim_categoria_despesa') }} cat
        on cat.cod_tipo = substr(md5(upper(s.tipo_despesa)), 1, 12)
    left join {{ ref('dim_data') }} dd
        on dd.data_sk = cast(strftime(cast(s.data_documento as date), '%Y%m%d') as bigint)
),

parlamentar_nao_resolvida as (
    select
        s.fonte,
        s.cod_documento,
        cast(null as bigint) as id_parlamentar,
        cast(null as bigint) as surrogate_key,
        cast(null as bigint) as id_orgao,
        cast(null as bigint) as id_fornecedor,
        cast(null as varchar) as cod_tipo,
        cast(null as bigint) as data_sk,
        s.valor_liquido,
        s.valor_glosa,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version,
        q.motivo as motivo_quarentena
    from {{ source('silver', 'silver_despesa') }} s
    inner join {{ ref('desp_parlamento_quarantine') }} q using (fonte, cod_documento)
)

select
    fonte,
    cod_documento,
    id_parlamentar,
    surrogate_key,
    id_orgao,
    id_fornecedor,
    cod_tipo,
    data_sk,
    valor_liquido,
    valor_glosa,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version,
    motivo_quarentena
from base
where motivo_quarentena is not null
union all
select
    fonte,
    cod_documento,
    id_parlamentar,
    surrogate_key,
    id_orgao,
    id_fornecedor,
    cod_tipo,
    data_sk,
    valor_liquido,
    valor_glosa,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version,
    motivo_quarentena
from parlamentar_nao_resolvida