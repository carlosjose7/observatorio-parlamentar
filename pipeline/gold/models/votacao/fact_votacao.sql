-- fact_votacao — voto parlamentar por votação nominal (ADR-058, ADR-012).
--
-- Grão: 1 linha por (id_parlamentar, id_votacao). Promove apenas votos com
-- parlamentar resolvido (versão vigente na data do evento), evento Encerrada
-- e dimensões resolvidas — ponte `votacao_parlamento_classificacao`
-- (status resolvido). `seguiu_partido` cruza voto × orientação da bancada
-- do parlamentar na mesma versão (NULL quando não comparável — Decisão 4).
-- Contrato em pipeline/gold.py:FactVotacao.

select
    row_number() over (order by id_votacao, id_parlamentar) as id_voto,
    id_parlamentar,
    surrogate_key,
    id_votacao,
    id_evento,
    id_orgao,
    data_sk,
    voto_normalizado as voto,
    seguiu_partido,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version
from {{ ref('votacao_parlamento_classificacao') }}
where status = 'resolvido'
