-- desp_fornecedor — resolução do fornecedor da despesa (ADR-011/ADR-018).
--
-- Efêmero compartilhado por `fact_despesa` e `fact_despesa_quarantine`: mapeia
-- cada despesa de parlamentar resolvido para o `id_fornecedor` da dimensão,
-- por JOIN na chave natural composta (tipo_documento, cnpj_cpf_valor).
--
-- A pseudonimização acontece na Silver (ADR-033, pipeline/pseudonymize.py):
-- `dim_fornecedor` e a foto `silver_despesa` carregam o MESMO hash HMAC-SHA256
-- do CPF, então o JOIN é por igualdade direta da coluna — o Gold nunca reaplica
-- hash (sem hash-de-hash) nem expõe o CPF em dígitos.
--
-- Linhas sem documento identificável (tipo indefinido/inválido/ausente) ou
-- cujo documento não existe na dimensão (lag) saem com `id_fornecedor` NULL —
-- a despesa vai à quarentena por construção (motivo `fornecedor_nao_resolvido`).

{{ config(materialized='ephemeral') }}

select
    s.fonte,
    s.cod_documento,
    f.id_fornecedor
from {{ ref('desp_parlamento') }} dp
inner join {{ source('silver', 'silver_despesa') }} s
    using (fonte, cod_documento)
left join {{ ref('dim_fornecedor') }} f
    on f.tipo_documento = s.tipo_documento
    and f.cnpj_cpf_valor = s.cnpj_cpf_valor