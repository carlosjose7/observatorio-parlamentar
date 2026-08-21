# Arquitetura Agent-Ready (RF-05)

A API expõe endpoints de **JSON semântico agregado** para consumo direto por
LLMs — implementados na **Onda 4 da Sprint 6** conforme o **ADR-032**. A
definição de contrato vive em `api/schemas/agent.py` (Pydantic,
`extra="forbid"`); este documento descreve o desenho e a fronteira.

## Princípios (ADR-032)

1. **Agent-ready ≠ espelho.** Os payloads `/agent/*` **não** repetem os
   endpoints de negócio paginados (`/parlamentares`, `/anomalias`, ...).
   Refletem a **Camada Semântica** (`PROJECT_CONTEXT.md §8`) e os **scores de
   risco** (§9/ADR-027/ADR-028): um objeto aninhado com rótulos semânticos e
   datas ISO.
2. **Mesma fronteira da API** (ADR-026): leitura read-only da camada Gold;
   nenhuma métrica analítica é recalculada por request (ADR-030) — as
   agregações são SQL sobre o Gold **materializado** pelo pipeline.
3. **Escopo da Camada Semântica:** `taxa_ausencia`/`indice_alinhamento`
   (§8) ficam fora — dependem de `fact_presenca`/`fact_votacao`, ainda
   inexistentes no Gold. `hhi` vem de `supplier_concentration` (grão
   `ano × id_parlamentar`).
4. **Vocabulário rastreável:** nomes de métricas/scores seguem §8, §9 e o
   registro da Feature Store (ADR-028), não abreviações locais do endpoint.

## Endpoints

### `GET /agent/parlamentar/{id}` — contexto de um parlamentar

- Perfil vigente do SCD2 (`dim_parlamentar`, ADR-020): nome, partido, UF,
  situação e início da vigência.
- Métricas §8 (`fact_despesa`): `total_gasto`, `gasto_medio`,
  `num_transacoes`, `num_fornecedores`, `valor_maximo`, `valor_mediano`,
  `percentil_95`.
- `hhi_recente`/`hhi_periodo` (`supplier_concentration`) e
  `risk_index` + 5 scores do período mais recente (`risk_scores`, ADR-027/029).
- Contagem/proporção de despesas anômalas (`expense_outliers`, ADR-002) e
  **top-5 fornecedores por valor** (nome resolvido em `dim_fornecedor`).

### `GET /agent/fornecedor/{cnpj_cpf_valor}` — contexto de um fornecedor

- Perfil (`dim_fornecedor`): nome, tipo de documento.
- Agregados (`fact_despesa`): `total_recebido`, `gasto_medio`, `valor_maximo`,
  `num_transacoes`, `num_parlamentares`.
- **Top-5 parlamentares por valor** (nome + total; join com a versão
  `is_current` do SCD2).
- CNPJ casa exatamente; CPF está pseudonimizado (ADR-011) e **não** casa pelo
  número cru — busca por CPF retorna 404 honesto.

### `GET /agent/anomalias` — resumo agregado de anomalias

Não é a lista crua paginada (`/anomalias`): retorna `total`, contagem **por
ano**, contagem **por critério** disparado (§10) e **top-10 por zscore** com
nome do parlamentar.

### `GET /agent/context` — retrato sistêmico (CU-07)

Visão agregada do Gold para o LLM situar a conversa: métricas globais
(`total_gasto`, `num_transacoes`, `num_fornecedores`, `num_parlamentares`,
`num_anomalias`), períodos com dados, resumo do último
`data_quality_report` (ADR-031) e da última execução `pipeline_runs`
(ADR-019).

## Fronteira de erros

Mesmas regras das demais ondas: Gold ausente/desatualizada → **503** ("Camada
Gold indisponível"); alvo inexistente → **404** nominal; contrato Pydantic
`extra="forbid"` (campos inesperados são rejeitados). O contrato contra o Gold
**real** emitido pelo dbt é travado no selo
`tests/integration/test_api_gold_contrato.py` (Onda 4: seed de
`ml_staging.risk_scores` + `supplier_concentration` derivada pelo dbt).
