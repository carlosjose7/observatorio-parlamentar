-- supplier_concentration — agregado analítico puro (ADR-021, Onda 3).
-- Índice de concentração de gastos de cada parlamentar em fornecedores, por
-- ano. Grão: (ano, id_parlamentar).
--
-- hhi = SUM(participacao^2), onde participacao = total do fornecedor dividido
-- pelo total do parlamentar no ano (métrica `hhi` / `participacao_no_total`
-- de PROJECT_CONTEXT §7). Intervalo: HHI ∈ (0, 1] — 1 significa gasto em um
-- só fornecedor. Fonte: fato promovido `fact_despesa` (agregado puro, sem ML).

with gasto_fornecedor as (
    select
        dd.ano,
        fd.id_parlamentar,
        fd.id_fornecedor,
        sum(fd.valor_liquido) as valor_fornecedor
    from {{ ref('fact_despesa') }} fd
    inner join {{ ref('dim_data') }} dd on dd.data_sk = fd.data_sk
    group by dd.ano, fd.id_parlamentar, fd.id_fornecedor
),

total_parlamentar as (
    select
        ano,
        id_parlamentar,
        count(*) as num_fornecedores,
        sum(valor_fornecedor) as total_valor
    from gasto_fornecedor
    group by ano, id_parlamentar
)

select
    tp.ano,
    tp.id_parlamentar,
    tp.num_fornecedores,
    tp.total_valor,
    sum(
        (g.valor_fornecedor / tp.total_valor) * (g.valor_fornecedor / tp.total_valor)
    ) as hhi
from total_parlamentar tp
inner join gasto_fornecedor g
    on tp.ano = g.ano
   and tp.id_parlamentar = g.id_parlamentar
group by tp.ano, tp.id_parlamentar, tp.num_fornecedores, tp.total_valor
order by tp.ano, tp.id_parlamentar