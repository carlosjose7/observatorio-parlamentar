-- em_autor_classificacao — classificação de autoria de emenda (ADR-017).
--
-- Modelo efêmero compartilhado por `emenda_autor` e `emenda_autor_quarantine`.
-- Implementa a política de resolução de autor do ADR-017 de forma
-- determinística, sem duplicar regra de negócio entre os dois modelos:
--
--  1. `tipo_emenda` é o discriminador primário de autoria colegiada
--     (`emenda_tipos_colegiados`, var do dbt_project; valores reais ainda
--     a confirmar no catálogo — item de seguimento registrado no BACKLOG).
--  2. Para tipo individual, matching **exato** do `nome_autor_normalizado`
--     (uppercase + remoção de acento, mesma regra de `pipeline.normalize`)
--     contra `dim_parlamentar`, restrito à versão **vigente no ano da
--     emenda** — intervalo `[effective_date, end_date)` que contém alguma
--     data do ano da emenda (vigência-por-ano, ADR-020). Nunca se grava
--     `id_parlamentar` por critério arbitrário (ADR-017.3.c).
--  3. Classificação:
--     - colegiada                              → `autor_coleiado`
--     - 1 parlamentar vigente casado        → `autor_resolvido`
--     - >1 parlamentares vigentes casados   → `autor_ambiguo`
--     - 0 casados, nome existe no cadastro  → `autor_fora_cobertura`
--       (pessoa é parlamentar conhecido, mas sem cobertura no ano da emenda
--       — ex.: mandato em outro órgão ou sem snapshot capturado)
--     - 0 casados e nome desconhecido      → `autor_nao_resolvido`
--
-- Emendas colegiadas nunca passam por matching individual (ADR-017).

{{ config(materialized='ephemeral') }}

with emendas as (
    select
        ano,
        codigo_emenda,
        tipo_emenda,
        nome_autor,
        {{ nome_normalizado('nome_autor') }} as nome_autor_normalizado
    from {{ source('silver', 'silver_emenda') }}
),

marcadas as (
    select
        ano,
        codigo_emenda,
        tipo_emenda,
        nome_autor,
        nome_autor_normalizado,
        case
            when {{ nome_normalizado('tipo_emenda') }} in (
                {%- for t in var('emenda_tipos_colegiados') %}
                '{{ t }}'{{ ',' if not loop.last }}
                {%- endfor %}
            ) then true
            else false
        end as eh_colegiado
    from emendas
),

-- Matching (ADR-017.3.b): versão de dim_parlamentar cujo intervalo
-- [effective_date, end_date) contém alguma data do ano da emenda.
candidatos as (
    select
        m.ano,
        m.codigo_emenda,
        d.id_parlamentar,
        d.surrogate_key
    from marcadas m
    inner join {{ ref('dim_parlamentar') }} d
        on m.nome_autor_normalizado = d.nome_normalizado
        and d.effective_date <= make_date(m.ano, 12, 31)
        and (
            d.end_date is null
            or d.end_date > make_date(m.ano, 1, 1)
        )
),

contagens as (
    select
        m.ano,
        m.codigo_emenda,
        count(distinct c.id_parlamentar) as n_candidatos,
        min(c.id_parlamentar) as id_parlamentar,
        min(c.surrogate_key) as surrogate_key
    from marcadas m
    left join candidatos c using (ano, codigo_emenda)
    group by m.ano, m.codigo_emenda
),

nomes_conhecidos as (
    select distinct {{ nome_normalizado('nome') }} as nome_normalizado
    from {{ ref('dim_parlamentar') }}
)

select
    m.ano,
    m.codigo_emenda,
    m.tipo_emenda,
    m.nome_autor,
    m.nome_autor_normalizado,
    case
        when m.eh_colegiado then 'autor_colegiado'
        when cg.n_candidatos > 1 then 'autor_ambiguo'
        when cg.n_candidatos = 1 then 'autor_resolvido'
        when m.nome_autor_normalizado is not null
             and m.nome_autor_normalizado in (
                 select nc.nome_normalizado from nomes_conhecidos nc
             )
            then 'autor_fora_cobertura'
        else 'autor_nao_resolvido'
    end as autor_status,
    cg.n_candidatos,
    cg.id_parlamentar,
    cg.surrogate_key
from marcadas m
left join contagens cg using (ano, codigo_emenda)