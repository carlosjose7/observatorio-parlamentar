-- emenda_autor_orgao — resolução do órgão da emenda (ADR-012/ADR-017/ADR-018).
--
-- Efêmero compartilhado por fact_emenda e fact_emenda_quarantine: uma emenda
-- pertence a uma casa (Câmara ou Senado), derivada da fonte da versão de
-- dim_parlamentar usada no matching. O `id_orgao` NÃO é literal arbitrário:
-- vem de `dim_orgao` (seed), por JOIN na chave natural `sigla` — `camara`→CD,
-- `senado`→SF.
--
-- Se a fonte não mapeia para uma sigla conhecida (fonte inesperada ou ausência
-- de linha em dim_orgao), `id_orgao` sai NULL e a emenda vai para a quarentena
-- por construção (ADR-018, motivo `orgao_nao_resolvido`) — nunca NULL
-- silencioso passando batido pelo not_null do schema.yml.

{{ config(materialized='ephemeral') }}

with autores as (
    select
        ma.ano,
        ma.codigo_emenda,
        ma.id_parlamentar,
        ma.surrogate_key,
        d.fonte
    from {{ ref('emenda_autor') }} ma
    inner join {{ ref('dim_parlamentar') }} d
        on ma.surrogate_key = d.surrogate_key
)

select
    a.ano,
    a.codigo_emenda,
    a.id_parlamentar,
    a.surrogate_key,
    o.id_orgao
from autores a
left join (
    select sigla, id_orgao
    from {{ ref('dim_orgao') }}
) o
    on o.sigla = case a.fonte
        when 'camara' then 'CD'
        when 'senado' then 'SF'
        else null
    end