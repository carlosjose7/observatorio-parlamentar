-- dim_categoria_despesa — tipos de despesa CEAP (PROJECT_CONTEXT §7).
-- Derivada de silver_despesa.tipo_despesa. O catálogo de categorias não é
-- fixo nem conhecido offline (variam entre Câmara e Senado), então `cod_tipo`
-- é gerado deterministicamente a partir da descrição: 12 hex de MD5 sobre o
-- texto normalizado (uppercase) — estável e livre de colisões para o volume
-- esperado. A descrição é a string original da fonte.
--
-- `tipo_despesa` nulo é isolado em dim_categoria_despesa_quarantine
-- (padrão ADR-018).

with categorias as (
    select tipo_despesa
    from {{ source('silver', 'silver_despesa') }}
    where tipo_despesa is not null
    group by tipo_despesa
)

select
    substr(md5(upper(tipo_despesa)), 1, 12) as cod_tipo,
    tipo_despesa as descricao
from categorias