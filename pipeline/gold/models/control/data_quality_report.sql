-- data_quality_report — Data Quality Report da Silver promovido à Gold (ADR-031).
-- Fonte: `main.data_quality_report` (ADR-015, ADR-042) — escrita exclusiva por
-- pipeline/silver.py (Pandera gate, ADR-013). A API é read-only sobre o Gold
-- (ADR-026); a promoção via source → materialização (mesmo mecanismo da
-- Opção A do ADR-026; precedente: `pipeline_runs` lê Bronze no build,
-- ADR-019) coloca o relatório atrás da fronteira de leitura sem expor a
-- Silver — `GET /qualidade/relatorio` (Sprint 6/Onda 3, ADR-031) consome
-- esta Gold.
--
-- `regras_violadas` chega como lista serializada em JSON string (coluna
-- varchar, ver `silver.persistir_qualidade_report`); `execution_timestamp`
-- é re-castado de varchar ISO-8601 para timestamp (paridade com as demais
-- tabelas de controle do Gold).

{{ config(materialized='table') }}

select
    run_id,
    tabela,
    total_registros,
    registros_validos,
    registros_quarentena,
    registros_deduplicados,
    regras_violadas,
    percentual_nulos_criticos,
    try_cast(execution_timestamp as timestamp) as execution_timestamp
from {{ source('control', 'data_quality_report') }}