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
☑ Registrar ADRs iniciais de arquitetura — ADR-006 (Stack e dependências), ADR-007 (Containers e deploy), ADR-008 (Configuração externa), ADR-009 (Batch/Lambda)
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

*Este documento é atualizado ao final de cada sprint pelo papel de Documentador.*
*Versão atual: 0.1 — criado retroativamente na Sprint 0A para registrar o histórico de itens já concluídos.*
