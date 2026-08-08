-- fact_emenda — fatos de emendas parlamentares de autor resolvido (ADR-012/ADR-017).
--
-- Promove apenas emendas cujo autor individual foi resolvido sem ambiguidade
-- (emenda_autor, ADR-017): `id_parlamentar` NOT NULL — faz parte da identidade
-- do evento (ADR-012.3). Emendas colegiadas, ambíguas, fora de cobertura ou
-- não resolvidas NÃO entram aqui — ficam em `fact_emenda_quarantine`
-- (ADR-018/ADR-022), nunca descartadas em silêncio.
--
-- FKs/dimensões (modelo de constelação, ADR-012):
--   - id_parlamentar → dim_parlamentar (versão vigente no ano, via ADR-017).
--   - id_orgao       → dim_orgao (seed): CD=1 / SF=2, derivada da `fonte` da
--                      versão de dim_parlamentar casada no matching.
--   - data_sk        → dim_data: a CGU só expõe o `ano` do exercício; a emenda
--                      é representada no último dia do ano (ANO-12-31), dentro
--                      do horizonte de dim_data (2015–2035).
--   - id_unidade_gestora → nullable (ADR-010; fonte não entrega UG no grão).
--
-- `id_emenda` é surrogate determinístico (row_number sobre a resolução
-- ordenada — mesmo padrão de id_fornecedor). Idempotente dentro de um mesmo
-- `dbt build`; a chave natural composta `(ano, codigo_emenda)` é a referência
-- externa/entre execuções (consequência ADR-020 na nota de emenda).

with resolvidas as (
    select
        s.ano,
        s.codigo_emenda,
        s.tipo_emenda,
        s.nome_autor,
        s.funcao,
        s.subfuncao,
        s.localidade_do_gasto,
        s.valor_empenhado,
        s.valor_liquidado,
        s.valor_pago,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version,
        ma.id_parlamentar,
        ma.surrogate_key,
        cast(strftime(make_date(s.ano, 12, 31), '%Y%m%d') as bigint) as data_sk
    from {{ source('silver', 'silver_emenda') }} s
    inner join {{ ref('emenda_autor') }} ma using (ano, codigo_emenda)
),

com_fonte as (
    select
        r.*,
        case when d.fonte = 'senado' then 2 else 1 end as id_orgao
    from resolvidas r
    inner join {{ ref('dim_parlamentar') }} d
        on r.surrogate_key = d.surrogate_key
)

select
    row_number() over (
        order by ano, codigo_emenda, id_parlamentar, surrogate_key
    ) as id_emenda,
    ano,
    codigo_emenda,
    id_parlamentar,
    surrogate_key,
    id_orgao,
    cast(null as bigint) as id_unidade_gestora,
    data_sk,
    tipo_emenda,
    nome_autor,
    funcao,
    subfuncao,
    localidade_do_gasto,
    valor_empenhado,
    valor_liquidado,
    valor_pago,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version
from com_fonte