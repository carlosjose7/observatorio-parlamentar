-- fact_cartao_cpgf_quarantine — transações NÃO promovidas a fact_cartao_cpgf
-- (padrão ADR-018/ADR-022), com motivo explícito para auditoria:
--
--   orgao_nao_resolvido            — sigla EX ausente de dim_orgao (lag da
--                                   dimensão, ADR-022.1) — nunca NULL silencioso.
--   unidade_gestora_nao_resolvida — UG não casou com dim_unidade_gestora
--                                   (dessincronização da dimensão; a fonte
--                                   nativa entrega, logo é lag estrutural).
--   data_nao_resolvida            — data_transacao fora do horizonte de dim_data.
--
-- `id_fornecedor` NULL NÃO gera quarentena: é nullable por contrato (ADR-012);
-- o relationships/fk_orphan_pct do próprio fato observam o lag (ADR-022.3a).
-- Nenhuma transação de cartão é descartada em silêncio: o complemento de
-- fact_cartao_cpgf fica aqui, reconstruível pela chave natural `id` (CGU).

with base as (
    select
        s.id,
        u.id_orgao,
        u.id_unidade_gestora,
        n.id_fornecedor,
        dd.data_sk,
        s.portador_nome,
        s.portador_cpf_mascarado,
        s.valor_transacao,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version,
        case
            when u.id_orgao is null then 'orgao_nao_resolvido'
            when u.id_unidade_gestora is null then 'unidade_gestora_nao_resolvida'
            when dd.data_sk is null then 'data_nao_resolvida'
        end as motivo_quarentena
    from {{ source('silver', 'silver_cartao') }} s
    left join {{ ref('cartao_unidade') }} u using (id)
    left join {{ ref('cartao_fornecedor') }} n using (id)
    left join {{ ref('dim_data') }} dd
        on dd.data_sk = cast(strftime(cast(s.data_transacao as date), '%Y%m%d') as bigint)
)

select
    id,
    id_orgao,
    id_unidade_gestora,
    id_fornecedor,
    data_sk,
    portador_nome,
    portador_cpf_mascarado,
    valor_transacao,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version,
    motivo_quarentena
from base
where motivo_quarentena is not null