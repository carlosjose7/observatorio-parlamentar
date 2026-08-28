# BACKLOG.md
# Plataforma de Inteligência Parlamentar Brasileira

> Backlog vivo do projeto. Atualizado ao final de cada sprint pelo
> papel de Documentador. Itens concluídos não são removidos —
> permanecem marcados como referência histórica.

---

## Sprint 0A — Descoberta e Produto

☑ Definir visão do produto e proposta de valor
☑ Definir personas (5 perfis de usuário)
☑ Definir casos de uso (CU-01 a CU-08)
☑ Definir requisitos funcionais (RF-01 a RF-12)
☑ Definir requisitos não funcionais (9 categorias)
☑ Definir critérios de sucesso (Sprint 0A + produto)
☑ Definir escopo explícito da v1/MVP (dentro/fora do escopo)
☑ Validar roadmap de 12 sprints (`docs/governance/sprint_rules.md` + `PROJECT_CONTEXT.md §13`)
☑ Auditoria de consistência entre artefatos do projeto (15 artefatos revisados)
☑ Reconciliar divergência de contagem de sprints (12 sprints confirmado)
☑ ADR-002 — Formalizar distinção `contamination` vs. threshold de score (Isolation Forest)
☑ ADR-003 — Definir pesos do `risk_index` (0.2 uniforme, baseline Sprint 0B)
☑ ADR-004 — Atualizar pseudonimização de CPF (salt fixo → HMAC-SHA256)
☑ Criar `docs/data/data_dictionary.md` (estrutura inicial)
☑ Deprecar `docs/data/semantic_layer.md` em favor de `PROJECT_CONTEXT.md §8`
☑ Aprovar papéis de desenvolvimento para sprints 6.5, 7 e 9 (`PROJECT_CONTEXT.md §12`)

☑ Atualizar `PROJECT_CONTEXT.md` com as seções 1.1–1.5 (casos de uso, RF, RNF, critérios de sucesso, escopo) — conteúdo já aprovado, pendente de inclusão física no arquivo
☑ Atualizar `PROJECT_CONTEXT.md §12` removendo nota de "proposto" (papéis já aprovados)
☑ Bump de versão `PROJECT_CONTEXT.md` para 0.4

---

## Sprint 0B — Arquitetura da Solução

☑ Provisionar VPS Oracle Cloud (Always Free) — instância VM.Standard.A1.Flex (2 OCPU/12GB), compartment observatorio-parlamentar, VCN/subnet dedicadas, Docker instalado, SSH hardening aplicado (root/senha desabilitados), Security List + UFW restritos ao IP de administração
☑ Revisar stack tecnológica (`PROJECT_CONTEXT.md §4`) — versões fixas, dependências adicionadas ao `pyproject.toml`, Dockerfiles atualizados para usar grupos opcionais
☑ Consolidar diagramas de alto nível — `docs/architecture/arch_medalhao.md`, `arch_deploy.md`, `arch_pipeline.md`
☑ Validar estrutura de diretórios (`PROJECT_CONTEXT.md §6`) — sincronizada com o disco, incluindo `nginx/`, `scripts/`, `infra/cloud-config.yaml`, `.dockerignore`, `LICENSE`, `pyproject.toml` e diretórios de sprint com anotações
☑ Formalizar diretório infra/ no PROJECT_CONTEXT.md §6 (cloud-init Oracle Cloud)
☑ Registrar ADRs iniciais de arquitetura — ADR-005 (Organização da documentação), ADR-006 (Stack e dependências), ADR-007 (Containers e deploy), ADR-008 (Configuração externa), ADR-009 (Batch/Lambda)
☑ Consolidar `PROJECT_CONTEXT.md` v1.0 — stack, diagramas, diretórios, ADRs 001-009 e versão final da sprint
☑ Atualizar `docs/data/data_dictionary.md` — schemas reais da Câmara e Senado (Sprint 0B)
☑ Obter chave da API CGU e explorar schema real — 3 endpoints documentados (emendas, cartões, órgãos), campos mortos identificados, padrão transversal de valores/datas/CNPJ registrado
---

## Backlog Futuro (pós-v1 — fora do escopo do MVP, ver `PROJECT_CONTEXT.md §1.5`)

☐ Cruzamento com dados eleitorais do TSE
☐ Enriquecimento via CNAE
☐ Autenticação/autorização de usuários
☐ Alertas automáticos/notificações proativas de anomalias
☐ Versionamento multi-tenant ou multi-instância do dashboard

---
## Sprint 1 — Modelagem de Dados

☑ ADR-010 — Dimensão institucional `dim_orgao` + `dim_unidade_gestora` (SIAFI-ready, fonte_origem genérica)
☑ ADR-011 — Refinamento da pseudonimização CPF/CNPJ (string vazia → NULL, distinção por comprimento, schema `dim_fornecedor` revisado)
☑ ADR-012 — Separação de fatos por domínio de negócio (modelo de constelação: `fact_despesa`, `fact_emenda`, `fact_cartao_cpgf`)
☑ Código SIAFI do Senado Federal identificado (UG 020001, Gestão 00001) — pendência da Sprint 0B resolvida
☑ Correção de tipagem `codDocumento` (Câmara) — confirmado formato GUID, tipado VARCHAR
☑ Documentado requisito de parsing explícito de `dataDocumento` (Câmara) e datas pt-BR (Senado/CGU) na Silver
☑ `data_dictionary.md` — schemas completos Gold (`dim_orgao`, `dim_unidade_gestora`, `dim_fornecedor` revisado, `fact_despesa` com FKs institucionais)
☑ Modelo ER completo em Mermaid (`docs/architecture/arch_er.md`) — constelação de fatos com dimensões compartilhadas
☑ Contratos de interface Pydantic — Bronze/Silver por fonte (`pipeline/camara/schemas.py`, `pipeline/senado/schemas.py`, `pipeline/transparencia/schemas.py`) e Gold (`pipeline/gold.py`)
☑ Contratos compartilhados centralizados em `pipeline/contracts.py` (LoadMetadata, TipoDocumento, Poder, FonteOrigemUnidadeGestora, resolve_tipo_documento)
☑ Decisão de estrutura de diretórios — Opção A confirmada (sem novas pastas `schemas/`/`gold/`, aderente a `PROJECT_CONTEXT.md §6`)
☑ Convenção de código atualizada (`PROJECT_CONTEXT.md §15`) — comentários/docstrings em português, variáveis/funções/classes em inglês
☑ Estratégia consolidada de watermark e versionamento (`docs/engineering/versionamento.md`) — RF-01/RF-12, cobrindo as três fatos e tabela de controle `pipeline_runs`
☑ `PROJECT_CONTEXT.md §7` atualizado — modelo dimensional completo com constelação de fatos, FKs institucionais e regras de nullability documentadas

### Pendências em aberto (não bloqueiam fechamento, mas devem ser resolvidas antes da Sprint 2)

☑ Decimal confirmado para campos monetários em Silver/Gold (precisão sobre performance)
☐ Código SIAFI da Câmara dos Deputados — ainda não identificado (não bloqueia grão de `dim_orgao`)
☑ Revisão técnica cruzada de todos os artefatos da Sprint 1 — 3 achados de sincronia de documentação corrigidos (catálogo `data_dictionary.md` reposicionado, nota obsoleta removida, cabeçalho/rodapé `PROJECT_CONTEXT.md` atualizado)
☐ Atualizar `PROJECT_CONTEXT.md §6` (estrutura de diretórios) para refletir os arquivos novos criados nesta sprint (`pipeline/contracts.py`, `pipeline/camara/schemas.py` etc.) — ainda dentro da estrutura existente, mas os nomes de arquivo específicos não estavam listados
☑ `CHANGELOG.md` — criado como artefato formal na Sprint 2 (commit `285eab8`)

---

## Sprint 2 — Pipeline Bronze

☑ Implementar extração e persistência em Bronze das três fontes (`pipeline/camara`, `pipeline/senado`, `pipeline/transparencia`) — Parquet + MinIO local, retry tenacity (ADR-009)
☑ Deduplicação por chave natural na escrita (read-merge-write, keep-first-seen) e `pipeline_runs` não-particionado por run_id
☑ Watermark em store isolável; persistido **após** escrita bem-sucedida (versionamento.md §2.1)
☑ Carga histórica na primeira execução (watermark vazio) com `carga_historica` por fonte em `config/sources.yaml`
☑ Modo de validação (`validacao:` em `config/pipeline.yaml`) — janela truncada + watermark em namespace isolado (Opção B)
☑ Smoke tests 15/15 passando (backfill multi-ano, cartões cruza-anos, isolamento de watermark)

### Observações de implementação

☑ **Senado — carga histórica (resolvida).** Durante a implementação notou-se que a extração
   era "só o ano corrente", sem parâmetro de backfill isolado na fonte (ADR-009). Isso já não
   se aplica: a Sprint 2 provê backfill/backfil histórico via `carga_historica.ano_inicio` do
   Senado, que varre os anos até o corrente na primeira carga. Nota deprecada.

☐ **CGU Emendas — rollover de ano após o backfill (a conferir).** O campo de watermark de
   emendas guarda o último ano processado. Com a janela virando lista de anos truncada, o
   problema lexicográfico do `max()` já não se aplica (ano é só número), mas vale confirmar o
   comportamento pós-backfill: ao virar o ano seguinte, o incremental deve avançar para o ano
   novo (e não reprocessar indefinidamente o ano do watermark).

---

## Sprint 3 — Pipeline Silver e Qualidade

☑ ADR-013 — Fronteira de validação Pydantic vs. Pandera (registro individual vs. DataFrame agregado; quarentena de inválidos)
☑ ADR-014 — Deduplicação independente por camada (Silver deduplica pela chave de negócio pós-normalização, não assume a Bronze)
☑ ADR-015 — Data Quality Report persistido em tabela estruturada (`data_quality_report` particionada por `run_id`)
☑ ADR-016 — Módulo dedicado de normalização multi-fonte (`pipeline/normalize.py`)
☑ ADR-017 — Política de resolução de autor de emenda (individual vs. colegiado); execução diferida para a Sprint 4 (dependência de camada); chave de dedup composta `(ano, codigo_emenda)`
☑ Pipeline Silver — motor completo (dedup ADR-014, gate Pandera ADR-013, persistência DuckDB, DQ Report ADR-015) — **nota corretiva (ADR-023): apenas o motor foi entregue; o caminho de carga (transform.py) não existe e foi absorvido como pré-requisito da Sprint 4/Onda 1**
☑ Quarentena de registros inválidos (`quarantine_*`) — não descartar nem derrubar a execução
☑ `data_quality_report` — persistido a cada execução, agora com `registros_deduplicados`
☑ Helper de parse (`pipeline/normalize.py`) — encerra em NULL/NaT + log estruturado, nunca exceção; coberto por testes unitários isolados
☑ Fechar Sprint 3 — 55 testes passando; cobertura `pytest-cov` da subárvore `pipeline` em **82%** (RNF ≥80% satisfeito)

### Onda 2 — `silver_emenda` e `silver_cartao` (expansão de escopo da Sprint 3)

