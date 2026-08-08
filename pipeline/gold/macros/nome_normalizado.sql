-- macros/nome_normalizado.sql — normalização pt-BR de nomes para joins Gold.
--
-- Espelha `pipeline.normalize.normalizar_nome_proprio` (uppercase + remoção
-- de acentos) para permitir matching determinístico entre vocabulários de
-- nomes distintos na fronteira Silver→Gold (usado pelo ADR-017: `nome_autor`
-- da CGU contra `nome` de `dim_parlamentar`). A Silver já normaliza
-- `silver_emenda.nome_autor` em Python; este macro garante a mesma regra na
-- dimensão — sem depender de UDF, e idempotente sobre texto já normalizado.

{% macro nome_normalizado(coluna) -%}
    translate(
        upper({{ coluna }}),
        'ÁÀÂÃÄÅÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
        'AAAAAAEEEEIIIIOOOOOUUUUC'
    )
{%- endmacro %}