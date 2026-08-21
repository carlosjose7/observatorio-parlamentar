-- fact_despesa — fatos de despesas parlamentares de parlamentar resolvido
-- (ADR-012, modelo de constelação; contrato em pipeline/gold.py:FactDespesa).
--
-- Promove apenas despesas cujo parlamentar foi resolvido sem ambiguidade
-- (desp_parlamento) E cujas dimensões resolveram de verdade — nasce com os
-- JOINs reais, não com placeholder de identidade para preencher depois:
--
--   - id_parlamentar → dim_parlamentar (versão vigente em `data_documento`,
--     via desp_parlamento_classificacao — câmara por id, senado por nome).
--   - id_orgao       → dim_orgao (seed), via JOIN por `sigla` derivada da
--                      `fonte` da despesa (desp_orgao, ADR-022.1) — sem
--                      literal da casa.
--   - id_fornecedor  → dim_fornecedor (ADR-011), por (tipo_documento,
--                      cnpj_cpf_valor); CPF casado pelo hash HMAC-SHA256 já
--                      pseudonimizado na Silver (ADR-033, desp_fornecedor).
--   - cod_tipo       → dim_categoria_despesa, por `substr(md5(upper(tipo_despesa)),
--                      1, 12)` — mesmo determinismo da dimensão.
--   - data_sk        → dim_data, YYYYMMDD de `data_documento`.
--
-- QUALQUER FK que não resolve (incluindo órfão transitório de dimensão, ex.:
-- fornecedor novo antes da próxima carga da dimensão, ADR-022.3a) impede a
-- promoção — a despesa vai a `fact_despesa_quarantine` (ADR-018), nunca é
-- descartada ou promovida com FK NULL.
--
-- `id_despesa` é surrogate determinístico (row_number sobre a resolução
-- ordenada — mesmo padrão de id_fornecedor/id_emenda). A chave natural
-- composta `(fonte, cod_documento)` é a referência externa/entre execuções.
--
-- Já que `id_parlamentar` é chave natural (e `dim_parlamentar` é SCD2, com
-- várias versões por id), o fato também guarda o `surrogate_key` da versão
-- EXATA casada em `data_documento` — insumo de auditoria (ADR-017) e alvo de
-- integridade referencial 1:1 (ver schema.yml): um `relationships` por
-- `surrogate_key` prova que existe a versão vigente nesta data, não apenas
-- "alguma versão" do id (paridade com o contrato de `surrogate_key` do
-- `fact_emenda`).

with resolvidas as (
    select
        s.fonte,
        s.cod_documento,
        s.data_documento,
        s.tipo_despesa,
        s.valor_liquido,
        s.valor_glosa,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version,
        dp.id_parlamentar,
        dp.surrogate_key,
        eao.id_orgao,
        dfo.id_fornecedor
    from {{ source('silver', 'silver_despesa') }} s
    inner join {{ ref('desp_parlamento') }} dp using (fonte, cod_documento)
    inner join {{ ref('desp_orgao') }} eao using (fonte, cod_documento)
    inner join {{ ref('desp_fornecedor') }} dfo using (fonte, cod_documento)
    inner join {{ ref('dim_categoria_despesa') }} cat
        on cat.cod_tipo = substr(md5(upper(s.tipo_despesa)), 1, 12)
    inner join {{ ref('dim_data') }} dd
        on dd.data_sk = cast(strftime(cast(s.data_documento as date), '%Y%m%d') as bigint)
    where eao.id_orgao is not null
      and dfo.id_fornecedor is not null
      and s.data_documento is not null
      and s.tipo_despesa is not null
)

select
    row_number() over (
        order by fonte, cod_documento, id_parlamentar, surrogate_key
    ) as id_despesa,
    id_parlamentar,
    surrogate_key,
    id_fornecedor,
    id_orgao,
    cast(null as bigint) as id_unidade_gestora,
    substr(md5(upper(tipo_despesa)), 1, 12) as cod_tipo,
    cast(strftime(cast(data_documento as date), '%Y%m%d') as bigint) as data_sk,
    cod_documento,
    valor_liquido,
    valor_glosa,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version
from resolvidas