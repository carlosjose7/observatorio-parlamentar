-- emenda_autor_quarantine — autoria de emenda NÃO promovida (ADR-017/ADR-018).
--
-- Todo o restante de autoria que não entra em `emenda_autor`, exposto para
-- auditoria com motivo explícito (coluna `motivo`):
--
--   autor_colegiado      — tipo_emenda é de autoria agregada (bancada/comissão);
--                          nunca passa por matching individual (ADR-017.3.a).
--   autor_ambiguo        — mais de um parlamentar vigente no ano com o mesmo
--                          nome; nunca grava id por critério arbitrário (3.c).
--   autor_fora_cobertura — nome existe no cadastro, mas sem versão de
--                          dim_parlamentar cobrindo o ano da emenda (3.e).
--   autor_nao_resolvido  — nome não casou com nenhuma linha de dim_parlamentar.
--
-- Sempre reproduzível: reprocessa a classificação de `em_autor_classificacao`.

with classificada as (
    select *
    from {{ ref('em_autor_classificacao') }}
)

select
    ano,
    codigo_emenda,
    tipo_emenda,
    nome_autor,
    nome_autor_normalizado,
    autor_status as motivo
from classificada
where autor_status != 'autor_resolvido'