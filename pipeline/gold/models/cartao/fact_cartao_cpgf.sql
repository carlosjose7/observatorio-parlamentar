-- fact_cartao_cpgf — transações do Cartão de Pagamento do Governo Federal (ADR-012/ADR-025).
--
-- Grão: UMA transação de cartão CPGF (silver_cartao, chave nativa `id` da CGU).
-- Promovidas apenas transações cujas FKs institucionais e de calendário
-- resolvem; o restante fica em `fact_cartao_cpgf_quarantine` (ADR-018/022),
-- nunca descartado em silêncio.
--
-- FKs/dimensões (modelo de constelação, ADR-012):
--   - id_orgao          → dim_orgao (seed), via JOIN da ponte cartao_unidade na
--                        sigla `EX` (Poder Executivo genérico, ADR-025) — sem
--                        literal de id [ADR-022.1]; CGU não expõe órgão no grão.
--   - id_unidade_gestora → dim_unidade_gestora (CGU), chave natural
--                        (fonte_origem, codigo) — a CGU entrega a UG nativamente;
--                        NOT NULL no contrato (gold.py).
--   - id_fornecedor      → dim_fornecedor, NULLABLE por contrato (ADR-012); só
--                        preenchido quando o estabelecimento tem CNPJ/CPF que
--                        resolve na dimensão (cartao_fornecedor).
--   - data_sk           → dim_data, YYYYMMDD de data_transacao.
--   - dim_parlamentar    → NÃO referenciada (ADR-012.3): o portador é
--                        estruturalmente do Poder Executivo; correlação futura
--                        com parlamentar é bridge dedicada, não FK desta fato.
--
-- `id_transacao` é surrogate determinístico (row_number sobre a resolução
-- ordenada — mesmo padrão de id_despesa/Fornecedor). Chave de referência
-- externa/entre execuções: `id` nativo da CGU (silver_cartao).

with resolvidas as (
    select
        s.id,
        u.id_orgao,
        u.id_unidade_gestora,
        n.id_fornecedor,
        cast(strftime(cast(s.data_transacao as date), '%Y%m%d') as bigint) as data_sk,
        s.portador_nome,
        s.portador_cpf_mascarado,
        s.valor_transacao,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version
    from {{ source('silver', 'silver_cartao') }} s
    inner join {{ ref('cartao_unidade') }} u using (id)
    left join {{ ref('cartao_fornecedor') }} n using (id)
    where u.id_orgao is not null
      and u.id_unidade_gestora is not null
)

select
    row_number() over (
        order by id, data_sk, id_orgao, id_unidade_gestora
    ) as id_transacao,
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
    source_version
from resolvidas
where data_sk is not null
  and exists (
      select 1 from {{ ref('dim_data') }} d
      where d.data_sk = resolvidas.data_sk
  )