☑ `silver_cartao` — reutiliza `normalize`/`quality`; schema Pandera próprio com `unidade_gestora_codigo`/`unidade_gestora_nome` **NOT NULL** (reflete `fact_cartao_cpgf`, ADR-012); UK do fato não fixada no schema (o `id` nativo da CGU não chega à Silver)
☑ `silver_emenda` — reutiliza `normalize`/`quality`; chave de dedup composta **`(ano, codigo_emenda)`** (ADR-017); `nome_autor` normalizado e `tipo_emenda` fielmente tipado, **sem** tentativa de `id_parlamentar` (deferido ao Gold)
☑ **Persistência das linhas removidas pela dedup da Silver** — `escrever_dedup_removidas_duckdb` grava em `dedup_removidas_{tabela}` (padrão `quarantine_` reusado) e `data_quality_report` contabiliza `registros_deduplicados` (extensão ADR-015). Distingue "removido por duplicação real" de "removido por chave mascarada `S/I`" (ADR-017)
☑ Tratar `codigo_emenda = "S/I"` como anomalia de qualidade — `_codigo_emenda_nao_si` no gate de `silver_emenda` (observado na amostragem da API, ADR-017)

### Dívida consciente registrada (Sprint 8 — Testes/cobertura)

☐ **Cobertura `pipeline/silver.py` em 77%** — abaixo da média do módulo (`quality.py` 96%, `normalize.py` 97%) e do limiar global de 80%. O global de 82% já satisfaz a RNF, mas a base de orquestração (`carregar_tabela_silver`, duckdb persistence) merece elevação na Sprint 8.
☐ **Ruff não configurado** — segue como dívida técnica de lint; coberto na Sprint 8 junto com a elevação de cobertura.

### Escopo futuro explícito (não nesta sprint)

☐ **RF-07 — HTML do Data Quality Report.** a geração de relatório HTML fica reservada para a
   Sprint de documentação automática (RF-07), consumindo a tabela `data_quality_report` —
   não implementada na Sprint 3 (ADR-015).

---

## Sprint 4 — Camada Gold (pré-requisitos herdados da Sprint 3)

> **Pré-requisito documental:** a promoção de `fact_emenda` não pode ocorrer
> sem implementar a política de resolução de autor definida no **ADR-017**
> (matching por nome contra `dim_parlamentar` SCD2, vigente no ano da emenda;
> quarentena com motivos `autor_colegiado`/`autor_nao_resolvido`/`autor_ambiguo`).

### Planejamento arquitetural — ADRs 018–023 (concluído)

☑ **ADR-018 — dbt Core no Gold com quarentena por construção** (sem hooks Pandera): dbt entra de vez na camada Gold (ADR-006 postergado para a Sprint 4); quarentena expressa como par de models `{entidade}.sql`/`{entidade}_quarantine.sql` (regra no próprio SQL); `schema.yml` como segunda camada de checagem; Pandera segue exclusivo da fronteira Bronze→Silver; dbt é a única forma regular de escrita no Gold.
☑ **ADR-019 — `pipeline_runs` Parquet (Bronze) → DuckDB (Gold)**: tabela controla em DuckDB, model dbt incremental chaveado por `run_id`; Bronze Parquet permanece como source/registro imutável e como dbt source (`sources.yml`); `scripts/backfill_pipeline_runs.py` migra o histórico das Sprints 2/3.
☑ **ADR-020 — SCD Type 2 para `dim_parlamentar`**: merge/upsert por snapshot (fecha vigente, insere nova versão); vigência-por-ano via `[effective_date, end_date)` (insumo do ADR-017 na Onda 2); `surrogate_key` BIGINT por versão.
☑ **ADR-021 — Tabelas analíticas §7**: agregados puros (`supplier_concentration`, `supplier_growth`) populados na Onda 1; dependentes de ML/rede (`risk_scores`, `expense_outliers`, etc.) criadas como schema vazio (placeholder) e populadas só na Sprint 5.
☑ **ADR-022 — Contrato de qualidade Gold**: `relationships` + `not_null` por FK em `schema.yml` para todo fato; motivo de FK órfã na quarentena (`motivo_quarentena = 'fk_orfa:{coluna}'`); singular tests de FK com `severity: warn` + threshold > 5% configurável, sem bloquear `dbt build`; falha estrutural (`not_null`/`unique`) bloqueia (o `dbt build` é o gate).
☑ **ADR-023 — Silver sem caminho de carga**: verificação contra o repo revelou que os 3 `transform.py` (Câmara, Senado, CGU) não existem; `carregar_tabela_silver` nunca é chamada; o DAG só tem `_executar_bronze`. Os 3 módulos entram como **pré-requisito da Onda 1** (Trilha B), com interface comum (cada um usa `normalize.py` e chama `carregar_tabela_silver` com chave/campos por entidade).

### Trilha A — Não bloqueada (não depende de `silver_*` populada)

☑ Setup do Gold: `gold/` com `profiles.yml` (target DuckDB, **um único arquivo** `DUCKDB_DATABASE_PATH`), `dbt_project.yml`, `models/sources.yml` (lê `main.silver_*` no mesmo DuckDB); `dbt-duckdb`/`dbt-core` já no grupo `pipeline` do pyproject.
☑ `dim_data` — calendário completo gerado (2015 em diante, início real da Câmara), `data_sk` YYYYMMDD e flags; fine como model dbt sem dependência de fonte.
☑ `dim_orgao` — tabela de referência institucional semeada (Câmara, Senado com UG/Gestão SIAFI), **não** derivada de `silver_despesa` (que não tem coluna de órgão).

### Trilha B — Bloqueada até os `transform.py` (pré-requisito ADR-023)

☑ `transform.py` Câmara → `silver_despesa` (`fonte=camara`, chave `["fonte","cod_documento"]`, ADR-023) + DAG task Silver — `pipeline/camara/transform.py`.
☑ `transform.py` Senado → `silver_despesa` (`fonte=senado`, mesmo contrato) — `pipeline/senado/transform.py`.
☑ `transform.py` CGU → `silver_emenda` (chave `["ano","codigo_emenda"]`) e `silver_cartao` (chave `["id"]`, id nativo da CGU propagado até a Silver) + DAG task Silver — `pipeline/transparencia/transform.py`.
☑ `pipeline_dag.py` — task `executar_silver` conectando Bronze→Silver (ADR-023), agregando os 4 `carregar_silver_*` com XCom.
☑ `dim_fornecedor` — de `silver_despesa` com CPF pseudonimizado na Silver (ADR-033: HMAC-SHA256 aplicado no `transform.py`, `pipeline/pseudonymize.py`; CNPJ claro) + `tipo_documento` (ADR-011) + quarentena por construção.
☑ `dim_categoria_despesa` — de `silver_despesa.tipo_despesa` + quarentena.
☑ `pipeline_runs` dbt incremental operante (glob no Bronze Parquet; sem arquivos → **zero linhas**, nunca linha fictícia — `where false` com schema compatível); pendente o `scripts/backfill_pipeline_runs.py` para migrar o histórico das Sprints 2/3 (ADR-019).
☑ Agregados analíticos puros (`supplier_concentration`, `supplier_growth`) populados (ADR-021) — Onda 3 (`models/analytics/`, HHI por parlamentar/ano + crescimento YoY por fornecedor/ano; contratos em `gold.py`).
☐ `supplier_concentration` cobre granularidade por-parlamentar (HHI do gasto do parlamentar em fornecedores). Granularidade complementar por-fornecedor (HHI da dependência do fornecedor em parlamentares) **não foi modelada** — pré-requisito de `supplier_dependency_score` (§9, ADR-003) na Sprint 5.

### Onda 2 — `dim_parlamentar` SCD2 + mecanismo ADR-017

> **Pré-requisito de cobertura (decisão do usuário):** os dados mestres
> Bronze→Silver precisam cobrir **Câmara e Senado**, e o SCD2 no Gold só
> inicia após essa cobertura. Sem as duas Casas, `fact_emenda` mascara
> emendas de senador como `autor_nao_resolvido` (ADR-017) e `dim_parlamentar`
> nasceria parcial. A implementação foi fatiada por Casa.

- ☑ **Câmara — dados mestres Bronze→Silver** (`e3a5275`): extração de deputados
  (lista paginada + detalhe com `ultimoStatus`), snapshot `parlamento/camara/`,
  colunas de Silver centralizadas em `pipeline/silver.py` (ADR-023).
- ☑ **Senado — dados mestres Bronze→Silver**: `extract_senadores` via
  `GET /senador/lista/atual.json` (lista já traz partido/UF/legislatura; sem
  request por id), snapshot `parlamento/senado/`, fonte='senado', task
  `senado_parlamentares` no DAG.
- ☑ `dim_parlamentar` SCD Type 2 (ADR-020) — `effective_date`/`end_date`/`is_current`/`surrogate_key`; recomputada deterministicamente do histórico de snapshots (idempotente, `end_date` na data as-of real, não da execução); quarentena por construção (ADR-018).
- ☑ Resolução autor → `id_parlamentar` em Gold (ADR-017): `tipo_emenda` como discriminador de colegiado (`emenda_tipos_colegiados`, var dbt a validar com o catálogo real); matching por nome normalizado contra a versão vigente no ano da emenda (`[effective_date, end_date)`).
- ☑ Mecanismo de qualidade/quarentena do Gold para `autor_colegiado`/`autor_nao_resolvido`/`autor_ambiguo`/`autor_fora_cobertura` — `emenda_autor` (só resolvido) + `emenda_autor_quarantine` (motivos `autor_colegiado`/`autor_ambiguo`/`autor_fora_cobertura`/`autor_nao_resolvido`); classificação centralizada no modelo efêmero `em_autor_classificacao`.
- ☑ **ADR-024 — paridade semântica `silver_parlamentar` (Câmara×Senado)**: `id_legislatura` derivada de calendário (`pipeline/parlamento.py`, nunca da API) + `gt(0)` no gate (fim do bug do `0` do Senado); `situacao_bruta` + `situacao_normalizada` (de-para versionado, sentinela `nao_mapeado`).
- ☐ **Catálogo real de `situacao` (ação de seguimento do ADR-024)**: na primeira captura real, verificar vocabulários de `DescricaoParticipacao` (Senado) e `ultimoStatus.situacao` (Câmara) e adicionar ao de-para com teste.
- ☐ **Manutenção periódica do calendário `LEGISLATURAS` (ação de seguimento do ADR-024)**: a derivação de `id_legislatura` cobre as legislaturas 54ª–58ª (fim exclusivo em 2031-02-01); snapshots além da janela caem no gate `gt(0)` → quarentena. **Gatilho**: ampliar `pipeline/parlamento.py::LEGISLATURAS` a cada início de legislatura (ex.: 59ª a partir de 2031-02-01, cobre a janela 2035 do `dim_data` Gold). **Dono**: owner do pipeline.
- ☐ **`dim_unidade_gestora` ATIVADA na Onda 3 (substitui o item schema-only
  acima, ADR-025)**: com o `fact_cartao_cpgf` a fonte existe no grão (a própria
  CGU entrega `unidadeGestora.codigo`) e o contrato exige a FK NOT NULL — a
  dimensão foi materializada a partir de `silver_cartao` (chave natural
  `(fonte_origem='CGU', codigo)`) e o seed `dim_orgao` ganhou o Poder
  Executivo genérico (sigla `EX`, JOIN por sigla — ADR-022.1, sem literal).

### Onda 3 — Fatos

☑ `fact_despesa` (Câmara/Senado) — promoção da Silver + checks `relationships` (ADR-022).
☑ **`fact_cartao_cpgf` (CGU — ADR-012/ADR-025)**: promoção da Silver com
   `id_unidade_gestora` NOT NULL (dimensão ativada na Onda 3, ver item acima) e
   `id_orgao` = EX por construção; `cartao_unidade` (efêmero) resolve UG+órgão,
   `cartao_fornecedor` resolve `id_fornecedor` nullable (ADR-011); quarentena
   `fact_cartao_cpgf_quarantine` com `motivo_quarentena` (`orgao_nao_resolvido`/
   `unidade_gestora_nao_resolvida`/`data_nao_resolvida`); checks `relationships`
   + `not_null` + test custom `fk_orphan_pct` (ADR-022.3a). Teste de integração
   `tests/pipeline/test_gold_cartao.py` (promoção, lag EX→quarentena, órfãos
   acima/abaixo do limiar).
