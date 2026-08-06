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

☐ ADR-013 — Fronteira de validação Pydantic vs. Pandera (registro individual vs. DataFrame agregado; quarentena de inválidos)
☐ ADR-014 — Deduplicação independente por camada (Silver deduplica pela chave de negócio pós-normalização, não assume a Bronze)
☐ ADR-015 — Data Quality Report persistido em tabela estruturada (`data_quality_report` particionada por `run_id`)
☐ ADR-016 — Módulo dedicado de normalização multi-fonte (`pipeline/normalize.py`)
☐ Pipeline Silver — normalização, deduplicação e gate Pandera por tabela (`silver_despesa`, `silver_parlamentar`, etc.)
☐ Quarentena de registros inválidos (`data/silver/_quarantine/`) — não descartar nem derrubar a execução
☐ `data_quality_report` — schema adicionado ao `data_dictionary.md` e preenchimento a cada execução
☐ Helper de parse (encerra em NULL/NaT + log estruturado, nunca exceção) coberto por testes unitários isolados
☐ Fechar Sprint 3 — 15/15 testes existentes + novos testes de normalize e Pandera passando

### Escopo futuro explícito (não nesta sprint)

☐ **RF-07 — HTML do Data Quality Report.** a geração de relatório HTML fica reservada para a
   Sprint de documentação automática (RF-07), consumindo a tabela `data_quality_report` —
   não implementada na Sprint 3 (ADR-015).

---

*Este documento é atualizado ao final de cada sprint pelo papel de Documentador.*
*Versão atual: 0.1 — criado retroativamente na Sprint 0A para registrar o histórico de itens já concluídos.*
