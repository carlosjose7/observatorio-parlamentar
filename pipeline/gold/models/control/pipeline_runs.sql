-- pipeline_runs — tabela de controle de execuções (versionamento.md §4, ADR-019).
-- Derruba o Parquet de controle escrito pela Bronze (um arquivo por run_id) e
-- consolida em tabela DuckDB incremental por `run_id`. Merge idempotente:
-- em cada build o conteúdo espelha o diretório Bronze completo (novas linhas
-- somadas, ausência de arquivo = nenhuma linha). Sem `source_version`
-- (PipelineRun não possui esse campo — na Silver ele veio do próprio Bronze).
--
-- O caminho é externalizado (ADR-008): var `bronze_pipeline_runs_dir`,
-- padrão relativo ao arquivo DuckDB (que vive em data/silver/...). Em
-- produção com MinIO o diretório é remoto (s3://...) — basta override da var.

{{ config(materialized='incremental', unique_key='run_id') }}

{% if execute %}
    {% set pg = run_query(
        "select count(*) as total from glob('" ~ var('bronze_pipeline_runs_dir') ~ "')"
    ) %}
    {% set arquivos_total = pg.rows[0][0] %}
    {# `status_detalhado` (ADR-056 D1) só existe nos Parquet escritos a partir
    da Sprint 26 — referenciá-lo incondicionalmente quebraria o build com
    `Binder Error` enquanto o glob só tiver arquivos legados (todos sem a
    coluna), mesmo com `union_by_name`. Introspecção de schema em tempo de
    build (mesmo mecanismo do `run_query` acima): com a coluna, lê o valor;
    sem ela, NULL — o Gold antigo e o novo convergem para o mesmo schema. #}
    {% if arquivos_total | int > 0 %}
        {% set esquema = run_query(
            "describe select * from read_parquet('"
            ~ var('bronze_pipeline_runs_dir') ~ "', union_by_name = true)"
        ) %}
        {% set colunas_parquet = [] %}
        {% for linha in esquema.rows %}
            {% do colunas_parquet.append(linha[0]) %}
        {% endfor %}
    {% endif %}
{% endif %}

{% if execute and arquivos_total | int > 0 %}
    select
        run_id,
        pipeline_version,
        try_cast(execution_timestamp as timestamp) as execution_timestamp,
        status,
        {% if 'status_detalhado' in colunas_parquet %}
        status_detalhado,
        {% else %}
        cast(null as varchar) as status_detalhado,
        {% endif %}
        cast(fontes_com_erro as varchar[]) as fontes_com_erro,
        watermark_camara,
        watermark_senado,
        watermark_cgu_emenda,
        watermark_cgu_cartao
    from read_parquet('{{ var('bronze_pipeline_runs_dir') }}', union_by_name = true)
{% else %}
    -- Sem arquivos de controle: tabela vazia com schema compatível — NUNCA
    -- insere linha fictícia (nada distingue "dummy" de execução real; zero
    -- linhas = zero falsos positivos em DQ/reprodutibilidade/RF-12).
    -- `fontes_com_erro` é LIST(VARCHAR) (corretivo QA BUG-005): o Parquet da
    -- Bronze grava a lista de fontes com erro; o ramo vazio espelha o MESMO
    -- tipo para o MERGE incremental nunca falhar por incompatibilidade.
    select
        cast(null as varchar) as run_id,
        cast(null as varchar) as pipeline_version,
        cast(null as timestamp) as execution_timestamp,
        cast(null as varchar) as status,
        cast(null as varchar) as status_detalhado,
        cast(null as varchar[]) as fontes_com_erro,
        cast(null as varchar) as watermark_camara,
        cast(null as varchar) as watermark_senado,
        cast(null as varchar) as watermark_cgu_emenda,
        cast(null as varchar) as watermark_cgu_cartao
    where false
{% endif %}