☑ `fact_emenda` (CGU) — promoção via `emenda_autor` (ADR-017): somente autoria individual resolvida sem ambiguidade; `fact_emenda_quarantine` com `motivo_quarentena` (`autor_colegiado`/`autor_ambiguo`/`autor_fora_cobertura`/`autor_nao_resolvido`/`orgao_nao_resolvido`); `id_orgao` derivado por JOIN de `dim_orgao` via `sigla` (CD/SF) da `fonte` da versão casada (`emenda_autor_orgao`) — sem literal hardcoded (ADR-022.1), não-match → quarentena `orgao_nao_resolvido`; `data_sk` em 31/12/ano; checks `relationships` + `not_null` + test custom `fk_orphan_pct` com threshold percentual >5% (var `fk_orfas_threshold_pct`, fonte única `data_quality.fk_orfas_threshold_pct` em `config/pipeline.yaml` injetada via `get_dbt_vars()`) e severidade `warn` (ADR-022.3a).
☑ `schema.yml` + singular tests de cada fato (referencial/órfãos `warn`, estrutura `error`).
☐ Placeholder das tabelas de ML (ADR-021) como schema vazio.

---

## Sprint 5 — Analytics + ML + Redes

> **Dono:** Cientista de Dados (PROJECT_CONTEXT §12). Roadmap da Sprint 5
> (§13) define estatística, detecção de anomalias, clusterização, análise
> de redes (NetworkX), scores de risco e tabelas analíticas.

### Onda 0 — Arquitetura (ADRs)

☑ **ADR-026 — Fronteira de escrita dbt ↔ Python/ML no Gold (Aceito)**:
   Python (`pipeline/analytics/`) escreve exclusivamente em schema
   `ml_staging` (DuckDB, single-writer); dbt consome como `source()` e
   materializa `risk_scores`, `expense_outliers`, `network_edges`,
   `network_nodes`, `politician_similarity` (placeholders ADR-021, item
   217) como models Gold regulares com `schema.yml`/`relationships`/
   `fk_orphan_pct` (ADR-022.3a, `severity: warn`). Opção C (models dbt
   `language: python`) avaliada e descartada — reabertura exige ADR de
   superseding.
☑ **ADR-027 — Fórmulas explícitas dos 5 scores individuais do §9**
   (Aceito): `supplier_concentration_score` (norm(hhi_p), ADR-021),
   `political_exposure_score` (norm(média (n_f − 1) dos fornecedores)),
   `supplier_dependency_score` (norm(média dep_f; HHI por fornecedor,
   granularidade do item 173)), `expense_anomaly_score` (norm(proporção
   de anomalias §10/ADR-002)), `network_influence_score` (norm(PageRank
   bipartido)). `risk_index` = Σ w_i·score_i, w_i=0.2 (ADR-003/ADR-029).
☑ **ADR-028 — Contrato da Feature Store** (Aceito): `pipeline/features.py`
   (modelo Pydantic `Feature`/`FeatureRegistry` + enum `FeatureCategoria`
   `agregado|ml|composicao|funcao`), valida `feature_store/registry.yaml`;
   campos obrigatórios (nome, descrição, fórmula, origem, tipo, categoria,
   última atualização, consumidores) fecham `ml_feature.md`; teste
   `test_features.py` garante registry válido e feature não-órfã.
☑ **ADR-029 — Revisão dos pesos do `risk_index`** (Aceito): pesos 0.2
   permanecem baseline durante toda a Sprint 5 (configuráveis via
   `config/analytics.yaml` → `risk.pesos`); revisão empírica é evento
   **pós-Sprint 6.5** (≥12 meses de `fact_despesa` real no Gold), via
   ADR de amendment do ADR-003, com sensibilidade + validação de face;
   pesos só mudam por ADR, nunca por operação manual.
☑ **ADR-030 — Materialização do grafo NetworkX** (Aceito): recálculo
   **total por execução** de `network_edges`/`network_nodes` chaveado por
   `(run_id, periodo)` em `ml_staging`, models dbt Gold clean-slate
   (ADR-026); PageRank global invalida incremental simples; limite de
   arestas (`config/analytics.yaml` → `rede.limite_arestas_recorte`) vira
   disjuntor com alerta no DQ Report para ADR de superseding futuro;
   `politician_similarity` compartilha o mesmo staging.

### Ondas 1–3 (implementadas)

☑ **Onda 1 — Feature Store + Analytics estatística** (`84de54d`,
   lineage corrigida em `a6b239e`): `pipeline/features.py` (ADR-028) —
   contrato Pydantic `Feature`/`FeatureRegistry` + `FeatureCategoria`
   (`agregado|ml|composicao|funcao`) validando `feature_store/registry.
   yaml`; features registradas (5 fórmulas de score do ADR-027,
   `risk_index`, funções `minmax`/`regra_anomalia`); `pipeline/analytics.
   py` — estatística descritiva + correlações determinísticas; testes
   `test_features.py`/`test_analytics.py`.
☑ **Onda 2 — Detecção de anomalias** (`6a2e957`): `pipeline/anomalies.py`
   conforme §10/ADR-002 — `is_anomalia = num_criterios >= 2` dos 6
   critérios (Z-score > 2.5, Isolation Forest contra `0.05`/threshold
   `< −0.1` com distinção treino×inferência preservada, fornecedor < 3
   clientes, empresa < 12 meses, valores idênticos ≥ 3 no mês, dia sem
   sessão); reuso da feature `regra_anomalia` (ADR-028);
   `ml_staging.expense_outliers` (ADR-026) + Gold `expense_outliers`
   (inner join `fact_despesa`, ADR-018) com contrato em `gold.py`;
   testes `test_anomalies.py`/`test_gold_expense_outliers.py`.
☑ **Onda 3 — Rede + clusterização** (`76ce55b`): `pipeline/network.py` —
   grafo **bipartido** parlamentar↔fornecedor de `fact_despesa`
   (PageRank global do período — never subgrafo, ADR-030.1; centralidade
   de grau; comunidades determinísticas RF-12; similaridade de cosseno
   `politician_similarity` CU-08/§7); `ml_staging.network_edges|
   network_nodes|politician_similarity` (ADR-026/030) + Gold com `exists`
   condicionado por `tipo_no`/dimensões (SCD2-safe); disjuntor
   `rede.limite_arestas_recorte=50000` (ADR-030.3); contratos em
   `gold.py`/`schema.yml`; testes `test_network.py` (18) +
   `test_gold_network.py` (2). Suíte `tests/pipeline` — 189 passed.

### Onda 4 (implementada)

☑ **Onda 4 — Scores + risk_index** (`7192692`): `pipeline/risk.py` —
   os 5 scores individuais do ADR-027 consumindo os raws das Ondas 1–3 no
   grão `(periodo, id_parlamentar)`: `supplier_concentration_score` (HHI
   Gold `supplier_concentration`), `political_exposure_score` (média_{f∈F_p}
   (n_f−1) de `fact_despesa`), `supplier_dependency_score` (`dep_f = Σ_p
   share²` do fornecedor), `expense_anomaly_score` (`a_p` de
   `ml_staging.expense_outliers`) e `network_influence_score` (PageRank de
   `ml_staging.network_nodes`). Normalização Min-Max **por período** via
   feature `normalizar_minmax` (ADR-003/028) + `risk_index = Σ w_i·score_i`
   com `risk.pesos` de `config/analytics.yaml` (0.2 uniforme, ADR-029;
   `RiskSettings` valida soma 1). `ml_staging.risk_scores` (ADR-026) + Gold
   `risk_scores.sql` (`exists` SCD2-safe) com contrato em `gold.py`/
   `schema.yml`; testes `test_risk.py` (19) + `test_gold_risk.py` (2).
   **Correção pós-revisão** (`9ab951b`): média do `political_exposure_score`
   agora sobre os fornecedores DISTINTOS de p (únidade de média do ADR-027,
   não a despesa) + test genérico Gold `nao_negativo` em
   `fact_despesa.valor_liquido` (contrato do HHI, já garantido na Silver
   pelo Pandera `ge(0)` — ADR-013). Suíte `tests/pipeline` — **212 passed**.

---

## Sprint 6 — API (FastAPI)

> **Onda 1 concluída** — infra da API + contratos de resposta sobre o Gold +
> primeiros endpoints de negócio do `PROJECT_CONTEXT.md §11`. Fronteira de
> leitura exclusiva do Gold (DuckDB read-only via `DUCKDB_DATABASE_PATH`,
> ADR-026); falhas de esquema degradam como HTTP 503 (Gold indisponível).
> **Onda 2 concluída** — perfil completa, rede materializada e fornecedores com
> agregados (Gold consultado diretamente; nenhuma análise é recalculada por
> request — ADR-030). **Onda 3 concluída** — anomalias (threshold = piso de
> zscore), comunidades, qualidade/relatório (ADR-031) e pipeline/status.
> **Onda 4 concluída** — endpoints agent-ready (ADR-032): JSON semântico
> agregado para LLMs (`/agent/parlamentar`, `/agent/fornecedor`,
> `/agent/anomalias` resumo, `/agent/context` retrato sistêmico).

### Onda 1 (implementada)

☑ **Onda 1 — Infra da API + contratos + `/parlamentares` e
   `/parlamentares/{id}/gastos`** (`61968f6`): `config/api.yaml` +
   `ApiSettings` (ADR-008 — identificação, host/porta, paginação e
   `ano_minimo_consulta`; nada hardcoded); `api/repo.py` read-only sobre o
   Gold com `GoldIndisponivel` → 503; contratos de resposta
   `api/schemas/parlamentares.py` (`extra="forbid"`) espelhando as colunas
   emitidas pelos modelos dbt (SCD2 `is_current`); endpoints paginados com
   filtros nome/uf/partido e gastos com dimensões resolvidas
   (fornecedor/categoria/`dim_data`), 404/422/503; `api/main.py` usa a config
   e preserva `/` e `/health`. Testes `tests/api/test_parlamentares.py` (16)
   com DuckDB determinístico + TestClient. Suíte completa
   `tests` — **228 passed**.
   **Selo de contrato** (`5f4131f`): `tests/integration/test_api_gold_contrato.
   py` (5) roda o **dbt real do Gold** (via subprocesso, isolando a conexão
   read-write do adaptador — API reabre estritamente `read_only`, ADR-026) e
   trava o contrato pipeline→Gold→API. Apanhou drift real: `dim_data` emite
   `data` (não `data_completa` do `gold.py:DimData`) — corrigido na consulta
   de gastos e no fixture da API. Suíte completa `tests` — **233 passed**
   (212 pipeline + 16 API + 5 integração).

### Onda 2 (implementada)

