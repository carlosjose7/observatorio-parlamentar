-- pipeline_task_runs — spans de duração por task (ADR-056 D1, Onda 1).
-- Derruba o Parquet de controle escrito pela instrumentação própria
-- (`pipeline/runs.py::medir_task`, um arquivo por `(run_id, task)`) e
-- consolida em tabela DuckDB incremental. Grão `(run_id, task)` — grão
-- distinto de `pipeline_runs` (1 linha por run), por isso model próprio.
-- Chave de merge `task_run_id` (`run_id__task`, determinística): re-runs
-- sobrescrevem os mesmos spans (idempotente, mesmo padrão do `run_id`).
-- Merge idempotente: em cada build o conteúdo espelha o diretório Bronze
-- completo (novas linhas somadas, ausência de arquivo = nenhuma linha).
--
-- O caminho é externalizado (ADR-008): var `bronze_pipeline_task_runs_dir`,
-- padrão relativo ao repo root (mesma correção do `pipeline_runs`, E2E
-- Sprint 6.5 — o DuckDB resolve globs relativos ao CWD). Em produção com
-- MinIO o diretório é remoto (s3://...) — override via `get_dbt_vars()`.

{{ config(materialized='incremental', unique_key='task_run_id') }}

{% if execute %}
    {% set pg = run_query(
        "select count(*) as total from glob('" ~ var('bronze_pipeline_task_runs_dir') ~ "')"
    ) %}
    {% set arquivos_total = pg.rows[0][0] %}
{% endif %}

{% if execute and arquivos_total | int > 0 %}
    select
        run_id || '__' || task as task_run_id,
        run_id,
        task,
        status,
        try_cast(duration_seconds as double) as duration_seconds,
        pipeline_version,
        try_cast(execution_timestamp as timestamp) as execution_timestamp
    from read_parquet('{{ var('bronze_pipeline_task_runs_dir') }}', union_by_name = true)
{% else %}
    -- Sem arquivos de controle: tabela vazia com schema compatível — NUNCA
    -- insere linha fictícia (mesmo contrato do `pipeline_runs`, ADR-019).
    select
        cast(null as varchar) as task_run_id,
        cast(null as varchar) as run_id,
        cast(null as varchar) as task,
        cast(null as varchar) as status,
        cast(null as double) as duration_seconds,
        cast(null as varchar) as pipeline_version,
        cast(null as timestamp) as execution_timestamp
    where false
{% endif %}
