-- emenda_autor — autoria de emenda com autor individual resolvido (ADR-017).
--
-- Apenas emendas cujo autor foi resolvido **sem ambiguidade**: o
-- `nome_autor_normalizado` casou exatamente com exatamente um
-- `dim_parlamentar` vigente no ano da emenda (ADR-017.3.b/3.c, vigência-por-ano
-- do ADR-020). Linhas com `id_parlamentar` não-único ou inexistente ficam em
-- `emenda_autor_quarantine` (ADR-018) — não são descartadas silenciosamente.
--
-- O `id_parlamentar` aqui é a chave natural (por fonte) da dimensão SCD2; o
-- `surrogate_key` permite rastrear exatamente qual versão foi usada no
-- matching — insumo auditável para `fact_emenda` (ADR-012).

with classificada as (
    select *
    from {{ ref('em_autor_classificacao') }}
)

select
    ano,
    codigo_emenda,
    tipo_emenda,
    nome_autor,
    id_parlamentar,
    surrogate_key,
    n_candidatos
from classificada
where autor_status = 'autor_resolvido'