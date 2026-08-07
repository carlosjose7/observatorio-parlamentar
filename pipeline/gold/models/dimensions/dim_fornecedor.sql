-- dim_fornecedor — ADR-011/ADR-018, Onda 1 (Trilha B da Sprint 4).
-- Derivada de silver_despesa: CNPJ em texto claro; CPF pseudonimizado com
-- HMAC-SHA256 (UDF registrada pelo plugin hmac_udf.py; chave de
-- CPF_HMAC_SECRET_KEY, nunca vaza para o SQL). Fornecedores sem documento
-- identificável ou com tipo indefinido/inválido NÃO entram na dimensão
-- (ADR-011 evita identidade fantasma); as linhas são isoladas em
-- dim_fornecedor_quarantine (padrão ADR-018).
--
-- Chave natural: (cnpj_cpf_valor, tipo_documento) — PROJECT_CONTEXT §7.
-- Um mesmo documento com grafias distintas de nome é consolidado (max).

with fornecedores as (
    select
        cnpj_cpf_valor,
        tipo_documento,
        max(nome_fornecedor) as nome_fornecedor
    from {{ source('silver', 'silver_despesa') }}
    where cnpj_cpf_valor is not null
      and tipo_documento in ('CNPJ', 'CPF')
    group by cnpj_cpf_valor, tipo_documento
)

select
    row_number() over (
        order by cnpj_cpf_valor, tipo_documento, nome_fornecedor
    ) as id_fornecedor,
    case
        when tipo_documento = 'CPF' then hmac_sha256_cpf(cnpj_cpf_valor)
        else cnpj_cpf_valor
    end as cnpj_cpf_valor,
    tipo_documento,
    nome_fornecedor,
    cast(null as bigint) as id_municipio
from fornecedores