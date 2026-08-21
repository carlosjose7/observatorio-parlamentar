-- dim_fornecedor_quarantine — isolamento do que NÃO entrou em dim_fornecedor
-- (padrão ADR-018: toda dimensão derivada tem seu modelo quarentena).
-- Auditável e reprocessável: em vez de descartar silenciosamente, as linhas
-- com identidade de fornecedor irresolúvel são expostas aqui.

with dados as (
    select
        cnpj_cpf_valor,
        tipo_documento,
        nome_fornecedor
    from {{ source('silver', 'silver_despesa') }}
    where nome_fornecedor is not null
)

select distinct
    cnpj_cpf_valor,
    tipo_documento,
    nome_fornecedor,
    case
        when cnpj_cpf_valor is null then 'identidade_ausente'
        when tipo_documento = 'INVALIDO' then 'documento_invalido'
        else 'tipo_documento_indefinido'
    end as motivo
from dados
where
    cnpj_cpf_valor is null
    or tipo_documento is null
    or tipo_documento = 'INVALIDO'