-- cartao_unidade — resolução da dimensão institucional do cartão (ADR-010/ADR-025).
--
-- Efêmero compartilhado por `fact_cartao_cpgf` e `fact_cartao_cpgf_quarantine`:
-- cada transação CGU nasce com `unidadeGestora.codigo`/`nome` nativamente
-- (ADR-010/ADR-012) — a ponte liga a UG à sua linha em `dim_unidade_gestora`
-- (chave natural composta fonte_origem=C(CGU) + codigo) e carrega o `id_orgao`
-- por JOIN de `dim_orgao` na sigla `EX` (Poder Executivo genérico, ADR-025).
--
-- A sigla NÃO é um literal de id: vem de dim_orgao (seed). `id_orgao` é a única
-- FK NOT NULL do contrato derivada desta ponte; se a dimensão (órgão ou UG)
-- estiver dessincronizada, ela sai NULL e a transação vai para a quarentena por
-- construção (motivo orgao_nao_resolvido / unidade_gestora_nao_resolvida) —
-- nunca NULL silencioso (ADR-018/022.1).

{{ config(materialized='ephemeral') }}

with transacoes as (
    select
        s.id,
        s.unidade_gestora_codigo
    from {{ source('silver', 'silver_cartao') }} s
)

select
    t.id,
    u.id_unidade_gestora,
    o.id_orgao
from transacoes t
left join (
    select id_unidade_gestora, codigo, fonte_origem
    from {{ ref('dim_unidade_gestora') }}
) u
    on u.fonte_origem = 'CGU'
    and u.codigo = t.unidade_gestora_codigo
left join (
    select sigla, id_orgao
    from {{ ref('dim_orgao') }}
) o
    on o.sigla = 'EX'