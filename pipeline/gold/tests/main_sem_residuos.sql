-- main_sem_residuos — guardrail contra regressão pré-ADR-042 (Sprint 27, Onda 2).
--
-- Falha (retorna linhas) se o schema `main` voltar a acumular tabelas além
-- da permitida — sintoma da migração por COPY sem DROP que gerou 23 tabelas
-- stale (fact_despesa defasado em ~465k linhas, Onda 20.1). Roda em todo
-- `dbt build` sem `--select` restritivo (inclui o build core do DAG).
--
-- ESTADO 1 (Onda 2): permitido = {'data_quality_report'} — tabela de
-- controle viva, fonte do model Gold (ADR-031). A Onda 3 (rename → control)
-- esvazia para {} no mesmo diff do rename (guardrail versionado, dois
-- estados — exigência do Revisor Técnico).

select table_name as tabela_residuo_main
from information_schema.tables
where table_schema = 'main'
  and table_name not in ('data_quality_report')
