-- dim_parlamentar_quarantine — isolamento do que NÃO entrou em dim_parlamentar
-- (padrão ADR-018: toda dimensão derivada tem seu modelo quarentena).
--
-- Regra de validade espelhada do model principal (defesa em profundidade):
-- identidade obrigatória (`nome`, `id_parlamentar`) e observação plausível
-- (`id_legislatura > 0`, `data` não nula). Em operação normal a Silver já
-- isolou essas linhas no gate Pandera (ADR-024), portanto a tabela tende a
-- ficar vazia — mas existe como contrato observável: se algo escapar do
-- gate, aparece aqui com motivo explícito em vez de sumir silenciosamente.

with dados as (
    select
        fonte,
        id_parlamentar,
        nome,
        id_legislatura,
        cast(data as date) as data,
        run_id
    from {{ source('silver', 'silver_parlamentar') }}
)

select distinct
    fonte,
    id_parlamentar,
    nome,
    id_legislatura,
    data,
    case
        when nome is null or id_parlamentar is null then 'identidade_ausente'
        when id_legislatura is null or id_legislatura <= 0 then 'legislatura_invalida'
        when data is null then 'data_ausente'
        else 'observacao_invalida'
    end as motivo
from dados
where
    nome is null
    or id_parlamentar is null
    or id_legislatura is null
    or id_legislatura <= 0
    or data is null