☑ **Onda 2 — Perfil completo, rede e fornecedores** (`9e3cb43`): 
   `GET /parlamentares/{id}` — perfil vigente do SCD2 (ADR-020) resolvendo
   `sigla_partido`/`sigla_uf`/`situacao_normalizada` emitidas pelo dbt;
   `GET /parlamentares/{id}/rede` — consome **o Gold materializado**
   (`ml_staging.network_nodes/edges` promovidos por `network_nodes.sql`/
   `network_edges.sql`), nunca recalcula PageRank/comunidades por request
   (ADR-030); `GET /fornecedores` (filtros `nome` ILIKE + `tipo_documento`,
   422 para valor inválido); `GET /fornecedores/{cnpj_cpf_valor}` — dimensão
   + agregados sobre `fact_despesa` (`num_despesas`, `valor_liquido_total`);
   `GET /fornecedores/{cnpj_cpf_valor}/parlamentares` — agregado
   parlamentar↔fornecedor (vigentes, `total_gasto` desc). CNPJ exposto claro,
   CPF somente pelo hash HMAC (ADR-011 — buscar por CPF cru retorna 404
   honesto). Schemas `api/schemas/fornecedores.py` + extensão de
   `parlamentares.py` (`extra="forbid"`); repo com decorator `_tratar_erro_gold`
   centralizado; fixture determinística `tests/api/conftest.py` (SPT).
   Testes: `tests/api/test_parlamentares.py` estendido (16→21) +
   `tests/api/test_fornecedores.py` (10) — **31 API**; selo de contrato
   `tests/integration/test_api_gold_contrato.py` estendido (5→10) validando
   perfil (SCD2 → PARTIDO B), fornecedores (CNPJ claro/HMAC), agregados e o
   **bind das colunas de rede** contra o dbt real (200 honesto com staging
   vazio, nunca reanálise). Suíte completa `tests` — **253 passed**
   (212 pipeline + 31 API + 10 integração).

### Onda 3 (implementada)

☑ **Onda 3 — Anomalias, comunidades, qualidade e status** (`50d7ef8`):
   `GET /anomalias?threshold=` — despesas sinalizadas da Gold
   `expense_outliers` (ADR-002/§10); `threshold` é **piso de `zscore`**
   sobre o conjunto já sinalizado (decisão fixada na revisão desta Onda 3 —
   a API não reabre o `-0.1` do Isolation Forest nem os `>= 2` critérios,
   ADR-026/ADR-030), negativo/não-numérico → 422 (mesmo contrato de erro da
   Onda 2). `GET /rede/comunidades` — agrupamento por `comunidade_id` dos
   nós já materializados (`network_nodes`, ADR-030) com nome resolvido das
   dimensões. `GET /qualidade/relatorio` — **ADR-031**: `data_quality_report`
   (Silver, ADR-015) promovida à Gold por model dbt (mecanismo da Opção A do
   ADR-026) para a API continuar read-only sobre o Gold; `regras_violadas`
   desserializada em `list[str]`; filtro `tabela` + paginação.
   `GET /pipeline/status` — controle `pipeline_runs` (ADR-019), mais
   recentes primeiro, observadora passiva do orquestrador. Schemas
   `anomalias.py`/`rede.py`/`qualidade.py`/`pipeline.py` (`extra="forbid"`).
   Testes: 4 arquivos novos em `tests/api` (19 testes — **50 API**); selo de
   contrato estendido (10→14) validando o bind das colunas de
   `expense_outliers`/`network_nodes` (200 honesto com staging vazio) e a
   promoção de `data_quality_report` + `control.pipeline_runs` no dbt real.
   **Achado de implementação corrigido no selo**: `control` é `incremental`
   e a tabela Silver de mesmo nome já existia → o dbt fazia `INSERT INTO`
   (append = duplica + VARCHAR em vez de TIMESTAMP); materializado como
   `table` (full replace) — a Gold passa a emitir `execution_timestamp`
   TIMESTAMP e 1 linha. Suíte completa `tests` — **276 passed**
   (212 pipeline + 50 API + 14 integração).

### Onda 4 (implementada)

☑ **Onda 4 — Endpoints agent-ready (RF-05/ADR-032)**:
   `/agent/parlamentar/{id}` — perfil vigente do SCD2 (ADR-020) + métricas §8
   (`total_gasto`, `gasto_medio`, `num_transacoes`, `num_fornecedores`,
   `valor_maximo`, `valor_mediano`, `percentil_95` — agregação SQL sobre
   `fact_despesa` do Gold) + `hhi_recente`/`hhi_periodo`
   (`supplier_concentration`, grão ano×parlamentar) + `risk_index` e 5 scores
   do período mais recente (`risk_scores`, ADR-027/029) + contagem/proporção
   de anomalias (`expense_outliers`) + top-5 fornecedores por valor;
   `/agent/fornecedor/{cnpj_cpf_valor}` — perfil `dim_fornecedor` + agregados
   (`total_recebido`, `gasto_medio`, `valor_maximo`, `num_transacoes`,
   `num_parlamentares`) + top-5 parlamentares (join `is_current`); CPF só
   HMAC (ADR-011). `/agent/anomalias` — **resumo agregado**, não espelho
   paginado: total, por ano, por critério disparado e top-10 por zscore com
   nome do parlamentar. `/agent/context` — **retrato sistêmico** (CU-07):
   métricas globais do Gold, períodos com dados, resumo do último
   `data_quality_report` e da última execução `pipeline_runs`. **ADR-032**:
   JSON semântico para LLM (Camada Semântica §8 + scores §9/ADR-027/028), na
   mesma fronteira read-only do ADR-026, sem recalcular nada por request
   (ADR-030); `taxa_ausencia`/`indice_alinhamento` fora por inexistência de
   `fact_presenca`/`fact_votacao`. Schemas `api/schemas/agent.py`
   (`extra="forbid"`), 4 funções em `api/repo.py`, router
   `api/routers/agent.py`. Testes: `tests/api/test_agent.py` (8 — **58 API**);
   selo de contrato estendido (14→18) — seed `ml_staging.risk_scores`
   atravessa o model dbt até a Gold, `supplier_concentration` derivada do dbt
   (hhi ≈ 0.5556) e bind das colunas de risco/concentração/fato/dimensão.
   Suíte completa `tests` — **288 passed** (212 pipeline + 58 API + 18
   integração).

### Ondas (pendentes — Sprint 6.5)

> **Dívida técnica aceita no fechamento da Onda 2** (backlog Sprint 6/6.5):
> **paridade automatizada** dbt model → `schema.yml` → Pydantic → API — os
> contratos de resposta e o `gold.py` deveriam ser **gerados a partir do
> schema emitido** pelos modelos dbt (não escritos à mão e divergindo, como em
> `DimParlamentar` → `sigla_partido`/`sigla_uf` e `DimData` → `data`). O selo
> de contrato `tests/integration/test_api_gold_contrato.py` já é a barreira
> detecta-falsos; a dívida é apenas a automação da paridade em si.

---

## Sprint 6.5 — Validação End-to-End

> **Resíduo registrado no fechamento da Sprint 4/Trilha B** (não bloqueante):
> o encadeamento `executar_bronze >> executar_silver` foi confirmado por
> **leitura de código**, não por import-test do DAG — Airflow não está
> instalado no ambiente de desenvolvimento. É a mesma classe de lacuna de
> "parece certo no código, mas nunca foi exercitado" que originou o ADR-023.

☑ **`test_dag.py`** — import-test do DAG com Airflow `DagBag` (sem subir o
   scheduler): valida parsing do módulo `pipeline/dags/pipeline_dag.py`, a
   estrutura de dependências de todas as tasks (ordem passada Bronze→Silver→
   Gold) e a integridade XCom (`executar_silver` consome o `run_id` da
   upstream). Importado via `pytest.importorskip("airflow")` — o extra
   `pipeline` é optional-dependency; em dev local sem Airflow o teste é
   pulado e em CI/containers com o extra instalado vira barreira real.

☑ **Manutenção estrutural — realocação dos módulos analíticos** (padrão §6):
   `analytics.py`/`risk.py` → `analytics/parliamentarians/`, `anomalies.py` →
   `analytics/anomalies/`, `network.py` → `analytics/network/`, `features.py`
   → `analytics/features.py` (git mv, histórico preservado). Imports internos,
   docstrings e comentários ativos sincronizados; referência obsoleta a
   `pipeline/pipeline.py` removida da árvore §6. Suíte 306 testes verdes após
   a realocação (230 pipeline + 58 API + 18 integração).

☑ **Corretivos do prompt de QA (Sprint 6.5)**:
   - **BUG-001** — incremental da Bronze avançava para período inexistente;
     agora extrai o período seguinte apenas quando já existe, senão reextrai o
     corrente (`_proximo_mes_competencia`/`_proximo_ano_competencia` +
     `run_pipeline(execution_timestamp=...)`). 3 testes de regressão.
   - **BUG-003** — Silver idempotente por chave de negócio: `escrever_validos_
     duckdb` virou UPSERT (DELETE+INSERT na chave). 2 testes de regressão.
   - **BUG-005** — `fontes_com_erro` tipada `list[str]` na API e
     `cast(null as varchar[])` no ramo vazio de `pipeline_runs.sql`.
   - **BUG-006** — `limite` de `/pipeline/status` confirmado dentro do teto
     (`le=config.limite_maximo`), coberto por teste.

☑ **ADR-033 — Pseudonimização de CPF movida para a Silver** (transform onde o
   hash é aplicado; Gold repassa sem UDF). Plugin `hmac_udf.py` removido do
   `profiles.yml`; `pipeline/pseudonymize.py` é a fonte única; seeds dos
   testes Gold carregam o hash (asserções de dimensão preservadas).

☑ **BUG-004 — migração de schema legado na Silver** (corretivo QA): tabelas
   criadas por versões anteriores (menos colunas) são migradas via `ALTER
   TABLE ADD COLUMN` antes do INSERT por nome (`_criar_tabela_se_necessario` +
   `_insert_por_nome` em `pipeline/silver.py`), com teste de contrato
   `test_migracao_de_schema_em_tabela_legada`.

☑ **Validação E2E real (`scripts/run_e2e_local.py`, Bronze→Silver→Gold com
   APIs reais em modo validação)** — corretivos adicionais encontrados
   exercitando a cadeia ponta-a-ponta com dados das quatro fontes:

   - **BUG-007 — inferência de tipo da coluna de texto toda nula**: a
     Câmara grava `nome_parlamentar` 100% nulo e o DuckDB inferia
     `INTEGER` ao criar `silver_despesa` (primeira carga); o Senado (nomes
     reais) derrubava o INSERT com `ConversionException`. `_criar_tabela_
     se_necessario` agora normaliza colunas `object` para `string` antes da
     inferência (VARCHAR). Regressão `test_coluna_de_texto_toda_nula_nao_
     vira_integer_no_schema`.
   - **BUG-008 — cartões CGU anteriores a 2015**: o parser e o gate Pandera
     de `silver_cartao` rejeitavam transações de 2012-2013 (início real dos
     cartões CPGF, `mes_inicio "01/2013"`), mandando a fonte inteira para
     quarentena. Limites de sanidade ajustados para 2012 (`normalize.py`) e
     gate do cartão com `nao_anterior_a(2012)`. Regressões
     `test_ano_inicial_cgu_2012_aceito` e `test_transacao_de_2012_aceita_
     inicio_real_cgu`. Ainda assim, o horizonte `dim_data` do Gold é
     2015-2035 (espelho do início da Câmara) — transações de cartão
     pré-2015 vão para `fact_cartao_cpgf_quarantine` (`data_nao_resolvida`),
     limitação conhecida aceita.
   - **BUG-009 — `ml_staging` ausente no build Gold completo**: os models
     analytics leem `ml_staging` (escrita exclusiva dos scripts de ML,
     ADR-026); o runner E2E agora cria o schema VAZIO antes do `dbt build`
     (mesmo contrato do teste de contrato), habilitando os 224 nodes.
   - **BUG-010 — `pipeline_runs` Gold vazio/consolidação de tipos mistos**:
     o glob `bronze_pipeline_runs_dir` era relativo ao arquivo do DuckDB,
     mas o DuckDB resolve caminhos relativos ao cwd → 0 arquivos. Ajustado
     para relativo ao repo root, e o `read_parquet` do `pipeline_runs.sql`
     passou a usar `union_by_name = true` + `cast(... as varchar[])` para
     consolidar arquivos legados com `fontes_com_erro` `INTEGER[]`
     (lista vazia) e atuais `VARCHAR[]`. Regressões em
     `tests/pipeline/test_gold_pipeline_runs.py`.
   - **BUG-011 — runner E2E**: faltavam `import json`/`import sys` no
     subprocesso do `dbt build` (NomeError); caractere `→` no `print` do
     `--reset` quebrava com cp1252 em stdout redirecionado. Corrigidos em
     `scripts/run_e2e_local.py`.
   - **Resultado**: Bronze `success` (4 fontes), Silver com despesa Câmara
     9.350 + Senado 63.874, parlamentar 514+162, cartão ~120k, emenda
     45.799; Gold `dbt build` **PASS=224 ERROR=0**; `pipeline_runs` 12
     linhas no DuckDB dev.

