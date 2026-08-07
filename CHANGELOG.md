# Changelog

Plataforma de Inteligência Parlamentar Brasileira.

Histórico das alterações, organizado por sprint (ver
`docs/governance/sprint_rules.md`). Segue as boas práticas do
[Keep a Changelog](https://keepachangelog.com/).

---

## Sprint 4 — Camada Gold (trilhas A e B)

### Adicionado
- ADRs 018–023: dbt Core no Gold com quarentena por construção,
  `pipeline_runs` DuckDB, SCD2 `dim_parlamentar` (Onda 2), tabelas
  analíticas §7, contrato de qualidade Gold e Silver sem caminho de
  carga (lacuna Sprints 2/3 → absorvida como ADR-023/Sprint 4).
- Gold dbt em `pipeline/gold/` (`profiles.yml`, `dbt_project.yml`,
  `models/sources.yml`, `models/dimensions/`) — `dim_data`,
  `dim_orgao` (seed), `dim_fornecedor`, `dim_categoria_despesa`, suas
  quarentenas por construção e `pipeline_runs` (incremental) —
  `dbt build` 35/35 verde.
- Plugin `pipeline/gold/hmac_udf.py` — UDF `hmac_sha256_cpf` (HMAC-SHA256
  sobre CPF na Gold; chave de `CPF_HMAC_SECRET_KEY`, sem vazar ao SQL).
- `pipeline/camara/transform.py`, `pipeline/senado/transform.py` e
  `pipeline/transparencia/transform.py` — caminho de carga Silver das 3
  fontes (ADR-023), incluindo `normalizar_nome_proprio` em `normalize.py`.
- Task `executar_silver` no `pipeline_dag.py` — conecta Bronze→Silver.

### Corrigido
- `sources.yml` do Gold sem `database:` explícito — catálogo DuckDB é o
  nome do arquivo (`observatorio`), não `main`; `schema: main` mapeia as
  fontes Silver.
- **`hmac_udf.py` — registro da UDF reescrito (regressão da Trilha B).** O
  original usava `con` (NameError) dentro de `try/except Exception: pass` —
  o erro real era mascarado (_anti-padrão §15_) e o registro era silencioso.
  Agora: guarda de idempotência consultando `duckdb_functions()` (sem
  casamento frágil de string de erro) e `null_handling=SPECIAL` (NULL /
  string vazia retornam NULL limpo em vez de falhar o build). Teste de
  regressão isolado `tests/pipeline/test_gold_hmac_udf.py` (5 cenários:
  digest, NULL/vazio, idempotência, chave ausente, erro real propagado).

---

## [Não publicadas] — pendências da Sprint 2

- ☐ CGU Emendas: conferir o comportamento de rollover de ano no
  incremental após o backfill (ver `BACKLOG.md`, Sprint 2).

---

## Sprint 2 — Pipeline Bronze

### Adicionado
- Extração e persistência em Bronze das três fontes
  (`pipeline/camara`, `pipeline/senado`, `pipeline/transparencia`) —
  Parquet + MinIO local, retry `tenacity` (ADR-009).
- Deduplicação por chave natural na escrita (read-merge-write,
  keep-first-seen) e `pipeline_runs` não-particionado por `run_id`.
- Watermark em store isolável (`JsonFileStore`,
  `AirflowVariableStore`, `NamespaceWatermarkStore`), persistido
  **após** escrita bem-sucedida (versionamento.md §2.1).
- Carga histórica na primeira execução (watermark vazio) via
  `carga_historica` por fonte em `config/sources.yaml`.
- Modo de validação (`validacao:` em `config/pipeline.yaml`) — janela
  truncada para `limite_periodos` + watermark em namespace isolado
  (Opção B).
- Schema de configuração Pydantic (ADR-008): `pipeline/config.py`,
  `config/sources.yaml`, `config/pipeline.yaml`.
- Smoke tests do pipeline Bronze (15 cenários, HTTP mockado).

### Corrigido
- Watermark do backfill de cartões: `_agregar_resultados` usava
  `max()` lexicográfico sobre `MM/AAAA`, escolhendo `12/2025` em vez
  de `08/2026` ao cruzar anos — agora usa o último período cronológico
  da janela, evitando que o incremental fique preso reprocessando o
  mesmo mês.

---

## Sprint 1 — Modelagem de Dados

### Adicionado
- ADR-010 — Dimensão institucional `dim_orgao` + `dim_unidade_gestora`
  (SIAFI-ready).
- ADR-011 — Refinamento da pseudonimização CPF/CNPJ (string vazia →
  NULL, distinção por comprimento).
- ADR-012 — Separação de fatos por domínio de negócio (constelação:
  `fact_despesa`, `fact_emenda`, `fact_cartao_cpgf`).
- Identificação do código SIAFI do Senado Federal (UG 020001,
  Gestão 00001).
- Confirmação de `codDocumento` (Câmara) em formato GUID (VARCHAR).
- Contratos Pydantic Bronze/Silver/Gold por fonte
  (`pipeline/camara/schemas.py`, `pipeline/senado/schemas.py`,
  `pipeline/transparencia/schemas.py`, `pipeline/gold.py`) e
  compartilhados em `pipeline/contracts.py`.
- Modelo ER completo em `docs/architecture/arch_er.md`.
- `docs/data/data_dictionary.md` — schemas Gold completos.
- Estratégia consolidada de watermark e versionamento
  (`docs/engineering/versionamento.md`, RF-01/RF-12).
- Convenção de código (comentários/docstrings em português;
  variáveis/funções/classes em inglês) em `PROJECT_CONTEXT.md §15`.

---

## Sprint 0B — Arquitetura da Solução

### Adicionado
- Provisionamento da VPS Oracle Cloud (Always Free,
  VM.Standard.A1.Flex 2 OCPU/12GB) com Docker, SSH hardening e
  Security List/UFW restritos.
- Revisão da stack tecnológica — versões fixas, dependências em
  `pyproject.toml`, Dockerfiles com grupos opcionais.
- Diagramas de alto nível: `docs/architecture/arch_medalhao.md`,
  `arch_deploy.md`, `arch_pipeline.md`.
- ADR-005 (Organização da documentação), ADR-006 (Stack e
  dependências), ADR-007 (Containers e deploy), ADR-008 (Configuração
  externa), ADR-009 (Batch/Lambda).
- `PROJECT_CONTEXT.md` v1.0 — stack, diagramas, diretórios e ADRs
  001-009.
- `docs/data/data_dictionary.md` — schemas reais da Câmara e Senado.
- Exploração da API da CGU — 3 endpoints documentados (emendas,
  cartões, órgãos).

---

## Sprint 0A — Descoberta e Produto

### Adicionado
- Visão do produto, 5 personas e casos de uso (CU-01 a CU-08).
- Requisitos funcionais (RF-01 a RF-12) e não funcionais (9
  categorias).
- Critérios de sucesso (Sprint 0A + produto) e escopo explícito da
  v1/MVP.
- Roadmap de 12 sprints (`docs/governance/sprint_rules.md` +
  `PROJECT_CONTEXT.md §13`).
- ADR-002 (contamination vs. threshold de score), ADR-003 (pesos do
  `risk_index`), ADR-004 (pseudonimização HMAC-SHA256 com salt fixo).
- `docs/data/data_dictionary.md` (estrutura inicial); deprecação de
  `docs/data/semantic_layer.md` em favor de `PROJECT_CONTEXT.md §8`.
- Aprovação dos papéis de desenvolvimento (Sprints 6.5, 7 e 9).
