-- fact_presenca_quarantine — presenças não promovidas, com motivo (ADR-018).
--
-- Consome a ponte `presenca_parlamento_classificacao` (status <>
-- 'resolvido'); ausências derivadas nunca vêm para cá (nascem de conjuntos
-- já resolvidos). Motivos: evento_nao_resolvido | evento_nao_encerrado |
-- parlamentar_nao_resolvido | data_nao_resolvida | orgao_nao_resolvido.

select
    id_evento,
    id_deputado as id_parlamentar,
    status as motivo_quarentena,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version
from {{ ref('presenca_parlamento_classificacao') }}
where status <> 'resolvido'