☑ **Dívida consciente (registrada no fechamento do QA, BUG-002) —
   criptografia em repouso do MinIO NÃO implementada.** Registrada como
   item fechado de registro (não como trabalho pendente): a camada Bronze
   cumpre a condição de acesso restrito (MinIO exposto apenas em
   `127.0.0.1:9000/9001`, rede interna `observatorio-net`,
   `no-new-privileges`), mas o volume `minio_data` não tem criptografia em
   repouso (server-side do MinIO ou disco cifrado). Mitigação atual: acesso
   restrito + pseudonimização na Silver (ADR-033). Endurecimento futuro:
   habilitar criptografia server-side (SSE-S3/KMS) ou cifrar o disco/volume,
   e atualizar ADR-033 quando implementado.

☑ **Segurança — secrets externalizados (CWE-798) e pendência de rotação.**
   O commit `b03170a` (Sprint 6.5) removeu os secrets hardcoded do
   `docker-compose.yml` (Fernet key, senhas admin/postgres → variáveis de
   ambiente com `:?Defina ...` no `.env`), incluindo a postura "fail-fast"
   que impede o stack de subir sem as credenciais. **Análise do histórico
   (varredura dos 872 blobs, Sprint 6.5):** o ÚNICO secret versionado foi
   uma Fernet key curta no `docker-compose.yml` (13 chars, inválida como
   Fernet — o Airflow não iniciaria com ela); **nenhuma** senha real, chave
   CGU ou `CPF_HMAC_SECRET_KEY` esteve em commits. **Decisão: não reescrever
   o histórico** (a Fernet key não tem valor de exploração; force-push
   reescreveria todos os SHAs e quebraria clones/CI sem benefício
   proporcional). Mitigações aplicadas:
   1) **Secret scanner no CI** — Gitleaks adicionado ao
      `.github/workflows/pipeline.yml` (job `secret-scan`, dispara em
      `workflow_dispatch` + `pull_request`) com `.gitleaks.toml` próprio
      (regra extra para Fernet key + campos de secret do projeto) — impede
      regressão da CWE-798;
   2) **Rotação recomendada no ambiente local** — a Fernet key antiga que
      esteve no histórico deve ser substituída por uma nova gerada com
      `Fernet.generate_key()` no `.env` (qualquer valor que já esteve em
      repositório público trata-se como comprometido). Mesma regra para
      `CGU_API_KEY`/`CPF_HMAC_SECRET_KEY` se alguma cópia do `.env` com
      valores reais tiver sido compartilhada.

*Este documento é atualizado ao final de cada sprint pelo papel de Documentador.*
*Versão atual: 1.6 — **Sprint 6.5 — DONE / QA APPROVED** — Validação End-to-End: manutenção estrutural completa (módulos analíticos em `analytics/` §6), corretivos do prompt de QA BUG-001/003/004/005/006 com regressões, ADR-033 (pseudonimização na Silver), import-test do DAG (`tests/pipeline/test_dag.py`, Airflow via optional-dependency), dívida de criptografia MinIO registrada (BUG-002), secrets externalizados (CWE-798) com **varredura do histórico (872 blobs: nenhum secret real, teste de controle 3/3) e decisão de não reescrever**, Gitleaks no CI (`.gitleaks.toml` + job `secret-scan`) — **308 testes verdes** (232 pipeline + 58 API + 18 integração). **Validação E2E real concluída** (Bronze→Silver→Gold com APIs reais em modo validação): corretivos BUG-007/008/009/010/011 + regressões, Gold `PASS=224 ERROR=0`, `pipeline_runs` 12 linhas no dev; **316 testes verdes** (240 pipeline + 58 API + 18 integração + 1 skip Airflow). **Alinhamento documental da pseudonimização (BUG-DOC-001):** README, PROJECT_CONTEXT (RF-06/RNF) e ADR-004 agora refletem ADR-033 — Bronze mantém CPF bruto equivalente-público, Silver é a fronteira do hash. Dívida técnica de paridade dbt→Pydantic→API registrada (próxima sprint). Sprint 6 fechada (288). ADRs 001-033. Recomendação pós-fechamento: proteção da branch `develop` exigindo `secret-scan` como check obrigatório (Sprint 9).*

*Manutenção estrutural Sprint 6.5: módulos analíticos realocados de `pipeline/` para `analytics/` conforme §6 (git mv); referência obsoleta a `pipeline/pipeline.py` removida da árvore §6; 306 testes verdes após a realocação (230 pipeline + 58 API + 18 integração). Corretivos QA e ADR-033; **308 testes verdes** ao final (232 pipeline + 58 API + 18 integração).*

---

## Sprint 7 — Dashboard (Streamlit) — FECHADA

☑ **`dashboard/client.py`** — cliente HTTP da API REST (RF-05, ADR-026):
   um método por endpoint, com `ApiError` (erro de negócio com `detail`) e
   `ApiIndisponivel` (rede offline → página mostra estado amigável). Base URL
   de `API_URL` (config/dashboard.yaml, ADR-008; docker-compose injeta
   `http://api:8000`; dev `http://localhost:8000`; nginx expõe `/api/`).

☑ **`dashboard/ui.py`** — componentes reutilizáveis: `formatar_moeda` pt-BR,
   `carregar_com_feedback` (spinner + erro amigável), `estado_api`,
   `metricas_seguras`, `tabela_exportavel` (CSV/Excel/PDF, RF-08).

☑ **Config (ADR-008)** — `config/dashboard.yaml` + `DashboardSettings` em
   `pipeline/config.py`: título, `url_env_var`/`url_padrao`, timeout,
   `exportacao_formatos`. Loader cacheado `load_dashboard_settings`/`get_dashboard`.

☑ **Página 01 — Visão Geral** (`dashboard/app.py`): KPIs globais (total
   gasto, transações, fornecedores, parlamentares, anomalias) via
   `/agent/context`; períodos com dados; status dos serviços; execuções
   recentes (`/pipeline/status`).

☑ **Página 02 — Parlamentar**: busca por nome/UF/partido, perfil SCD2 e
   despesas com filtro por ano e exportação.

☑ **Página 03 — Partido** e **Página 04 — Estado**: agregação por partido/UF
   com total gasto por parlamentar.

☑ **Página 05 — Fornecedor**: perfil + top parlamentares; CNPJ claro, CPF
   pseudonimizado (ADR-011/033).

☑ **Página 06 — Rede**: grafo parlamentar-fornecedor (NetworkX + matplotlib)
   e comunidades (ADR-030) com exportação PNG/CSV.

☑ **Página 07 — Anomalias**: agregados por ano/critério (`/agent/anomalias`)
   + lista com threshold de z-score (`/anomalias`, ADR-002).

☑ **Página 08 — ML/Risco**: scores de risco em radar (ADR-029), risk index e
   top fornecedores via `/agent/parlamentar/{id}` (ADR-032).

☑ **Página 09 — Qualidade**: Data Quality Report do Gold (`/qualidade/
   relatorio`, ADR-033) com resumo por tabela.

☑ **Página 10 — Metadados**: catálogo de fontes e execuções do pipeline
   (`/pipeline/status`, RF-12).

☑ **UX**: erro amigável quando a API está offline (`carregar_com_feedback` +
   `st.stop`), spinners de carregamento, navegação consistente por abas/barra
   lateral.

☑ **`tests/dashboard/`** — 20 testes: client (montagem de rotas/params,
   `ApiError`/`ApiIndisponivel`, base URL via env) + UI (`formatar_moeda`,
   `tabela_exportavel` com dados/vazio).

☑ **`pyproject.toml`** — extra `dashboard` (`openpyxl`/`matplotlib`);
   `[tool.setuptools.packages.find]` declarado para resolver o flat-layout.

### Resultado Sprint 7
Dashboard validado com `AppTest` contra o DuckDB dev (dados reais do E2E):
KPIs com total gasto R$ 4,5M / 8.983 transações / 4.319 fornecedores /
432 parlamentares; perfil e risco de parlamentar real (204379);
DQ report e execuções renderizando. Suíte completa **336 passed, 1 skipped**
(20 novos + 316 anteriores). *Roadmap §13 atualizado (Sprint 7 em andamento).*

### Auditoria técnica (gates de revisão) — Sprint 7
☑ **Gate 1 — HTTP client robusto** (`dashboard/client.py`): JSON inválido em
   2xx vira `ApiError` (não escapa `JSONDecodeError`); retry limitado p/
   transitórios (5xx/rede, GET idempotente), 4xx nunca retried; limite de
   tamanho de resposta (`resposta_max_bytes`); mensagens sem URL interna.
☑ **Gate 2 — Exportações limitadas** (`dashboard/ui.py`): Excel/PDF com teto
   `exportacao_max_linhas` + aviso de truncamento; CSV completo (RF-08).
☑ **Gate 3 — Rede com teto**: página 06 limita arestas/nós renderizados; API
   `/rede/comunidades` ganhou `limite_nos` (default 200, teto 1000, enforced
   no SQL via `row_number()` por comunidade/período por pagerank desc).
☑ **Gate 4 — CNPJ URL-encoded** (`_codificar_path`): `/` de máscara não
   quebra rota; regressão de CNPJ mascarado.
☑ **Gate 5 — E2E HTTP real**: `tests/dashboard/test_integracao_api.py` sobe
   uvicorn sobre Gold semeado e conecta o `ApiClient` por socket TCP — sem
   mock de resposta. 8 cenários.
🟠 **Dívida registrada — autenticação/TLS pendentes (ADR-007).** O dashboard
   amplia a superfície da API (agora consumível publicamente via nginx).
   Antes de expor fora de rede confiável/VPN, exigir: TLS (terminação no
   reverso) e autenticação se a API servir dado individual. Não bloqueia o
   fechamento funcional; permanece como item explícito de deploy (Sprint 9).

*Versão atual: 2.2 — **Sprint 7 — DONE / QA APPROVED** — Dashboard Streamlit: cliente da API (RF-05), 10 páginas (visão geral, parlamentar, partido, estado, fornecedor, rede, anomalias, ML/risco, qualidade, metadados), exportações CSV/Excel/PDF (RF-08), UX com erro amigável; config ADR-008 (`config/dashboard.yaml`) e extra `dashboard`. **Auditoria técnica concluída (Gates 1-5):** client HTTP robusto (retry/limites/erros amigáveis), exportações com teto, rede limitada na API (`limite_nos`), CNPJ URL-encoded, E2E HTTP real sem mock — **349 testes verdes** (1 skip Airflow). Dívida técnica registrada e não bloqueante: autenticação/TLS pendentes (ADR-007, Sprint 9). Commit de fechamento: `bdf1cb3`. Sprint 6.5 fechada (QA approved). Sprint 7 fechada (349). ADRs 001-033.*

---

## Sprint 8 — Testes e Qualidade — FECHADA

