-- fact_emenda_quarantine — emendas NÃO promovidas a fact_emenda (ADR-017/ADR-018).
--
-- Todo o complemento de fact_emenda: emendas cuja autoria não foi resolvida
-- individualmente, OU cujo órgão não resolveu contra dim_orgao, expostas para
-- auditoria com motivo explícito:
--
--   autor_colegiado      — autoria agregada (bancada/comissão); nunca recebe
--                          id_parlamentar (ADR-017.3.a).
--   autor_ambiguo        — mais de um parlamentar vigente no ano com o mesmo
--                          nome; id nunca gravado por critério arbitrário (3.c).
--   autor_fora_cobertura — nome existe no cadastro, mas sem versão de
--                          dim_parlamentar cobrindo o ano da emenda (3.e).
--   autor_nao_resolvido  — nome não casou com nenhuma linha de dim_parlamentar.
--   orgao_nao_resolvido  — autoria resolvida, mas a fonte da versão casada não
--                          mapeia para uma sigla de dim_orgao (ADR-012/ADR-022.1):
--                          a emenda é impedida pela FK de órgão, não pelo autor.
--
-- `id_parlamentar` permanece sempre NULL aqui — quando a autoria resolvia mas o
-- órgão não, a identidade não se perde: a emenda é reconstruível pela chave
-- natural (ano, codigo_emenda). Métricas/metadados de RF-12 vêm de silver_emenda;
-- o motivo vem da classificação ADR-017 (emenda_autor_quarantine) ou do órgão
-- (emenda_autor_orgao).

with nao_resolvidas as (
    select
        s.ano,
        s.codigo_emenda,
        null::bigint as id_parlamentar,
        null::bigint as id_orgao,
        null::bigint as id_unidade_gestora,
        cast(strftime(make_date(s.ano, 12, 31), '%Y%m%d') as bigint) as data_sk,
        s.tipo_emenda,
        s.nome_autor,
        s.funcao,
        s.subfuncao,
        s.localidade_do_gasto,
        s.valor_empenhado,
        s.valor_liquidado,
        s.valor_pago,
        q.motivo as motivo_quarentena,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version
    from {{ source('silver', 'silver_emenda') }} s
    inner join {{ ref('emenda_autor_quarantine') }} q using (ano, codigo_emenda)
),

orgao_nao_resolvido as (
    select
        s.ano,
        s.codigo_emenda,
        null::bigint as id_parlamentar,
        null::bigint as id_orgao,
        null::bigint as id_unidade_gestora,
        cast(strftime(make_date(s.ano, 12, 31), '%Y%m%d') as bigint) as data_sk,
        s.tipo_emenda,
        s.nome_autor,
        s.funcao,
        s.subfuncao,
        s.localidade_do_gasto,
        s.valor_empenhado,
        s.valor_liquidado,
        s.valor_pago,
        'orgao_nao_resolvido' as motivo_quarentena,
        s.run_id,
        s.pipeline_version,
        s.execution_timestamp,
        s.source_version
    from {{ ref('emenda_autor_orgao') }} eao
    inner join {{ source('silver', 'silver_emenda') }} s using (ano, codigo_emenda)
    where eao.id_orgao is null
)

select * from nao_resolvidas
union all
select * from orgao_nao_resolvido