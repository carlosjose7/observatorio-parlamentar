-- desp_orgao — resolução do órgão da despesa (ADR-010/ADR-022.1).
--
-- Efêmero compartilhado por `fact_despesa` e `fact_despesa_quarantine`: uma
-- despesa pertence a uma casa (Câmara ou Senado), derivada da própria `fonte`
-- da linha de silver_despesa. O `id_orgao` NÃO é literal arbitrário: vem de
-- `dim_orgao` (seed), por JOIN na chave natural `sigla` — `camara`→CD,
-- `senado`→SF (mesmo padrão de `emenda_autor_orgao`, ADR-022.1).
--
-- Se a fonte não mapeia para uma sigla conhecida (fonte inesperada ou ausência
-- de linha em dim_orgao — lag da dimensão), `id_orgao` sai NULL e a despesa vai
-- para a quarentena por construção (ADR-018, motivo `orgao_nao_resolvido`) —
-- nunca NULL silencioso passando batido pelo not_null do schema.yml.

{{ config(materialized='ephemeral') }}

select
    a.fonte,
    a.cod_documento,
    a.id_parlamentar,
    a.surrogate_key,
    o.id_orgao
from {{ ref('desp_parlamento') }} a
left join (
    select sigla, id_orgao
    from {{ ref('dim_orgao') }}
) o
    on o.sigla = case a.fonte
        when 'camara' then 'CD'
        when 'senado' then 'SF'
        else null
    end