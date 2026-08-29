"""pipeline/schemas_silver.py — schema explícito das tabelas Silver (DuckDB).

Declara os tipos DuckDB e as descrições (comentários de catálogo) de cada
tabela da camada Silver. Substitui a inferência de tipos do DuckDB na criação
de tabela — que é frágil (coluna de texto integralmente nula era inferida
como `INTEGER`, derrubando o INSERT de outra fonte) — por um DDL explícito,
além de documentar o schema via `COMMENT ON` (consultável em
`duckdb_tables()`/`duckdb_columns()`, exposto à API).

Cada entrada: `nome_coluna: (tipo_duckdb, descricao)`.

Camadas Silver (ADR-023/ADR-024):
- `silver_despesa`       — fatos de despesas (Câmara e Senado), grão documento.
- `silver_parlamentar`   — snapshots de parlamentares (Câmara e Senado), SCD2.
- `silver_cartao`        — transações de cartões de pagamento (CGU/CPGF).
- `silver_emenda`        — emendas parlamentares (CGU/Portal da Transparência).

Tabelas de apoio (reusam o mesmo mecanismo de DDL explícito):
- `data_quality_report`  — relatório de qualidade (ADR-015).
- `quarantine_*`         — linhas em quarentena (ADR-013).
- `dedup_removidas_*`    — linhas removidas pela dedup (ADR-014).

Metadados comuns a todas as Silver (RF-12), sempre VARCHAR:
`run_id`, `pipeline_version`, `execution_timestamp`, `source_version`.
"""

from __future__ import annotations

# ── Tabela de despesas (Câmara e Senado) ─────────────────────────
SCHEMA_SILVER_DESPESA: dict[str, tuple[str, str]] = {
    "fonte": ("VARCHAR", "Casa legislativa de origem: 'camara' ou 'senado'."),
    "id_parlamentar": ("BIGINT", "Identificador canônico do parlamentar na fonte."),
    "nome_parlamentar": (
        "VARCHAR",
        "Nome do parlamentar responsável pela despesa (preenchido no Senado; "
        "na Câmara pode ser nulo no grão da despesa — resolver via silver_parlamentar).",
    ),
    "ano": ("BIGINT", "Ano de competência da despesa."),
    "mes": ("BIGINT", "Mês de competência da despesa."),
    "cod_documento": ("VARCHAR", "Identificador único do documento na fonte."),
    "data_documento": ("TIMESTAMP_NS", "Data de emissão do documento."),
    "tipo_despesa": ("VARCHAR", "Natureza/espécie da despesa."),
    "cnpj_cpf_valor": (
        "VARCHAR",
        "CNPJ ou digest HMAC-SHA256 do CPF do fornecedor (ADR-033).",
    ),
    "tipo_documento": ("VARCHAR", "'CNPJ' ou 'CPF' conforme o documento do fornecedor."),
    "nome_fornecedor": ("VARCHAR", "Nome do fornecedor/beneficiário."),
    "valor_liquido": ("DOUBLE", "Valor líquido da despesa em reais."),
    "valor_glosa": ("DOUBLE", "Valor de glosa/cancelamento em reais."),
    "run_id": ("VARCHAR", "Identificador da execução do pipeline (RF-12)."),
    "pipeline_version": ("VARCHAR", "Versão do pipeline que gerou o registro (RF-12)."),
    "execution_timestamp": ("VARCHAR", "Timestamp da execução (RF-12)."),
    "source_version": ("VARCHAR", "Versão da fonte/dados na extração (RF-12)."),
}

# ── Snapshot de parlamentares (SCD2, Câmara e Senado) ────────────
SCHEMA_SILVER_PARLAMENTAR: dict[str, tuple[str, str]] = {
    "fonte": ("VARCHAR", "Casa legislativa de origem: 'camara' ou 'senado'."),
    "id_parlamentar": ("BIGINT", "Identificador canônico do parlamentar na fonte."),
    "nome": ("VARCHAR", "Nome do parlamentar."),
    "sigla_partido": ("VARCHAR", "Sigla do partido na vigência."),
    "sigla_uf": ("VARCHAR", "UF do parlamentar."),
    "id_legislatura": (
        "BIGINT",
        "Legislatura derivada do calendário legislativo (ADR-024).",
    ),
    "id_legislatura_fonte": ("BIGINT", "Legislatura bruta da fonte (auditoria)."),
    "situacao_bruta": ("VARCHAR", "Situação original informada pela fonte."),
    "situacao_normalizada": ("VARCHAR", "Situação na taxonomia canônica."),
    "url_foto": ("VARCHAR", "URL da foto do parlamentar na fonte (Câmara/Senado)."),
    "data": ("TIMESTAMP_NS", "Data as-of do snapshot (chave do SCD2)."),
    "run_id": ("VARCHAR", "Identificador da execução do pipeline (RF-12)."),
    "pipeline_version": ("VARCHAR", "Versão do pipeline que gerou o registro (RF-12)."),
    "execution_timestamp": ("VARCHAR", "Timestamp da execução (RF-12)."),
    "source_version": ("VARCHAR", "Versão da fonte/dados na extração (RF-12)."),
}

