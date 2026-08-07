-- Dimensão calendário (Trilha A). Gerada por série de datas, sem
-- dependência de fonte Silver ou de silver_* populada — por isso não
-- há model de quarentena (não existe "dado inválido" numa dimensão
-- gerada). Baseada no ano de início real da Câmara
-- (config/pipeline.yaml: camara.carga_historica.data_inicio = 2015-01-01)
-- e projeção de ~20 anos à frente.

with date_spine as (
    select cast(d as date) as calendar_date
    from (
        select * from range(
            date '2015-01-01',
            date '2036-01-01',
            interval 1 day
        )
    ) as t(d)
)

select
    cast(strftime(calendar_date, '%Y%m%d') as bigint) as data_sk,
    calendar_date as data,
    year(calendar_date) as ano,
    month(calendar_date) as mes,
    day(calendar_date) as dia,
    quarter(calendar_date) as trimestre,
    date_part('dow', calendar_date) as dia_semana_num,
    dayname(calendar_date) as dia_semana_nome,
    monthname(calendar_date) as mes_nome,
    -- is_dia_util: seg-sex apenas. Feriados nacionais e calendário de
    -- sessões parlamentares ficam fora desta Onda 1 — ver PROJECT_CONTEXT
    -- §10 (critério "despesa em dia sem sessão").
    case
        when date_part('dow', calendar_date) in (0, 6) then false
        else true
    end as is_dia_util
from date_spine