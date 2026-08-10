# Changelog

Plataforma de Inteligência Parlamentar Brasileira.

Histórico das alterações, organizado por sprint (ver
`docs/governance/sprint_rules.md`). Segue as boas práticas do
[Keep a Changelog](https://keepachangelog.com/).

---

## Sprint 6 — API (FastAPI / Onda 3 — anomalias, comunidades, qualidade e status)

### Adicionado
- **Onda 3 — os 4 endpoints restantes do §11** (`XXX`):
  `GET /anomalias?threshold=` (despesas sinalizadas da Gold `expense_outliers`,
  ADR-002/§10 — leitura de resultado, nunca re-execução de inferência; o
  `threshold` foi fixado na revisão desta Onda 3 como **piso de `zscore`**
  sobre o conjunto já sinalizado, coerente com o exemplo `?threshold=2.5` do
  §11; negativo/não-numérico → 422, mesmo contrato de erro da Onda 2);
  `GET /rede/comunidades` (agrupamento por `comunidade_id` dos nós já
  materializados em `network_nodes`, ADR-030 — nome resolvido das dimensões,
  parlamentar na versão vigente do SCD2, ADR-020);
  `GET /qualidade/relatorio` (Data Quality Report através de **ADR-031** —
  ver abaixo; `regras_violadas` desserializada em `list[str]`, filtro
  `tabela` + paginação);
  `GET /pipeline/status` (controle `pipeline_runs`, ADR-019 — execuções mais
  recentes primeiro, API observadora passiva do orquestrador). Schemas
  `api/schemas/anomalias.py`/`rede.py`/`qualidade.py`/`pipeline.py`
  (`extra="forbid"`), routers em `api/routers/` (mesmo padrão `_erro_gold`
  →503), quatro arquivos de teste em `tests/api` (19 testes). Suíte
  completa `tests` — **276 passed** (212 pipeline + 50 API + 14 integração).
- **Selo de contrato estendido à Onda 3** (`tests/integration/
  test_api_gold_contrato.py`, 10→14): valida contra o **dbt real** o bind das
  colunas de `expense_outliers` e `network_nodes` (200 honesto com staging
  vazio, ADR-030) e a promoção de `data_quality_report` + `control.pipeline_runs`
  (linha da Silver atravessa o model Gold e chega à API desserializada).
- **ADR-031** (`pipeline/gold/models/control/data_quality_report.sql` + novo
  registro no `ADR.md`): `data_quality_report` da Silver (ADR-015) promovida à
  Gold pelo mecanismo da Opção A do ADR-026 (dbt consome source → materializa
  Gold; precedente `pipeline_runs`). Reconcilia a leitura "direta" do ADR-015
  (pré-ADR-026) com a fronteira Gold-only do ADR-026 (posterior), superseding
  a interpretação literal. `schema.yml` do model declara `not_null` de
  `run_id`/`tabela`/totais.

### Corrigido
- **Materialização `table` para `data_quality_report`** (achado do próprio
  selo, `XXX`): `control` configura `incremental` e a tabela Silver de mesmo
  nome no schema `main` já existia — o dbt fazia `INSERT INTO` na existente
  (append: duplicava linhas e mantinha `execution_timestamp` VARCHAR em vez
  do TIMESTAMP do `try_cast`). Ao materializar como `table` (full replace,
  cria a Gold a partir da silver a cada build), a Gold emite 1 linha e
  coluna TIMESTAMP — o endpoint desserializa corretamente.

---

## Sprint 6 — API (FastAPI / Onda 2 — perfil, rede e fornecedores)

### Adicionado
- **Onda 2 — endpoints de negócio sobre o Gold materializado** (`9e3cb43`):
  `GET /parlamentares/{id}` (perfil vigente do SCD2, ADR-020 — resolve as
  colunas `sigla_partido`/`sigla_uf`/`situacao_normalizada` emitidas pelo
  `dim_parlamentar.sql`); `GET /parlamentares/{id}/rede` (consome
  `network_nodes`/`network_edges` **já promovidos ao Gold pelo dbt**, com join
  em `dim_fornecedor` para o nome — nunca recalcula PageRank/comunidades por
  request, ADR-030; staging de rede vazio ⇒ 200 honesto com listas vazias);
  `GET /fornecedores` (paginado, filtros `nome` ILIKE + `tipo_documento`
  validado em `^(CNPJ|CPF)$`); `GET /fornecedores/{cnpj_cpf_valor}` (dimensão
  + agregados sobre `fact_despesa`: `num_despesas`, `valor_liquido_total`);
  `GET /fornecedores/{cnpj_cpf_valor}/parlamentares` (parlamentares vigentes
  que gastaram no fornecedor, `total_gasto` desc). CNPJ exposto em claro; CPF
  **apenas pelo hash HMAC** (ADR-011) — buscar pelo número cru devolve 404
  honesto, nunca vaza dado pseudonimizado. Contratos `api/schemas/
  fornecedores.py` (novo) + extensão de `api/schemas/parlamentares.py`
  (`PerfilParlamentar`, `NoRede`, `ArestaRede`, `RedeParlamentar`, todos
  `extra="forbid"`). `api/repo.py` com `_tratar_erro_gold` centralizado sobre
  as 8 queries; routers `fornecedores.py` (novo) e `parlamentares.py` (estendido).
  Fixture determinística consolidada em `tests/api/conftest.py` (schema real
  do Gold, incl. `network_nodes`/`network_edges`, ADR-009).
- **Selo de contrato estendido à Onda 2** (`tests/integration/
  test_api_gold_contrato.py`, 5→10): agora valida, contra o **dbt real** do
  Gold, o perfil vigente (SCD2 → `PARTIDO B`), a listagem de fornecedores
  (CNPJ claro × CPF HMAC), o agregado parlamentar↔fornecedor e o **bind das
  colunas de rede** (`pagerank`/`degree_centrality`/`valor_total` do schema
  emitido) — uma coluna renomeada em `network_*.sql` quebra a suíte.
- Testes: `tests/api/test_parlamentares.py` 16→21; `tests/api/
  test_fornecedores.py` 10 (novo). Suíte completa `tests` — **253 passed**
  (212 pipeline + 31 API + 10 integração).

### Registrado
- **Dívida técnica aceita (backlog 6/6.5)** — paridade automatizada
  dbt model → `schema.yml` → Pydantic → API: os contratos são escritos à mão
  e já divergiram do schema emitido (`DimParlamentar` → `sigla_partido`/
  `sigla_uf`; `DimData` → `data`). O selo de contrato é a barreira detecta-
  falsos; a automação da paridade fica para o backlog. Não mexe no escopo da
  Onda 2.

---

## Sprint 6 — API (FastAPI / Onda 1 — infra + parlamentares)

### Adicionado
- **Onda 1 — Infra da API + contratos + endpoints `/parlamentares` e
  `/parlamentares/{id}/gastos`** (`61968f6`):
  `config/api.yaml` + `ApiSettings` em `pipeline/config.py` (ADR-008 —
  identificação da API, host/porta, paginação e `ano_minimo_consulta` como
  régua de recurso; nenhum limite hardcoded). Camada read-only `api/repo.py`
  com fronteira de leitura exclusiva do Gold via `DUCKDB_DATABASE_PATH`
  (ADR-026 — nunca Bronze/Silver/`ml_staging`); falhas de driver/esquema
  degradam como `GoldIndisponivel` → HTTP 503 (schema Gold desatualizado não
  vaza 500 ao cliente). Contratos de resposta em `api/schemas/parlamentares.
  py` (`extra="forbid"`, selo de contrato) espelhando as colunas REALMENTE
  emitidas pelos modelos dbt — ex.: `dim_parlamentar.sql` emite
  `sigla_partido`/`sigla_uf`/`situacao_normalizada`, divergente do contrato
  estrutural `gold.py:DimParlamentar` (registro consciente do descompasso
  schema-declarado vs. schema-emitido). Endpoints paginados no router
  `parlamentares.py`: lista de vigentes do SCD2 (`is_current`, ADR-020) com
  filtros nome (`nome_normalizado` ILIKE, accent/case insensitive) / uf /
  partido; gastos com dimensões resolvidas (`dim_data`, `dim_categoria_
  despesa`, `dim_fornecedor`), filtro por ano, ordenação por data desc,
  404 de parlamentar inexistente e 422 de validação de query. `api/main.py`
  consome a config (título/versão) e preserva `/` e `/health` (sem regressão
  do scaffold v0.1). Testes `tests/api/test_parlamentares.py` (16, fixture com
  DuckDB determinístico de schema real do Gold + TestClient) cobrindo SCD2,
  filtros, paginação, dimensões de gastos, 404/422/503. Suíte completa
  `tests` — **228 passed** (212 pipeline + 16 API).

### Corrigido
- **Selo de contrato pipeline → Gold → API** (`5f4131f`): a revisão da Onda 1
  apontou que provávamos "API × Gold" mas não "Gold produzido pelo pipeline
  atual × API". Criado `tests/integration/test_api_gold_contrato.py` (5), que
  roda o **dbt real do projeto Gold** (mesma seleção comprovada
  `_SELECAO_FATO` de `test_gold_despesa.py`) via subprocesso (o adaptador
  dbt-duckdb mantém conexão read-write por processo; isolando o build, a API
  reabre o arquivo estritamente `read_only` — ADR-026, como em produção) e
  direciona a API ao Gold construído. O selo **apanhou drift real**: a API
  lia `dim_data.data_completa`, mas o modelo emite `dim_data.data` (mais um
  caso do descompasso `gold.py:DimData.data_completa` vs. schema-emitido) — a
  consulta de gastos foi corrigida para `d.data` e o fixture de
  `tests/api/test_parlamentares.py` alinhado ao schema real. Agora qualquer
  mudança de coluna/nome dos modelos Gold quebra a suíte. Suíte completa
  `tests` — **233 passed** (212 pipeline + 16 API + 5 integração).

---

## Sprint 5 — Analytics + ML + Redes (Onda 4 — `risk_scores`)

### Adicionado
- **Onda 4 — Scores de risco + `risk_index`** (`7192692`):
  `pipeline/risk.py` — os 5 scores individuais do ADR-027 consumindo os
  raws das Ondas anteriores no grão `(periodo, id_parlamentar)` (sem
  redesenhar fórmula): `supplier_concentration_score` (HHI da Gold
  `supplier_concentration`, ADR-021), `political_exposure_score`
  (média_{f∈F_p}(n_f−1) sobre `fact_despesa` promovido, ADR-018),
  `supplier_dependency_score` (média de `dep_f = Σ_p share²` do fornecedor,
  BACKLOG item 173), `expense_anomaly_score` (`a_p` = anomalias/despesas de
  p via `is_anomalia` do `ml_staging.expense_outliers`), `network_
  influence_score` (PageRank do nó parlamentar em `ml_staging.network_nodes`).
  Normalização **Min-Max por período** em [0,1] via feature reutilizável
  `normalizar_minmax` (`minmax` do registry, ADR-003/028; série constante →
  0.0; raw ausente → 0.0 sem sinal) e composição `risk_index = Σ_i w_i ·
  score_i` com pesos de `config/analytics.yaml → risk.pesos` (ADR-029, 0.2
  uniforme baseline; `RiskSettings` Pydantic valida chaves exatas, >0 e
  soma 1). Escrita exclusiva em `ml_staging.risk_scores` (ADR-026, Opção A).
  Model dbt Gold `risk_scores.sql` (`exists` contra `dim_parlamentar`, sem
  inner join por SCD2 — ADR-020) + contrato `RiskScores` em `gold.py` +
  `sources.yml`/`schema.yml` (not_null de scores/`risk_index`, FK
  `fk_orphan_pct` warn). Testes: `test_risk.py` (19) + `test_gold_risk.py`
  (2, fluxo dbt em 2 fases: Gold vazia com staging vazio → split de scores
  com o staging populado, risco = 0.2×Σ scores). Suíte completa
  `tests/pipeline` — **210 passed**.

### Corrigido
- **Granularidade da média do `political_exposure_score`** (`9ab951b`):
  `_df_exposure()` mediava no grão da DESPESA, mas o ADR-027 define
  `média_{f∈F_p} (n_f − 1)` — média sobre o conjunto `F_p` de fornecedores
  DISTINTOS de p no período. A versão antiga dava peso proporcional ao nº de
  lançamentos do fornecedor (P1: F1 com 1 despesa e F2 com 3 → 1,75 em vez
  de 1,5). Corrigido reduzindo o fato a `(periodo, id_parlamentar,
  id_fornecedor)` distinto antes da média; teste de contrato
  `test_df_exposure_media_sobre_fornecedores_distintos` prova que a média
  por fornecedor difere da média por despesa.
- **Contrato de não-negatividade do `valor_liquido` para o HHI**:
  `supplier_dependency_score` (e `supplier_concentration`) pressupõem
  `v_{p,f} >= 0` (share ∈ [0,1], `dep_f ∈ [1/n, 1]`). Essa premissa já era
  garantida pelo gate Silver Pandera (`quality.py`, `Check.ge(0)`, ADR-013 —
  negativos vão à quarentena) e agora é reafirmada no Gold com o test
  genérico `nao_negativo` em `fact_despesa.valor_liquido` (`warn`, ADR-022.3a)
  + invariante executável `test_df_dependency_invariante_hhi_nao_negativo`.
  **212 passed**.

---

## Sprint 5 — Analytics + ML + Redes (Ondas 1–3 — implementação)

### Adicionado
- **Onda 1 — Feature Store + Analytics estatística** (`84de54d`):
  `pipeline/features.py` (ADR-028) — modelo Pydantic `Feature`/
  `FeatureRegistry` + enum `FeatureCategoria` (`agregado|ml|composicao|
  funcao`), validação do `feature_store/registry.yaml` (campos
  obrigatórios: nome, descricao, formula, origem, tipo, categoria,
  ultima_atualizacao, consumidores; só `funcao` dispensa `tabela`);
  primeiras features registradas (as 5 fórmulas de score do ADR-027,
  `risk_index` como composição, funções derivadas `minmax`/`regra_anomalia`
  — ADR-002/§10). `pipeline/analytics.py` — estatística descritiva
  (ResumoEstatistico: média, mediana, desvio padrão, percentil 95 etc.)
  e correlações, puras e determinísticas, consumindo fatos Gold no grão
  correto e correspondendo a features do registry. Testes:
  `test_features.py` (registry válido + feature não-órfã, ADR-028.5)
  e `test_analytics.py`.
- **Correção de lineage no Feature Registry** (`a6b239e`): `supplier_
  concentration_score` ajustado no `registry.yaml` — `origem:
  supplier_concentration` (não `fact_despesa`), alinhando com ADR-021.
- **Onda 2 — Detecção de anomalias `expense_outliers`** (`6a2e957`):
  `pipeline/anomalies.py` — definição formal de anomalia do §10/ADR-002:
  despesa é **anomalia** quando satisfaz **pelo menos 2 dos 6 critérios**
  (`is_anomalia = num_criterios >= 2`); critérios: Z-score > 2.5 vs.
  histórico do parlamentar, Isolation Forest score < −0.1 (contamination
  0.05 — hiperparâmetro de **treino**; threshold é regra de **decisão em
  inferência**, distinção ADR-002 preservada), fornecedor < 3 clientes,
  empresa < 12 meses, valores idênticos ≥ 3 no mês, dia sem sessão; reusa
  a feature `regra_anomalia` do registry (ADR-028). Escrita exclusiva em
  `ml_staging.expense_outliers` (ADR-026). Model dbt Gold
  `expense_outliers.sql` (só `is_anomalia=true` promovido, inner join com
  `fact_despesa` — ADR-018) + contrato `ExpenseOutliers` em `gold.py` +
  `sources.yml`/`schema.yml`. Testes: `test_anomalies.py` +
  `test_gold_expense_outliers.py`.
- **Onda 3 — Rede + clusterização** (`76ce55b`): `pipeline/network.py` —
  grafo **bipartido** parlamentar↔fornecedor a partir de `fact_despesa`
  (nós `p:`/`f:`, aresta `v_{p,f}` agregada no período = peso); por
  período (grão ano) calcula PageRank **global** (ADR-030.1 — `network_
  influence_score` cru, ADR-027.5), centralidade de grau, comunidades
  (`greedy_modularity`, determinísticas — RF-12) e similaridade de
  cosseno entre parlamentares por sobreposição de fornecedores
  (`politician_similarity`, §7/CU-08, ordem canônica a<b); escrita
  exclusiva em `ml_staging.network_edges|network_nodes|politician_
  similarity` (ADR-026/030); disjuntor `rede.limite_arestas_recorte`
  (50000, `config/analytics.yaml` → `get_analytics()`, ADR-008/030.3).
  `pipeline/config.py` ganhou `AnalyticsSettings`/`RedeSettings` +
  `load_analytics_settings()`. Models dbt Gold `network_edges.sql`/
  `network_nodes.sql`/`politician_similarity.sql` — `exists` contra as
  dimensões (SCD2 `dim_parlamentar`, never inner join);
  `network_nodes.id_no` polimórfico condicionado a `tipo_no`. Contratos
  `NetworkEdges`/`NetworkNodes`/`PoliticianSimilarity` em `gold.py` +
  `sources.yml`/`schema.yml` (`accepted_values` para `tipo_no`, FK
  `fk_orphan_pct` warn). Testes: `test_network.py` (18) +
  `test_gold_network.py` (2, fluxo dbt em 2 fases com cenário de
  fornecedor compartilhado). Suíte completa `tests/pipeline` — **189
  passed**.

---

## Sprint 5 — Analytics + ML + Redes (Onda 0 — Arquitetura)

### Adicionado
- ADR-026 — Fronteira de escrita dbt ↔ Python/ML no Gold: Python
  (`pipeline/analytics/`) escreve exclusivamente em schema `ml_staging`
  (DuckDB, single-writer); dbt consome como `source()` e materializa
  `risk_scores`, `expense_outliers`, `network_edges`, `network_nodes`,
  `politician_similarity` como models Gold regulares (`schema.yml` +
  `relationships` + `fk_orphan_pct` ADR-022.3a). Opção C (models dbt
  `language: python`) avaliada e descartada.
- ADR-027 — Fórmulas explícitas dos 5 scores individuais (§9):
  `supplier_concentration_score` (norm(hhi), ADR-021),
  `political_exposure_score`, `supplier_dependency_score`,
  `expense_anomaly_score` (proporção de anomalias §10; Isolation Forest
  é um dos 6 critérios, não o score isolado), `network_influence_score`
  (PageRank). Fecha o ciclo do ADR-003.
- ADR-028 — Contrato da Feature Store: `pipeline/features.py` (Pydantic
  `Feature`/`FeatureRegistry`, enum `FeatureCategoria`) validando
  `feature_store/registry.yaml`; campos obrigatórios fecham
  `ml_feature.md`; `test_features.py` garante registry válido e feature
  não-órfã.
- ADR-029 — Revisão de pesos do `risk_index`: baseline 0.2 vigente
  durante a Sprint 5 (configurável via `config/analytics.yaml`); a
  revisão empírica ocorre **após a Sprint 6.5** (≥12 meses de
  `fact_despesa` real), via ADR de amendment do ADR-003.
- ADR-030 — Materialização do grafo NetworkX: recálculo **total por
  execução** (`run_id, periodo`) em `ml_staging`, models dbt Gold
  clean-slate; limite de arestas como disjuntor com alerta no DQ Report.

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
- Agregados analíticos puros do ADR-021 (Onda 3) — `pipeline/gold/models/analytics/`
  (`supplier_concentration` HHI por parlamentar/ano, `supplier_growth`
  crescimento YoY por fornecedor/ano) com contrato em `pipeline/gold.py`
  (`SupplierConcentration`, `SupplierGrowth`) e testes
  `tests/pipeline/test_gold_analytics.py`.

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
