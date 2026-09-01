{% macro generate_schema_name(custom_schema_name, node) -%}
    {# Override padrão do dbt: evita `<profile_schema>_<custom>` e usa só
       o custom schema (ex: `gold` em vez de `main_gold`).  ADR-042. #}
    {% if custom_schema_name %}
        {{ custom_schema_name | trim }}
    {% else %}
        {{ target.schema }}
    {% endif %}
{%- endmacro %}
