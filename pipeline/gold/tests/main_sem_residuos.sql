-- main_sem_residuos — guardrail contra regressão pré-ADR-042 (Sprint 27, Onda 2).
--
-- Falha (retorna linhas) se o schema `main` voltar a acumular tabelas além
-- da permitida — sintoma da migração por COPY sem DROP que gerou 23 tabelas
-- stale (fact_despesa defasado em ~465k linhas, Onda 20.1). Roda em todo
-- `dbt build` sem `--select` restritivo (inclui o build core do DAG).
--
-- ESTADO 2 (Onda 3): permitido = {} — `main` (default do DuckDB)
-- permanece vazio por construção; `data_quality_report` vive em `control`
-- (ADR-060). Qualquer tabela em `main` é resíduo e falha o build.

select table_name as tabela_residuo_main
from information_schema.tables
where table_schema = 'main'
