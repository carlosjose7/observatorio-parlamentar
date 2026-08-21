-- cartao_fornecedor — resolução do fornecedor do cartão (ADR-011/ADR-018).
--
-- Efêmero compartilhado por `fact_cartao_cpgf` e `fact_cartao_cpgf_quarantine`:
-- o `id_fornecedor` nasce do CNPJ/CPF do estabelecimento da transação, por JOIN
-- na chave natural composta (tipo_documento, cnpj_cpf_valor) de dim_fornecedor.
--
-- A pseudonimização acontece na Silver (ADR-033, pipeline/pseudonymize.py):
-- `silver_cartao.estabelecimento_cnpj_valor` (quando CPF) e `dim_fornecedor`
-- carregam o MESMO hash HMAC-SHA256, então o JOIN é por igualdade direta — o
-- Gold não reaplica hash. O `portador_cpf_formatado` já é mascarado pela CGU.
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
    and f.cnpj_cpf_valor = s.estabelecimento_cnpj_valor