-- desp_fornecedor — resolução do fornecedor da despesa (ADR-011/ADR-018).
--
-- Efêmero compartilhado por `fact_despesa` e `fact_despesa_quarantine`: mapeia
-- cada despesa de parlamentar resolvido para o `id_fornecedor` da dimensão,
-- por JOIN na chave natural composta (tipo_documento, cnpj_cpf_valor).
--
-- O valor de junção respeita a pseudonimização do ADR-011: `dim_fornecedor`
-- guarda CNPJ em texto claro e CPF como HMAC-SHA256 (UDF `hmac_sha256_cpf`,
-- plugin hmac_udf). Aqui a Silver ainda tem o CPF em dígitos — a UDF aplica o
-- MESMO hash para casar com a dimensão; nunca o CPF crupa para o fato.
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
    and f.cnpj_cpf_valor = case
        when s.tipo_documento = 'CPF' then hmac_sha256_cpf(s.cnpj_cpf_valor)
        else s.cnpj_cpf_valor
    end