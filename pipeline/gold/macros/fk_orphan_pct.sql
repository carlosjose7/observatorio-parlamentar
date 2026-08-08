-- fk_orphan_pct — test genérico customizado de integridade referencial por
-- PERCENTUAL (ADR-022.3a) — o indicador operacional do Data Quality Report.
--
-- Complementa (NÃO substitui) o test genérico `relationships`: ele é binário
-- e sinaliza erro estrutural de modelagem (qualquer órfão), este aqui computa
-- a RAZÃO órfãos/total do fato e SÓ retorna linhas (falha) quando a razão
-- ultrapassa o threshold percentual configurável. Assim, um órfão transitório
-- e esperado (ex.: fornecedor novo no fato antes da próxima carga da dimensão,
-- ADR-022.3a) não bloqueia — a dessincronização em massa da dimensão é o que
-- dispara.
--
-- Parâmetros (declarados no schema.yml, sob `arguments:`):
--   - model: o model do qual o column pertence (auto passado pelo dbt).
--   - column_name: a FK a verificar (auto passado pelo dbt).
--   - to: ref() da dimensão de referência.
--   - field: coluna de referência na dimensão.
--   - threshold_pct: % máximo tolerado de órfãos. O default é o
--     `var('fk_orfas_threshold_pct')` — OBRIGATÓRIO por construção: o valor
--     vem de `config/pipeline.yaml` via `--vars` gerado por
--     `pipeline.config.get_dbt_vars()` (fonte única, ADR-008). ELE NÃO TEM
--     default no código — se a var faltar, o dbt falha (PROJECT_CONTEXT §15),
--     em vez de aplicar silenciosamente um número divergente da config.

{% test fk_orphan_pct(model, column_name, to, field, threshold_pct=var('fk_orfas_threshold_pct')) %}

    with contagem as (
        select
            count(*) as total,
            count(case when d.{{ field }} is null then 1 end) as n_orfao
        from {{ model }} as f
        left join {{ to }} as d
            on f.{{ column_name }} = d.{{ field }}
        where f.{{ column_name }} is not null
    )
    select n_orfao as n_orfao_ultrapassa_threshold
    from contagem
    where total > 0
      and (cast(n_orfao as double) * 100.0 / cast(total as double)) > {{ threshold_pct }}

{% endtest %}