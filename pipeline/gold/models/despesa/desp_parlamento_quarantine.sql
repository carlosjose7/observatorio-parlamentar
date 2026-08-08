-- desp_parlamento_quarantine — despesas cujo parlamentar NÃO foi promovido
-- (padrão ADR-017/ADR-018), expostas para auditoria com motivo explícito:
--
--   parlamentar_ambiguo        — mais de um parlamentar vigente na data com o
--                                mesmo nome (senado) ou mesma identidade;
--                                id nunca gravado por critério arbitrário.
--   parlamentar_fora_cobertura — identidade existe no cadastro (mesma fonte),
--                                mas sem versão de dim_parlamentar cobrindo a
--                                data_documento (ex.: mandato em outro órgão,
--                                snapshot não capturado na data).
--   parlamentar_nao_resolvido  — identidade não casou com nenhuma linha de
--                                dim_parlamentar da mesma fonte.
--   data_nao_resolvida         — data_documento inválida/ausente: pré-requisito
--                                do matching por vigência não satisfeito.
--
-- Sempre reproduzível: reprocessa a classificação de
-- `desp_parlamento_classificacao`. A chave natural (fonte, cod_documento)
-- reconstitui a linha original de silver_despesa para auditoria.

with classificada as (
    select *
    from {{ ref('desp_parlamento_classificacao') }}
)

select
    fonte,
    cod_documento,
    id_parlamentar,
    nome_parlamentar,
    parlamentar_status as motivo,
    n_candidatos
from classificada
where parlamentar_status != 'parlamentar_resolvido'