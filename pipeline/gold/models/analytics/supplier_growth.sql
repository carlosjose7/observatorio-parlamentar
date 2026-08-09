-- supplier_growth — agregado analítico puro (ADR-021, Onda 3).
-- Crescimento de receita pública anual recebida por fornecedor, com variação
-- YoY contra o ano anterior. Grão: (ano, id_fornecedor).
--
-- `valor_ano_anterior` é nulo no primeiro ano em que o fornecedor aparece no
-- fato (sem período anterior); `variacao_pct` segue a mesma nulidade. Fonte:
-- fato promovido `fact_despesa` (agregado puro, sem ML).

with receita as (
    select
        dd.ano,
        fd.id_fornecedor,
        sum(fd.valor_liquido) as valor_recebido
    from {{ ref('fact_despesa') }} fd
    inner join {{ ref('dim_data') }} dd on dd.data_sk = fd.data_sk
    group by dd.ano, fd.id_fornecedor
),

com_anterior as (
    select
        ano,
        id_fornecedor,
        valor_recebido,
        lag(valor_recebido) over (
            partition by id_fornecedor
            order by ano
        ) as valor_ano_anterior
    from receita
)

select
    ano,
    id_fornecedor,
    valor_recebido,
    valor_ano_anterior,
    case
        when valor_ano_anterior is null or valor_ano_anterior = 0 then cast(null as double)
        else (valor_recebido - valor_ano_anterior) / valor_ano_anterior
    end as variacao_pct
from com_anterior
order by id_fornecedor, ano