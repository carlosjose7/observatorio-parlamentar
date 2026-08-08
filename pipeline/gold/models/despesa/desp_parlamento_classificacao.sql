-- desp_parlamento_classificacao — resolução do parlamentar de cada despesa
-- contra `dim_parlamentar` (SCD2), na vigência de `data_documento`.
--
-- Modelo efêmero compartilhado por `desp_parlamento` e
-- `desp_parlamento_quarantine`. Espelha o mecanismo de autoria do ADR-017
-- (`em_autor_classificacao`), adaptado às despesas:
--
--  1. a janela de validade é `[effective_date, end_date)` contendo
--     `data_documento` da despesa (não "vigência-por-ano", como nas emendas —
--     a despesa tem data exata do documento, ADR-020 aplicado ao dia);
--  2. o discriminador depende da fonte:
--     - `camara`: a Silver agora carrega `id_parlamentar` (id_deputado, captura
--       na extração) → matching exato **por id natural**;
--     - `senado`: a fonte CEAPS não expõe o id do senador — apenas o nome
--       (`nome_parlamentar`); matching exato do **nome normalizado** (macro
--       `nome_normalizado`, mesma regra de `pipeline.normalize`), no ADR-017.
--  3. O matching é restrito à `fonte` da própria despesa (deputados↔camara,
--     senadores↔senado) — homônimo de outra Casa não é candidato.
--  4. Classificação (uma por (fonte, cod_documento)):
--     - data inválida                                            → `data_nao_resolvida`
--     - 1 parlamentar vigente na data casado                     → `parlamentar_resolvido`
--     - >1 parlamentares vigentes casados                        → `parlamentar_ambiguo`
--       (nunca grava id por critério arbitrário — ADR-017.3.c/ADR-005)
--     - 0 casados, identidade conhecida no cadastro (id ou nome,
--       respeitando a fonte)                                      → `parlamentar_fora_cobertura`
--     - 0 casados e identidade desconhecida                      → `parlamentar_nao_resolvido`
--
-- `data_documento` nulo nem tenta o matching (pré-requisito da janela de
-- vigência) — a despesa vai à quarentena por construção, sem arriscar rótulo
-- incorreto de "fora_cobertura".
--
-- `n_candidatos` conta **pessoas** distintas (id natural); o `id_parlamentar`
-- resolvido e o `surrogate_key` saem apenas quando há exatamente um candidato.

{{ config(materialized='ephemeral') }}

with despesas as (
    select
        fonte,
        cod_documento,
        id_parlamentar,
        nome_parlamentar,
        cast(data_documento as date) as data_documento
    from {{ source('silver', 'silver_despesa') }}
),

candidatos as (
    select
        d.fonte,
        d.cod_documento,
        p.id_parlamentar,
        p.surrogate_key
    from despesas d
    inner join {{ref('dim_parlamentar') }} p
        on p.fonte = d.fonte
        and p.effective_date <= d.data_documento
        and (p.end_date is null or d.data_documento < p.end_date)
        and (
            (d.id_parlamentar is not null and p.id_parlamentar = d.id_parlamentar)
            or (
                d.nome_parlamentar is not null
                and p.nome_normalizado = {{ nome_normalizado('d.nome_parlamentar') }}
            )
        )
    where d.data_documento is not null
),

contagens as (
    select
        d.fonte,
        d.cod_documento,
        count(distinct c.id_parlamentar) as n_candidatos,
        min(c.id_parlamentar) as id_parlamentar_resolvido,
        min(c.surrogate_key) as surrogate_key
    from despesas d
    left join candidatos c using (fonte, cod_documento)
    group by d.fonte, d.cod_documento
),

-- identidades conhecidas no cadastro por fonte (para separar
-- `parlamentar_fora_cobertura` de `parlamentar_nao_resolvido`).
identidades as (
    select distinct fonte, id_parlamentar, nome_normalizado
    from {{ ref('dim_parlamentar') }}
)

select
    d.fonte,
    d.cod_documento,
    d.id_parlamentar,
    d.nome_parlamentar,
    case
        when d.data_documento is null then 'data_nao_resolvida'
        when cg.n_candidatos > 1 then 'parlamentar_ambiguo'
        when cg.n_candidatos = 1 then 'parlamentar_resolvido'
        when (
            (d.id_parlamentar is not null
                and exists (
                    select 1 from identidades k
                    where k.fonte = d.fonte and k.id_parlamentar = d.id_parlamentar
                ))
            or (d.nome_parlamentar is not null
                and exists (
                    select 1 from identidades k2
                    where k2.fonte = d.fonte
                      and k2.nome_normalizado = {{ nome_normalizado('d.nome_parlamentar') }}
                ))
        ) then 'parlamentar_fora_cobertura'
        else 'parlamentar_nao_resolvido'
    end as parlamentar_status,
    cg.n_candidatos,
    cg.id_parlamentar_resolvido,
    cg.surrogate_key
from despesas d
left join contagens cg using (fonte, cod_documento)