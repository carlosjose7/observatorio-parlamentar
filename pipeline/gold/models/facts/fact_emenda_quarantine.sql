-- fact_emenda_quarantine — emendas NÃO promovidas a fact_emenda (ADR-017/ADR-018).
--
-- Todo o complemento de fact_emenda: emendas cuja autoria não foi resolvida
-- individualmente, expostas para auditoria com motivo explícito:
--
--   autor_colegiado      — autoria agregada (bancada/comissão); nunca recebe
--                          id_parlamentar (ADR-017.3.a).
--   autor_ambiguo        — mais de um parlamentar vigente no ano com o mesmo
--                          nome; id nunca gravado por critério arbitrário (3.c).
--   autor_fora_cobertura — nome existe no cadastro, mas sem versão de
--                          dim_parlamentar cobrindo o ano da emenda (3.e).
--   autor_nao_resolvido  — nome não casou com nenhuma linha de dim_parlamentar.
--
-- `id_parlamentar` permanece sempre NULL aqui — o motivo explica o porquê.
-- As métricas e metadados de RF-12 vêm de silver_emenda; o motivo vem da
-- classificação ADR-017 (emenda_autor_quarantine espelhada no grão fato).

with nao_resolvidas as (
    select
        s.ano,
        s.codigo_emenda,
        s.tipo_emenda,
        s.nome_autor,
        s.funcao,
        s.subfuncao,
        s.localidade_do_gasto,
        s.valor_empenhado,
        s.valor_liquidado,
        s.valor_pago,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version,
        q.motivo as motivo_quarentena,
        cast(strftime(make_date(s.ano, 12, 31), '%Y%m%d') as bigint) as data_sk
    from {{ source('silver', 'silver_emenda') }} s
    inner join {{ ref('emenda_autor_quarantine') }} q using (ano, codigo_emenda)
)

select
    ano,
    codigo_emenda,
    null::bigint as id_parlamentar,
    null::bigint as id_orgao,
    null::bigint as id_unidade_gestora,
    data_sk,
    tipo_emenda,
    nome_autor,
    funcao,
    subfuncao,
    localidade_do_gasto,
    valor_empenhado,
    valor_liquidado,
    valor_pago,
    motivo_quarentena,
    run_id,
    pipeline_version,
    execution_timestamp,
    source_version
from nao_resolvidas