**Objetivo:** elevar a confiança dos módulos de maior risco, preservar a
cobertura global em pelo menos 80% e transformar cobertura/lint em gates locais
reprodutíveis. Baseline de abertura: **349 passed, 1 skipped (Airflow)** e
**88%** de cobertura global.

### Prioridade 1 — contratos Gold e persistência Bronze

- ☑ **Contratos de `pipeline/gold.py`** — testes unitários de validação e
  rejeição dos contratos Pydantic da camada Gold (tipos, campos obrigatórios,
  regras de nulidade e valores inválidos). O dbt continua validado pelos testes
  de integração já existentes em `tests/pipeline/test_gold_*.py`; este item não
  introduz um segundo orquestrador dbt.
- ☑ **`pipeline/storage.py`** — cobertura dos dois backends e dos ramos de
  persistência: diretório vazio, projeção de colunas, deduplicação mensal/anual,
  chave nula, arquivo de controle e serialização MinIO com cliente fake.

### Prioridade 2 — gate de qualidade

- ☑ **Ruff** — adicionado ao extra `dev`, configurado com o conjunto inicial
  de erros de execução (`E4`, `E7`, `E9`, `F`) e validado por `python -m ruff
  check .`. A migração de regras estritas de estilo/import ordering fica
  **deferida como item de backlog** (Sprint 9 ou migração própria) — ver
  "Dívida registrada na Sprint 8".
- ☑ **Coverage** — declarado `fail_under = 80` e incluído `dashboard` no source
  monitorado, sem mascarar módulos por exclusões novas; ajustar somente após a
  suíte permanecer acima do limiar.

### Prioridade 3 — lacunas remanescentes

- ☑ Elevar a cobertura de `watermark.py`, `pseudonymize.py`,
  `senado/transform.py` e routers de parlamentares/fornecedores: stores JSON/
  Airflow fake e namespace, falhas fail-fast do HMAC, carga Senado vazia e
  delegação Silver, e degradação Gold→503 em todas as rotas individuais.
- ☑ Critérios de anomalia — `analytics/anomalies/anomalies.py` confirmado em
  **100%** na reexecução limpa do gate de fechamento. O 87% registrado era
  artefato de medição: um `.coverage` acumulado de execuções anteriores excluía
  os testes de fronteira/persistência que já existiam
  (`test_fornecedor_coluna_ausente_ou_lote_vazio_nao_acusa`,
  `test_empresa_nova_com_base_vazia_nao_acusa`,
  `test_valores_identicos_com_dimensao_vazia_nao_acusa`,
  `test_avaliar_criterios_vazio_preserva_schema`,
  `test_avaliar_criterios_degrada_sem_dimensao_ou_fornecedor`,
  `test_escrita_outliers_vazia_nao_abre_duckdb`). Nenhum teste novo necessário.

### Resultado da terceira entrega (gate consolidado de fechamento)

Suíte completa reexecutada com `.coverage` limpo: **374 passed, 1 skipped
(Airflow)** e cobertura global de **93,58%**. Módulos em 100%:
`gold.py`, `watermark.py`, `pseudonymize.py`, `senado/transform.py`, routers
de parlamentares/fornecedores, `anomalies.py`. `storage.py` em 99% (1 ramo
parcial) e `dashboard` em 100% (`app.py`)/90%/62% (`ui.py`).

### Critérios de aceite

- ☑ Suíte completa verde: **374 passed, 1 skipped** (Airflow opcional), em
  18min31s (medição limpa, 33min52s na primeira execução).
- ☑ Cobertura total de **93,58%** (limiar >= 80%) com relatório por módulo.
- ☑ `python -m ruff check .` verde e `pytest --cov` falha abaixo do limiar
  configurado.
- ☑ Contratos de dados Gold e comportamento de storage exercitados sem MinIO
  real ou rede externa.

### Itens aceitos e deferidos (registro explícito de fechamento)

- 🟠 **Ruff estrito (import ordering/estilo)** — conjunto `E4/E7/E9/F`
  aplicado; regras de estilo/`I` (import ordering) **deferidas** para migração
  própria (Sprint 9 ou posterior), com porta de entrada controlada — não é uma
  reformatação massiva acoplada ao fechamento.
- 🟢 **`pipeline/storage.py` em 99%** (1 ramo parcial `188->190`) — **aceito**
  como está; acima do limiar global, sem exigência de 100%.
- 🟢 **`dashboard/ui.py` em 62%** — **aceito** (acima do limiar global de 80%);
  cobertura dos utilitários de exportação (tabela_exportavel/estado_api)
  registrada como dívida futura.
- 🟢 **`dashboard/app.py` em 0%** — entrypoint Streamlit (`if __name__ ==
  "__main__"`), não importado por testes; característica normal de entrypoint.
- ✅ Nenhum ADR novo necessário — sem decisão arquitetural, apenas qualidade
  e teste; ADRs vigentes 001-033.

### Fechamento da Sprint 8

**Sprint 8 — DONE / QA APPROVED.** Testes e qualidade: contratos Gold (100%),
persistência Parquet (99%), watermark/pseudonimização/Senado/routers/anomalias
(100%), gates locais de Ruff (extra `dev`) e coverage (`fail_under = 80` com
`dashboard` no source). **374 testes verdes, 1 skip Airflow, 93,58% de
cobertura global** em medição limpa (0:18:31). Commit de fechamento:
`fdad9c0`. ADRs 001-033.

*Versão atual: 2.3 — **Sprint 8 — DONE / QA APPROVED** — Testes e qualidade:
contratos Gold (100%), storage Parquet (99%), watermark/pseudonimização/
transformação Senado/routers de parlamentares e fornecedores/anomalias (100%),
gates locais de Ruff (`E4/E7/E9/F`) e coverage (`fail_under = 80`, `dashboard`
no source) — **374 testes verdes, 1 skip (Airflow), 93,58% de cobertura global**
(medição limpa, 0:18:31). Aceitos: storage 99% e dashboard/ui.py 62% (acima do
limiar). Deferido: Ruff estrito/import ordering (Sprint 9). Sem ADR novo.
Commit de fechamento: `fdad9c0`. Sprint 7 fechada (349). Sprint 6.5 fechada
(QA approved). ADRs 001-033.*

---

## Sprint 9 — Deploy + Documentação — FECHADA

**Objetivo:** ativar CI real (testes/lint/secret scan em todo PR), executar o
pipeline diariamente em produção (ADR-034), completar README e guias de
instalação/deploy/operação, e fechar dívidas registradas.

### Gate 1 — CI real (substitui o placeholder)

- ☑ Renomear `.github/workflows/pipeline.yml` → `ci.yml` (escopo real é CI,
  não execução de pipeline de dados — ADR-034).
- ☑ Job de testes: `pytest --cov` (gate `fail_under = 80` ativo) em
  ubuntu-latest, com instalação dos extras `api,pipeline,dashboard,
  analytics,dev`. Nota: no CI o Airflow existe → `test_dag.py` roda como
  barreira real (5 testes), total esperado **379 passed, 0 skipped**.
- ☑ Job de lint: `python -m ruff check .`.
- ☐ Gitleaks como *required status check* na branch protection de `develop`
  (configuração no GitHub Settings; documentada, sem artefato de código).
  **Nota:** requer ajuste manual de branch protection (Gates em Settings).
  ☑ **Concluído (27/08/2026):** Gitleaks, Ruff e pytest configurados como
  required status checks em `develop` e `main` via GitHub API.

### Gate 3 — Deploy automático (27/08/2026)

- ☑ **Workflow `deploy.yml`** criado e testado: dispara em `push` para `main`,
  roda em self-hosted runner na VPS, executa pull + build + restart containers.
- ☑ **Self-hosted runner** (`github-runner.service`): agente GitHub Actions
  rodando como serviço systemd, usuário `opc`, labels `self-hosted,linux,arm64`.
- ☑ **Branch protection** configurada em `develop` e `main`: status checks
  obrigatórios, review obrigatório, dismiss stale reviews.
- ☑ **ADR-037** documenta a decisão, riscos e mitigações.
- ☑ **Remoção de `observatorio-parlamentar.old`** após validação.

### Gate 2 — Execução diária (ADR-034, Opção B)

- ☑ `scripts/run_pipeline_daily.sh` — sobe perfil `pipeline` (só
  postgres+scheduler), healthcheck `list-import-errors`, unpause explícito,
  trigger com `run_id` determinístico, polling via `list-runs --output json`
  (compatível com Airflow 2.9, que exige `execution_date` no `dags state`),
  `down` garantido no trap EXIT; timeouts via env vars.
- ☑ Units `systemd` (`observatorio-pipeline.timer`/`.service`) em `infra/`
  (oneshot, 03:00 America/Sao_Paulo, `Persistent=true`).
- ☑ Provisionamento: `usermod -aG docker ubuntu` no `cloud-config.yaml`
  (posteriormente migrado para Oracle Linux/`opc`/firewalld — ver nota de
  migração abaixo); instalação/atualização das units no `deploy.sh`.
- ☑ **Bugfix latente:** `pipeline_dag.py::_executar_gold` usava
  `json.dumps`/`sys.path` no subprocesso do dbt sem importá-los
  (`NameError` em produção) — `import json`/`import sys` adicionados.
