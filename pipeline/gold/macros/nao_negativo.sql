-- nao_negativo — test genérico customizado de valor monetário não negativo
-- (ADR-013/ADR-022.3a — Data Quality Report).
--
-- Reafirma no Gold o contrato já garantido na Silver pelo gate Pandera
-- (`pipeline/quality.py`, `valor_liquido` com `Check.ge(0)`): o `fact_despesa`
-- que alimenta `supplier_concentration`/`supplier_growth` (ADR-021) e o
-- `supplier_dependency_score` (ADR-027.3) só pode conter `valor_liquido >= 0`,
-- caso contrário a interpretação de HHI (share ∈ [0,1], `dep_f ∈ [1/n, 1]`)
-- perde sentido. Severidade configurável no schema.yml (`warn` — AMBULATÓRIO:
-- a fonte nunca deveria entregar estornos com a quarentena Silver ligada; se
-- aparecerem, o DQ Report sinaliza sem bloquear o build).
--
-- Parâmetros (declarados no schema.yml, sob `arguments:`):
--   - model: o model do qual o column pertence (auto passado pelo dbt).
--   - column_name: a coluna monetária a verificar (auto passado pelo dbt).

{% test nao_negativo(model, column_name) %}

    select {{ column_name }} as valor_negativo
    from {{ model }}
    where {{ column_name }} is not null
      and {{ column_name }} < 0

{% endtest %}