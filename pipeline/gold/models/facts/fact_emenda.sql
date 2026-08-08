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
--   - id_orgao       → dim_orgao (seed), via JOIN por `sigla` derivada da
--                      `fonte` da versão casada (emenda_autor_orgao) — sem
--                      literal da casa [ADR-022.1]; fonte sem órgão conhecido
--                      NÃO promove aqui (Vai à quarentena ADR-018).
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

com_orgao as (
    select
        r.*,
        eao.id_orgao
    from resolvidas r
    inner join {{ ref('emenda_autor_orgao') }} eao
        on r.ano = eao.ano and r.codigo_emenda = eao.codigo_emenda
    where eao.id_orgao is not null
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
from com_orgao