- ☑ **Bugfix de duplicação de agendamento:** `schedule="@daily"` no DAG
  competia com o timer `systemd`, causando execuções concorrentes na
  primeira tentativa de backfill em produção. Corrigido para
  `schedule=None` — agendamento exclusivamente externo (mesclado em
  `61c4c66`, PR #6). `test_dag.py` atualizado.
- ☑ **Bugfix `pipeline_runs` vazio (ADR-019 em produção):** a Bronze grava
  o controle `pipeline_runs` no MinIO (storage MinIO, ADR-007), mas o dbt
  Gold lia o glob local `data/bronze/...` → 0 arquivos, "pipeline_runs
  zero-linhas". Corrigido: `profiles.yml` ganhou extensão `httpfs` + secret
  S3 path-style (endpoint SEM scheme — DuckDB 1.0.0 gerava URL quebrada com
  `http://`); `get_dbt_vars()` injeta `bronze_pipeline_runs_dir=s3://<bucket>/...`
  quando `MINIO_ENDPOINT` configurado. Validado no HML (4 execuções) e PRD.
- ☑ **Robustez do Gold sem dados CGU:** `_garantir_silver_cgu_vazio` cria
  `silver_cartao`/`silver_emenda` vazias (schema declarativo de
  `schemas_silver.py`) quando a CGU não retorna dados no período — o dbt
  build completo falhava com "table does not exist" (mesmo padrão do
  `_garantir_ml_staging_vazio`, ADR-026).
- ☑ **Ambiente HML portado:** `docker-compose.hml.yml`, `config.hml/`,
  `.env.hml.example` e `scripts/run_hml_e2e.sh` (branch `hml` órfã →
  `develop`), com isolamento corrigido (`*_ENV_FILE` apontando para
  `.env.hml`).
- ☑ **Fix de deploy:** `chmod +x scripts/run_pipeline_daily.sh` no passo 4/6
  do `deploy.sh` (unit invoca sem prefixo `bash`; sem +x → 203/EXEC).
- ☑ **SELinux (Oracle Linux):** o systemd falhava ao executar o script com
  `status=203/EXEC Permission denied` mesmo com o bit +x — contexto
  `user_home_t` bloqueava. Corrigido com `chcon -t bin_t` no script.
  **Nota operacional:** reaplicar após re-sincronização do arquivo na VPS.
- ☑ **Permissões de dados:** `chmod -R a+rwx data/` — o container airflow
  (uid 50000) precisa escrever no DuckDB da Gold (dono `opc`, uid 1000).
- ☑ **Validação real de execução completa na VPS — CONCLUÍDA (25/08).**
  Critério de aceite atendido: timer `enabled`/`active (waiting)` (próximo
  disparo 03:00 America/Sao_Paulo) e execução via systemd com **SUCCESS**
  (run_id `4e52260e`, 1676s, log do `journalctl`). `pipeline_runs`
  populado: `GET /api/pipeline/status` → `{"total":3}` com a linha nova no
  topo (`4e52260e`, status `success`); `GET /api/agent/context` →
  `pipeline.run_id = 4e52260e` (antes `null`), dados novos na Gold
  (`total_gasto` 608.742.032 → 608.821.853, `num_transacoes` 490.602 →
  490.800, `total_registros` 3.649.994 → 3.650.273). Observação: durante o
  `dbt build` (leitor read_only + single-writer), `/api/pipeline/status`
  pode retornar `total:0` momentaneamente — não é inconsistência
  permanente, é timing do build.

### Gate 3 — Ruff estrito (dívida deferida na Sprint 8)

- ☑ Migração controlada: habilitados `I` (import ordering), `W292`
  (newline EOF), `UP017/UP035/UP037` (modernizações mecânicas seguras);
  auto-fix aplicado (113 correções). Deferidos para porta própria: `E501`
  (line-too-long — exigiria reformatação massiva) e `B904/B905`
  (semânticas, revisão manual).
- ☑ Validado (auditoria direta, `61c4c66`): `ruff check .` verde; suíte
  completa **374 passed, 93,53% cobertura** (medição limpa, `.coverage`
  removido antes da execução — substitui a leitura anterior de 93,59%/87%,
  ambas afetadas por cache de cobertura entre execuções).

### Gate 4 — Documentação

- ☑ `README.md` §II.6 (observabilidade detalhada — structlog, run_id,
  DQ report, pipeline_runs, alertas deferidos) e §III (explicação do case
  com números reais da validação E2E e dashboard).
- ☑ Guias de instalação, deploy e operação: `docs/guia_deploy_operacao.md`
  (Docker Compose, deploy VPS, execução diária ADR-034, operação) — somado
  ao `docs/guia_provisionamento_oci.md` já existente.
- ☑ Revisão do `docker-compose.yml`: healthcheck no `postgres` +
  `depends_on` condicional em webserver/scheduler. `.env.example` já
  documenta credenciais obrigatórias.

### Gate 5 — TLS (autenticação/TLS — dívida da Sprint 7, ADR-007)

- ☑ Nginx com HTTPS via Let's Encrypt/certbot. Domínio próprio
  (`observatorio-parlamentar.com.br`, Registro.br) com zona DNS própria
  (NS `e.sec.dns.br`/`f.sec.dns.br`), registro A raiz + `www` → VPS Oracle.
  Certificado emitido (CN=`observatorio-parlamentar.com.br`, SAN `www`,
  expira 18/11/2026), renovação automática via container `certbot`
  (`certbot renew` a cada 12h). Config Nginx com entrada seletiva
  (bootstrap :80/ACME vs. SSL :443) evita crash-loop sem certificado.
  **Verificado por auditoria externa direta** (fetch a
  `https://observatorio-parlamentar.com.br/` — HTTPS válido, sem redirect
  para HTTP, App Streamlit servido corretamente).

### Acompanhamento pós-fechamento (não bloqueante)

- ☑ **UX fix em produção — busca por ID cru em `08_ml.py`/`06_rede.py`:**
  reportado como bug (usuário precisava saber o `id_parlamentar` de cor;
  qualquer ID incorreto retornava "Parlamentar N não encontrado" sem
  caminho de descoberta). Ambas páginas substituídas pelo mesmo
  fluxo de busca por nome/UF/partido + `st.selectbox` já usado em
  `02_parlamentar.py`/`05_fornecedor.py` — sem endpoint novo
  (`client.listar_parlamentares` reaproveitado). Varredura confirmou que
  nenhuma outra página do dashboard usa `number_input` para ID.

- ☑ **Bugfix em produção — `KeyError: None` em `05_fornecedor.py`:**
  seletor de fornecedor (`st.selectbox(key="forn_sel")`) quebrava no
  primeiro render após uma busca, pois o reset
  `st.session_state["forn_sel"] = None` (padrão já usado com segurança em
  `02_parlamentar.py`) não tinha a guarda `if sel is None: return None`
  correspondente. Corrigido replicando a guarda de `02_parlamentar.py`.
  `03_partido.py`/`04_estado.py` auditados e não afetados (não usam esse
  padrão de reset). Ruff limpo.
- ☐ **Cobertura de regressão para páginas Streamlit:** o projeto não usa
  `streamlit.testing.AppTest` — `tests/dashboard/` cobre apenas
  `client.py`/`ui.py`. Três problemas de UX/bug consecutivos em produção
  (`02_parlamentar.py`/Decimal, `05_fornecedor.py`/seletor,
  `08_ml.py`+`06_rede.py`/busca por ID) só foram pegos por uso manual.
  Avaliar introduzir `AppTest` ao menos para o fluxo busca→seleção, hoje
  replicado em 4 páginas (02, 05, 06, 08) sem teste automatizado.
- ☑ **Documentação retroativa — CRLF/`.gitattributes` (commit
  `1b54475`):** fix já em produção (rebuild do nginx crashava com `exit
  127` por CRLF em `nginx/entrypoint.sh` originado de checkout Windows);
  faltava o registro em CHANGELOG.md referenciado pelo próprio
  `.gitattributes`. Adicionado retroativamente.
- ☑ **Bugfix em produção — Decimal serializado como string JSON:**
  `GastoItem.valor_liquido`/`valor_glosa` (`api/schemas/parlamentares.py`),
  `AnomaliaItem.valor_liquido` (`api/schemas/anomalias.py`) e
  `PerfilFornecedor.valor_liquido_total`/`ParlamentarFornecedor.total_gasto`
  (`api/schemas/fornecedores.py`) eram tipados como `Decimal` puro — o
  Pydantic v2 serializa `Decimal` para JSON como *string*
  (`"150.30"`, não `150.3`), contradizendo a intenção já documentada no
  docstring original do módulo. Reportado em produção via
  `dashboard/pages/02_parlamentar.py` (`ValueError: Unknown format code
  'f' for object of type 'str'` em `formatar_moeda`); auditoria confirmou
  que `05_fornecedor.py` e `07_anomalias.py` tinham o mesmo bug latente
  (só não reportado ainda) — `03_partido.py`/`04_estado.py` escaparam por
  já aplicarem `float(...)` defensivamente. Corrigido na raiz (API, não no
  dashboard): novo tipo `Moeda` em `api/schemas/_common.py`
  (`Annotated[Decimal, PlainSerializer(..., when_used="json")]`),
  aplicado nos 4 campos monetários acima — `Decimal` continua sendo o tipo
  interno (precisão preservada), mas o encoder JSON da API agora emite
  número. Validado contra os schemas reais (`model_dump_json()`) e suíte
  `tests/api/`/`tests/unit/` (63 passed, sem regressão). Não requereu novo
  ADR — corrige comportamento para bater com a intenção já registrada,
  não reabre nenhuma decisão arquitetural.
- ☐ **Higiene operacional:** ambiente HML derrubado em 25/08 (containers,
  rede e volumes `hml_*` removidos) para liberar recursos da VPS e eliminar
  ambiguidade de observação. HML nunca deve ficar residente por design
  (mesmo princípio do Gate 5); o `scripts/run_hml_e2e.sh` sobe/derruba sob
  demanda.
- ☐ **Observação de `/api/pipeline/status`:** durante o `dbt build`
  (single-writer do DuckDB + leitura `read_only` da API), o endpoint pode
  retornar `total:0` momentaneamente. Verificado por 4 camadas independentes
  (DuckDB ground truth, API interna, URL pública via nginx/TLS, fetch
  externo) — sempre converge para `total:3` após o build. Não é bug; se
  virar queixa de consumidor, considerar retry/read replica.

*Versão atual: 2.7 — **Sprint 9 FECHADA (DONE/QA APPROVED).** ADR-034 aceito.
Auditoria direta em `61c4c66` + fixes até `9ad47c2` confirma: **Gates 1–5
concluídos e comprovados** com evidência externa (CI real, Ruff estrito
93,53%/374 passed, README/guias completos, TLS ao vivo, execução diária via
systemd com SUCCESS em produção). **Gate 2 fechado em 25/08:** timer
`enabled`/`active (waiting)`, execução via systemd `SUCCESS` (run_id
`4e52260e`), `pipeline_runs` populado via MinIO/S3 (`GET /api/pipeline/status`
→ total 3; `GET /api/agent/context` → pipeline.run_id preenchido). Causas
raiz resolvidas: SELinux (`chcon -t bin_t`), permissões de dados (`chmod -R
a+rwx data/`), fix S3 (httpfs), robustez CGU vazia, ambiente HML portado.
ADRs 001-034.*

---

## Pós-Sprint 9 - Hardening de Segurança (25/08/2026)

Auditoria de segurança externa (nginx, Docker/compose, API, pseudonimização,
CI e histórico git via gitleaks — 123 commits, 0 vazamentos). Correções na
branch `fix/security-hardening`; rotação de segredos executada na VPS de HML
ANTES do código (console MinIO estava pública → credenciais tratadas como
comprometidas).

- ☑ **Rotação de segredos em HML:** MINIO_ROOT_PASSWORD, POSTGRES_PASSWORD,
  AIRFLOW_ADMIN_PASSWORD (43 chars urlsafe CSPRNG) e AIRFLOW_FERNET_KEY
  (validada com `cryptography`) — gerados na própria VPS, nunca impressos.
  E2E verde pós-rotação (backfill + incremental SUCCESS). CPF_HMAC_SECRET_KEY
  intocado (exige reprocesso da Silver); CGU_API_KEY é rotação externa.
- ☑ **Console MinIO fora do proxy público** (`nginx/default.conf`,
  `nginx/bootstrap.conf`) — bind 127.0.0.1 + SSH tunnel apenas.
- ☑ **Rate limit e headers no nginx:** limit_req 10r/s (burst 20) +
  limit_conn por IP; HSTS, nosniff, X-Frame-Options DENY, Referrer-Policy;
  proxy_read_timeout do WebSocket Streamlit 86400s→60s (ping nativo 30s).
- ☑ **Containers não-root** (api/dashboard, uid 10001) e
  `no-new-privileges:true` em todos os serviços do compose.
- ☑ **Volume da API read-only** (`./data:/app/data:ro`) — fronteira ADR-026
  também no mount.
- ☑ **Env mínimo por serviço:** api lê `.env.api`, dashboard lê
  `.env.dashboard` (templates commitados) — Streamlit não recebe mais chaves
  CGU/HMAC/Postgres/Airflow.
- ☑ **Admin Airflow sem senha em argv:** entrypoint oficial da imagem
  (`_AIRFLOW_DB_MIGRATE` + `_AIRFLOW_WWW_USER_CREATE`); senha somente por env;
  `AIRFLOW_ADMIN_EMAIL` configurável. (`airflow users password` não existe no
  2.9.x — resets manuais em HML usaram o FAB SecurityManager por stdin.)
- ☑ **API_DOCS_ENABLED:** `/docs`, `/redoc` e `/openapi.json` desligáveis em
  produção (default ligado preserva DX em dev/HML).
- ☑ **Fix overlay HML:** porta 18080 publicada em scheduler E webserver
  (conflito de bind quando ambos sobem) — removida do scheduler.
- ☑ **Rotação de segredos em PRD** (26/08): MINIO_ROOT_PASSWORD,
  POSTGRES_PASSWORD (`ALTER USER`), AIRFLOW_ADMIN_PASSWORD e
  AIRFLOW_FERNET_KEY renovados na VPS de produção; `.env` atualizado.
  Validado pós-rotação: console MinIO `curl IP:9001` → connection refused;
  API `{"status":"healthy"}`; webserver e scheduler do Airflow
  reconectados ao Postgres. **Nota técnica:** `docker restart` não
  recarrega variáveis de ambiente dos containers — foi necessário
  `--force-recreate` para os containers do Airflow assumirem as novas
  credenciais; registrar esse detalhe em runbook de rotação futura.
- ☐ Normalizar CPF antes do HMAC-SHA256 — fontes entregam formatos distintos
  (`123.456.789-09` vs `12345678909`) e a mesma pessoa gera digests diferentes;
  exige reprocesso Bronze→Gold com chave versionada.
- ☐ Dependabot + pin das GitHub Actions por commit SHA (supply chain).
- ☐ Timeout explícito nos healthchecks de container (`urllib.urlopen` sem
  timeout pode travar a thread de healthcheck).
- ☐ Alinhar direção da janela `_truncar_validacao` com watermark vazio:
  Câmara usa os períodos MAIS RECENTES enquanto CGU/Senado varrem os PRIMEIROS
  (cartões 01-02/2013 ≈ 2600 páginas) — explica E2E HML ~50 min.
- ☐ Restringir SSH da VPS ao novo IP na Security List OCI (IP público mudou:
  147.15.38.74; antigo 137.131.175.179 em timeout).
- ☑ **Excludes de artefatos dbt nos scripts de deploy** (25/08): rsync/tar
  não leem o `.gitignore` — `pipeline/gold/target|logs` agora excluídos
  explicitamente em `deploy.sh`/`deploy.ps1` (causa raiz do lixo carregado
  para a VPS no deploy do PRD).
- ☐ **Paths dbt fora do bind mount** (`DBT_TARGET_PATH`/`DBT_LOG_PATH`
  apontando para volume próprio): evita `chmod 777 target logs` e a
  necessidade de sudo sem TTY no deploy (apontado no PRD, 25/08).
  Observação: `dbt.log` NUNCA esteve versionado (`.gitignore` cobre
  `pipeline/gold/logs/`) — o arquivo na VPS era resíduo de rsync antigo.

---

## Sprint 10 — Despesas por Fornecedor, Análises Agregadas e Fix do Fluxo de ML (26/08/2026)

**Objetivo:** fechar o espelho fornecedor→parlamentar na API/dashboard,
adicionar landing institucional para a banca avaliadora, expor camada de
agregações para os novos gráficos, e corrigir bug crítico que zerava as
tabelas analíticas de ML em produção desde a Sprint 9.

- ☑ **Endpoint `GET /fornecedores/{cnpj_cpf_valor}/gastos`** — espelho de
  `listar_gastos` (parlamentar→fornecedor); filtro `?ano=`, paginação
  padrão 100 itens/página. Schemas `GastoFornecedorItem`/`GastosFornecedor`
  (`api/schemas/fornecedores.py`), usando `Moeda` (ADR — hotfix pós-Sprint 9).
- ☑ **Página 05 (fornecedor)** corrigida: consumia `/parlamentares` (sem
  dados); passou a consumir `/gastos`, derivando parlamentares por
  agregação. Filtros ano/mês e gráfico mensal replicados nas páginas
  02–05 (`dashboard/ui.py::filtro_periodo`/`grafico_mensal`).
- ☑ **Bug crítico corrigido — ondas de ML nunca executavam (ADR-035):**
  o DAG ia direto bronze→silver→gold(dbt); os pontos de entrada das
  cargas de ML nunca eram chamados, então `expense_outliers`,
  `network_nodes`, `network_edges`, `politician_similarity` e
  `risk_scores` nasciam vazios em toda execução — páginas de
  Anomalias/Rede/Risco zeradas em produção desde a Sprint 9. Corrigido
  com `gold_core → executar_analytics (pipeline/analytics_stage.py) →
  gold_analytics` + guardrail `alertar_analytics_vazio`. Backfill
  aplicado em produção: 2.418 outliers, 5.803 arestas, 432 risk_scores.
- ☑ **Landing institucional** (`site/index.html`) servida estaticamente
  pelo nginx em `/` (sem upstream, sem acesso a `/api/` — auditado);
  Streamlit movido para `/app/`. **Governança:** esta mudança de
  roteamento contradizia o texto literal do ADR-007/§5 sem ADR próprio —
  formalizada retroativamente como **ADR-036** e refletida em
  `PROJECT_CONTEXT.md §5` (Revisor Técnico, 26/08).
- ☑ **Endpoints de agregação** `GET /agregacoes/{por-uf|por-partido|
  top-parlamentares|no-tempo}` — GROUP BY sobre o Gold (fronteira
  ADR-026 preservada), schemas `extra="forbid"`.
- ☑ **Página "Análises"** (`11_analises.py`) — 4 gráficos Altair
  (gastos por UF, por partido, série mensal, top parlamentares).
- ☑ **Identidade visual do dashboard** (`.streamlit/config.toml` +
  `aplicar_identidade()`) — paleta compartilhada com a landing.
- ☑ Ruff limpo (`ruff check .` — All checks passed) e CI (Gitleaks +
  Ruff + pytest) verde no merge para `main`.

### Pendências abertas nesta sprint

- ☑ **BACKLOG não fechado no fluxo padrão:** as entregas acima foram
  registradas em CHANGELOG.md e no ADR-036, mas só reconciliadas aqui
  retroativamente por auditoria de Revisor Técnico — não no fim natural
  da sprint. Fechamento definitivo em `09cfb31` (remoção dos marcadores
  de conflito órfãos + §14 com branch `hml` formalizada). Lição
  permanente: reforçar o ciclo de Documentador (`sprint_rules`, passo 4)
  antes do merge, não depois.
- ☑ **§4 cita Streamlit Community Cloud:** confirmado com Carlos — o tier
  nunca foi usado; dashboard sempre rodou no Docker Compose da VPS Oracle.
  Corrigido em `2a6f8aa` (PROJECT_CONTEXT.md §4 + nota de reconciliação
  no ADR-007, ADR-036 formaliza a arquitetura real).
- ☑ Cobertura de testes validada localmente em 27/08 (Python 3.12 /
  Windows): **92.35% total, gate de 80% atingido — 398 passed** em
  1h48m. Zero falhas de rede (a máquina local acessa
  `extensions.duckdb.org` normalmente, ao contrário do sandbox de
  auditoria). 5 erros restantes, todos em `tests/pipeline/test_dag.py`
  (`sqlite3.OperationalError: unable to open database file` na metadata
  DB do Airflow) — atrito ambiental de Airflow em Windows (plataforma
  não suportada); o CI em `ubuntu-latest` é o gate autoritativo e lá
  esses testes passam.
- ☑ **Bypass de branch protection em `develop`:** push direto de
  `09cfb31` reportou `Bypassed rule violations`. Verificado via API do
  GitHub em 27/08: proteções **ativas** nas duas branches conforme
  ADR-037 (checks Gitleaks/Ruff/pytest strict, review ≥1, dismiss stale).
  O bypass ocorre só em `develop`, que tem `enforce_admins=false` por
  design (admin contorna com warning auditável); `main` tem
  `enforce_admins=true` (ninguém contorna, só PR). Configuração confere
   com o ADR — comportamento intencional, nenhuma ação necessária.

---

## Sprint 11 — Identidade Visual e Experiência Analítica — EM ANDAMENTO

**Objetivo:** unificar a identidade visual do dashboard com a landing
(paleta navy/verde/dourado), eliminar gráficos default (`st.bar_chart`/
matplotlib sem tema) fora da página 11, tornar a página de rede
interativa, e absorver a dívida de `AppTest` registrada desde a
Sprint 9/10. Sem endpoints novos — `/agregacoes/*` (Sprint 10) já
sustenta os gráficos.

### Onda 0 — Decisão de stack de visualização

- ☑ **ADR-038** — Altair como padrão (rankings, séries, barras);
  Plotly como complemento cirúrgico restrito a grafo de rede (página 06)
  e radar (página 08); ECharts avaliado e descartado; matplotlib
  mantido apenas para exportação PDF de tabelas em `ui.py`.

### Onda 1 — Design system no Streamlit

- ☑ **`dashboard/theme.py`** — paleta como constantes únicas no lado
  Python (`theme.py`, consumido por `ui.py`/`charts.py`/páginas);
  `.streamlit/config.toml` e `site/index.html` permanecem literais por
  natureza estática. CSS ampliado (chrome, tabs, dataframes, expanders,
  inputs, sidebar navy).
- ☑ **`cabecalho_pagina()`** — componente editorial (kicker mono +
  título + lede) replicando o padrão da landing.

### Onda 2 — Biblioteca de gráficos tematizados

- ☑ **`dashboard/charts.py`** — builders compartilhados: `barras_ranking`,
  `serie_mensal`, `barras_vert`, `radar_risco`, `grafo_rede`.
- ☑ Dependência `plotly>=5.22.0` no extra `dashboard` do
  `pyproject.toml` (ADR-006 — nunca no Dockerfile).
- ☑ **Migração de 100% dos gráficos fora da paleta:**
  - `grafico_mensal()` em `ui.py` (páginas 02–05) → `barras_vert`
  - Dois `st.bar_chart` de `07_anomalias.py` → `barras_vert`
  - `st.bar_chart` de `06_rede.py` → `barras_ranking`
  - Radar de `08_ml.py` (matplotlib → Plotly `radar_risco`)
  - `11_analises.py` migra do Altair inline para `barras_ranking`/`serie_mensal`
- ☑ `matplotlib` restrito à exportação PDF de tabelas em `ui.py`
  (verificável via `git grep matplotlib` fora de `ui.py` = zero
  ocorrências em gráficos).

### Onda 3 — Página 06 Rede interativa

- ☑ Grafo com hover/zoom/pan via Plotly (`grafo_rede`), sobre
  NetworkX layout — sem recálculo por request, Gate 3 preservado.

### Onda 4 — Landing, qualidade e fechamento

- ☐ **Landing** — Panorama re-gerado com retrato real de produção
  (estático, sem fetch em runtime — ADR-036 preservado). Revertido
  commit dinâmico (`d0edcc1`) por violação de ADR-036 sem novo ADR.
  Pendente: re-geração manual dos números estáticos com dados de
  produção + OG image.
- ☑ **AppTest** — smoke das 11 páginas + fluxo busca→seleção
  (02/05/06/08), 15 testes verdes (`tests/dashboard/test_apptest.py`).
- ☑ **Governança de fechamento** — BACKLOG, CHANGELOG e
  PROJECT_CONTEXT §4/§6/§13 sincronizados.

### Fora de escopo

Frontend dedicado fora do Streamlit; novos endpoints de API; dark mode;
autenticação/alertas (backlog pós-v1, §1.5).

### Critérios de aceite

- ☑ Zero `st.bar_chart`/`st.line_chart` default remanescente
- ☑ 100% dos gráficos estatísticos na paleta única (`charts.py`)
- ☑ `AppTest` verde nos fluxos críticos (02/05/06/08)
- ☑ Ruff limpo (`ruff check .`)
- ☑ Suíte completa verde, cobertura ≥ 80% (gate `fail_under`,
  Sprint 8) — 92.35% confirmado (398 passed)
- ☑ Documentos de fechamento sincronizados (CHANGELOG, BACKLOG,
  PROJECT_CONTEXT §4/§6/§13)

**Branch:** `sprint/11-identidade-visual` (§14) → `develop` → `hml` →
`main`
