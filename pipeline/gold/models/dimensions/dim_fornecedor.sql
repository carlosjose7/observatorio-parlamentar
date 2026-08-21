-- dim_fornecedor — ADR-011/ADR-018/ADR-033, Onda 1 (Trilha B da Sprint 4).
-- Derivada de silver_despesa: CNPJ em texto claro; CPF já vem pseudonimizado
-- com HMAC-SHA256 pela própria Silver (pipeline/pseudonymize.py, ADR-033) —
-- o Gold apenas REPASSA o valor, nunca reaplica hash (sem hash-de-hash).
-- Fornecedores sem documento identificável ou com tipo indefinido/inválido
-- NÃO entram na dimensão (ADR-011 evita identidade fantasma); as linhas são
-- isoladas em dim_fornecedor_quarantine (padrão ADR-018).
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
    cnpj_cpf_valor,
    tipo_documento,
    nome_fornecedor,
    cast(null as bigint) as id_municipio
from fornecedores