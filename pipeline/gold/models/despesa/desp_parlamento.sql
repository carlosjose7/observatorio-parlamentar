-- desp_parlamento — ponte despesa × parlamentar RESOLVIDO (padrão ADR-017).
--
-- Despesas cujo parlamentar foi resolvido **sem ambiguidade** contra a versão
-- de `dim_parlamentar` vigente na `data_documento` (câmara por id natural;
-- senado por nome normalizado; ver `desp_parlamento_classificacao`).
--
-- `id_parlamentar` aqui é a chave natural (por fonte) da dimensão SCD2; o
-- `surrogate_key` identifica exatamente qual versão foi usada no matching —
-- insumo auditável para `fact_despesa` (ADR-012). Linhas ambíguas, fora de
-- cobertura, não resolvidas ou com data inválida ficam em
-- `desp_parlamento_quarantine` (ADR-018) — nunca descartadas em silêncio.

with classificada as (
    select *
    from {{ ref('desp_parlamento_classificacao') }}
)

select
    fonte,
    cod_documento,
    id_parlamentar_resolvido as id_parlamentar,
    surrogate_key,
    n_candidatos
from classificada
where parlamentar_status = 'parlamentar_resolvido'
  and id_parlamentar_resolvido is not null
  and surrogate_key is not null