-- cartao_fornecedor — resolução do fornecedor do cartão (ADR-011/ADR-018).
--
-- Efêmero compartilhado por `fact_cartao_cpgf` e `fact_cartao_cpgf_quarantine`:
-- o `id_fornecedor` nasce do CNPJ/CPF do estabelecimento da transação, por JOIN
-- na chave natural composta (tipo_documento, cnpj_cpf_valor) de dim_fornecedor.
--
-- A pseudonimização do ADR-011 é respeitada: dim_fornecedor guarda CNPJ em
-- texto claro e CPF como HMAC-SHA256 (UDF `hmac_sha256_cpf`, plugin hmac_udf);
-- aqui a Silver ainda tem o dígito cru — a UDF aplica o MESMO hash para casar.
--
-- Diferente da despesa, `id_fornecedor` do cartão é NULLABLE no contrato
-- (gold.py:188, a fonte não garante CNPJ do estabelecimento); quando o
-- documento não resolve (ausente/não identificável/lag da dimensão), a transação
-- PERMANECE no fato com `id_fornecedor` NULL — não vai à quarentena
-- (ADR-012/arch_er: id_fornecedor nullable). Só os relationships/fk_orphan_pct
-- de `id_fornecedor` apontam o lag quando ele é massivo (ADR-022.3a).

{{ config(materialized='ephemeral') }}

select
    s.id,
    f.id_fornecedor
from {{ source('silver', 'silver_cartao') }} s
left join {{ ref('dim_fornecedor') }} f
    on f.tipo_documento = s.estabelecimento_tipo_documento
    and f.cnpj_cpf_valor = case
        when s.estabelecimento_tipo_documento = 'CPF' then hmac_sha256_cpf(s.estabelecimento_cnpj_valor)
        else s.estabelecimento_cnpj_valor
    end