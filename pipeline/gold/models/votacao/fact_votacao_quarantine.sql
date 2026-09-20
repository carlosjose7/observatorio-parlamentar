-- fact_votacao_quarantine — votos não promovidos, com motivo (ADR-018).
--
-- Motivos: votacao_sem_evento | evento_nao_encerrado |
-- parlamentar_nao_resolvido | data_nao_resolvida | orgao_nao_resolvido.

select
    id_votacao,
    id_deputado as id_parlamentar,
    status as motivo_quarentena,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version
from {{ ref('votacao_parlamento_classificacao') }}
where status <> 'resolvido'
