-- dim_categoria_despesa_quarantine — linhas rejeitadas de dim_categoria_despesa
-- (tipo_despesa ausente). Padrão ADR-018.

select distinct
    tipo_despesa as descricao,
    'tipo_despesa_ausente' as motivo
from {{ source('silver', 'silver_despesa') }}
where tipo_despesa is null