# ── Cartões de pagamento (CGU/CPGF) ──────────────────────────────
SCHEMA_SILVER_CARTAO: dict[str, tuple[str, str]] = {
    "id": ("BIGINT", "Identificador numérico nativo da transação na CGU."),
    "data_transacao": ("TIMESTAMP_NS", "Data da transação."),
    "valor_transacao": ("DOUBLE", "Valor da transação em reais."),
    "estabelecimento_cnpj_valor": (
        "VARCHAR",
        "CNPJ ou digest HMAC-SHA256 do CPF do estabelecimento (ADR-033).",
    ),
    "estabelecimento_tipo_documento": ("VARCHAR", "'CNPJ' ou 'CPF'."),
    "estabelecimento_nome": ("VARCHAR", "Nome do estabelecimento."),
    "portador_nome": ("VARCHAR", "Nome do portador do cartão."),
    "portador_cpf_mascarado": ("VARCHAR", "CPF mascarado do portador."),
    "unidade_gestora_codigo": ("VARCHAR", "Código da unidade gestora."),
    "unidade_gestora_nome": ("VARCHAR", "Nome da unidade gestora."),
    "run_id": ("VARCHAR", "Identificador da execução do pipeline (RF-12)."),
    "pipeline_version": ("VARCHAR", "Versão do pipeline que gerou o registro (RF-12)."),
    "execution_timestamp": ("VARCHAR", "Timestamp da execução (RF-12)."),
    "source_version": ("VARCHAR", "Versão da fonte/dados na extração (RF-12)."),
}

# ── Emendas parlamentares (CGU/Portal da Transparência) ──────────
SCHEMA_SILVER_EMENDA: dict[str, tuple[str, str]] = {
    "ano": ("BIGINT", "Ano de competência da emenda."),
    "codigo_emenda": ("VARCHAR", "Código da emenda (chave de negócio)."),
    "tipo_emenda": ("VARCHAR", "Tipo da emenda (ex: individual, de bancada...)."),
    "nome_autor": ("VARCHAR", "Autor da emenda normalizado (ADR-016)."),
    "funcao": ("VARCHAR", "Função orçamentária."),
    "subfuncao": ("VARCHAR", "Subfunção orçamentária."),
    "localidade_do_gasto": ("VARCHAR", "Localidade do gasto."),
    "valor_empenhado": ("DOUBLE", "Valor empenhado em reais."),
    "valor_liquidado": ("DOUBLE", "Valor liquidado em reais."),
    "valor_pago": ("DOUBLE", "Valor pago em reais."),
    "run_id": ("VARCHAR", "Identificador da execução do pipeline (RF-12)."),
    "pipeline_version": ("VARCHAR", "Versão do pipeline que gerou o registro (RF-12)."),
    "execution_timestamp": ("VARCHAR", "Timestamp da execução (RF-12)."),
    "source_version": ("VARCHAR", "Versão da fonte/dados na extração (RF-12)."),
}

# ── Catálogo: nome da tabela → schema declarativo ───────────────
SCHEMAS_SILVER: dict[str, dict[str, tuple[str, str]]] = {
    "silver_despesa": SCHEMA_SILVER_DESPESA,
    "silver_parlamentar": SCHEMA_SILVER_PARLAMENTAR,
    "silver_cartao": SCHEMA_SILVER_CARTAO,
    "silver_emenda": SCHEMA_SILVER_EMENDA,
}

# Descrição (comentário) de cada tabela principal.
DESCRICOES_TABELAS: dict[str, str] = {
    "silver_despesa": (
        "Fatos de despesas parlamentares de Câmara e Senado — grão por "
        "documento, com deduplicação por (fonte, cod_documento) e gate de "
        "qualidade Pandera (ADR-013/ADR-014)."
    ),
    "silver_parlamentar": (
        "Snapshots de parlamentares (Câmara e Senado) — alimenta a "
        "dim_parlamentar SCD2 da Gold; legislatura derivada do calendário "
        "(ADR-024)."
    ),
    "silver_cartao": (
        "Transações de cartões de pagamento do governo federal (CGU/CPGF) — "
        "dedup por chave nativa `id` (ADR-012)."
    ),
    "silver_emenda": (
        "Emendas parlamentares do Portal da Transparência (CGU) — dedup por "
        "(ano, codigo_emenda); marcador 'S/I' isolado em quarentena (ADR-017)."
    ),
}


def schema_para_tabela(tabela: str) -> dict[str, tuple[str, str]] | None:
    """Retorna o schema declarativo de `tabela`, ou `None` se não mapeada.

    Tabelas de apoio (`data_quality_report`, `quarantine_*`,
    `dedup_removidas_*`) não têm schema declarativo — continuam usando a
    inferência do DuckDB (sem o risco de colunas de texto nulas, pois são
    tabelas de controle geradas internamente).
    """
    return SCHEMAS_SILVER.get(tabela)


def descricao_para_tabela(tabela: str) -> str | None:
    """Descrição (comentário de catálogo) de `tabela`."""
    return DESCRICOES_TABELAS.get(tabela)
