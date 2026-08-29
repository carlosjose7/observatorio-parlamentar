-- dim_parlamentar — dimensão de parlamentares, SCD Type 2 (ADR-020).
--
-- Derivada de `silver_parlamentar`: um registro por **versão** de
-- parlamentar, ou seja, o histórico rastreável de mudanças de
-- partido/UF/situação (RF-11). Cada versão cobre o intervalo
-- `[effective_date, end_date)` e `is_current` marca a versão vigente hoje.
--
-- Nota de implementação (Onda 2): o ADR-020 prevê carga por merge/upsert.
-- Aqui a dimensão é **recomputada deterministicamente** a partir do
-- histórico completo de snapshots da Silver (imutável, append-only por data
-- as-of): uma nova versão começa quando a tupla rastreada
-- `(nome, sigla_partido, sigla_uf, situacao_normalizada)` difere da versão
-- anterior. Isso é idempotente e reprocessável (RF-12) e produz a mesma
-- tabela que N execuções de merge por snapshot — o `end_date` da versão
-- fechada usa a data as-of da observação seguinte, mais preciso que a data
-- da execução.
--
-- `surrogate_key` é BIGINT determinístico, nunca reaproveitado: compõe
-- `(código da fonte, id_parlamentar, nº da versão)` — estável e idempotente.
--
-- Regra de validade (quarentena por construção, ADR-018): identidade
-- obrigatória (`nome`, `id_parlamentar`) e observação plausível
-- (`id_legislatura > 0`, `data` não nula). Silver já excluiu essas linhas
-- no gate (ADR-024) — a quarentena aqui é defesa em profundidade.
--
-- Consumo ADR-017 (vigência-por-ano, ADR-020): a versão de um parlamentar
-- válida em um ano é aquela cujo intervalo [effective_date, end_date)
-- intercepta qualquer data daquele ano.

with observacoes as (
    select
        fonte,
        id_parlamentar,
        nome,
        sigla_partido,
        sigla_uf,
        situacao_normalizada,
        id_legislatura,
        url_foto,
        cast(data as date) as data,
        run_id,
        execution_timestamp
    from {{ source('silver', 'silver_parlamentar') }}
    where
        nome is not null
        and id_parlamentar is not null
        and id_legislatura > 0
),

-- Marca quando a observação inicia nova versão: difere da anterior na
-- janela (fonte, id_parlamentar) ordenada por data as-of.
legado as (
    select
        *,
        case
            when lag(nome) over particao is null then 1
            when (
                coalesce(lag(nome) over particao, '') <> coalesce(nome, '')
                or coalesce(lag(sigla_partido) over particao, '') <> coalesce(sigla_partido, '')
                or coalesce(lag(sigla_uf) over particao, '') <> coalesce(sigla_uf, '')
                or coalesce(lag(situacao_normalizada) over particao, '') <> coalesce(situacao_normalizada, '')
                or coalesce(lag(url_foto) over particao, '') <> coalesce(url_foto, '')
            ) then
                1
            else
                0
        end as nova_versao
    from observacoes
    window particao as (
        partition by fonte, id_parlamentar
        order by data
    )
),

versoes_brutas as (
    select
        *,
        sum(nova_versao) over (
            partition by fonte, id_parlamentar order by data
        ) as id_versao
    from legado
),

versoes as (
    select
        fonte,
        id_parlamentar,
        id_versao,
        min(data) as effective_date,
        -- dentro de uma versão nome/partido/UF/estado são constantes por
        -- construção; guarda a legislatura mais recente observada no intervalo.
        max(id_legislatura) as id_legislatura,
        max(execution_timestamp) as execution_timestamp
    from versoes_brutas
    group by fonte, id_parlamentar, id_versao
),

atributos_versao as (
    -- Rebaixa os atributos rastreados (constantes dentro da versão) para o
    -- grão versão, garantindo que o registro só carregue o que é estável.
    select distinct
        vb.fonte,
        vb.id_parlamentar,
        vb.id_versao,
        v.effective_date,
        v.id_legislatura,
        v.execution_timestamp,
        vb.nome,
        vb.sigla_partido,
        vb.sigla_uf,
        vb.situacao_normalizada,
        vb.url_foto
    from versoes_brutas vb
    join versoes v
        on v.fonte = vb.fonte
        and v.id_parlamentar = vb.id_parlamentar
        and v.id_versao = vb.id_versao
),

preenchida as (
    select
        *,
        lead(effective_date) over (
            partition by fonte, id_parlamentar order by id_versao
        ) as end_date
    from atributos_versao
)

select
    -- surrogate determinístico e idempotente; nunca reaproveitado
    (
        case when fonte = 'senado' then 200000000000 else 100000000000 end
        + cast(id_parlamentar as bigint) * 1000 + id_versao
    ) as surrogate_key,
    fonte,
    id_parlamentar,
    nome,
    {{ nome_normalizado('nome') }} as nome_normalizado,
    sigla_partido,
    sigla_uf,
    situacao_normalizada,
    url_foto,
    id_legislatura,
    effective_date,
    end_date,
    case when end_date is null then true else false end as is_current
from preenchida
order by fonte, id_parlamentar, effective_date