-- dim_unidade_gestora — Unidades Gestoras observadas na fonte CGU (ADR-010).
--
-- A v1 do projeto manteve esta dimensão schema-only (BACKLOG, Onda 2): sem
-- requisito funcional, nenhuma fonte tinha sido materializada. O `fact_cartao_cpgf`
-- muda isso: a própria CGU entrega `unidadeGestora.codigo`/`nome` nativamente por
-- transação (ADR-010/ADR-012) e o contrato exige `id_unidade_gestora` NOT NULL —
-- então a dimensão nasce populada pelas UGs do grão de cartão.
--
-- Chave natural: (fonte_origem, codigo) — nunca codigo isolado (ADR-010.3).
-- `fonte_origem = 'CGU'`; `gestao` é específico do SIAFI e permanece NULL.
-- O órgão é resolvido por JOIN em dim_orgao pela sigla `EX` (Poder Executivo
-- genérico, ADR-025) — sem literal de id (ADR-022.1); se a sigla sumir da
-- dimensão, `id_orgao` sai NULL e a UG fica órfã (pega pelo relationships).

{{ config(materialized='table') }}

with ugs as (
    select
        unidade_gestora_codigo as codigo,
        max(unidade_gestora_nome) as nome
    from {{ source('silver', 'silver_cartao') }}
    where unidade_gestora_codigo is not null
    group by unidade_gestora_codigo
)

select
    row_number() over (
        order by codigo
    ) as id_unidade_gestora,
    u.codigo,
    cast(null as varchar) as gestao,
    u.nome,
    o.id_orgao,
    'CGU' as fonte_origem
from ugs u
left join (
    select sigla, id_orgao
    from {{ ref('dim_orgao') }}
) o
    on o.sigla = 'EX'