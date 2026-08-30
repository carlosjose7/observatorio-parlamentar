# Auditoria Formal de Fechamento — Sprints 12 e 13

**Papel:** Documentador / Revisor Técnico  
**Data:** 30/08/2026  
**Commit de referência:** `6a5083b` (main)  
**Escopo:** Verificar sincronia dos três artefatos vivos (CHANGELOG.md, BACKLOG.md, PROJECT_CONTEXT.md §13) com o código efetivamente mesclado em `main`.

---

## 1. Resumo Executivo

| Artefato | Estado | Déficit |
|---|---|---|
| `CHANGELOG.md` | Última sprint documentada: **Sprint 11** (29/08) | **Sprint 12 e Sprint 13 não têm entrada** |
| `BACKLOG.md` | Última sprint documentada: **Sprint 12** (29/08) | **Sprint 13 não existe como seção** |
| `PROJECT_CONTEXT.md §13` | Tabela de roadmap para em **Sprint 11 ✅** | **Sprint 12 e Sprint 13 ausentes da tabela** |

**Conclusão:** Todo o código das Sprints 12 e 13 está em `main` (commits confirmados), mas os três artefatos vivos não refletem isso. O ciclo de fechamento de Documentador (`sprint_rules.md`, passo 4) não foi executado para nenhuma das duas sprints.

---

## 2. Auditoria por Artefato

### 2.1 CHANGELOG.md

**Última entrada de sprint:** Sprint 11 — Identidade Visual e Experiência Analítica (29/08/2026) — FECHADA

**Entradas adicionadas entre Sprint 11 e Sprint 12:**
- Infraestrutura — Deploy automático via GitHub Actions (27/08/2026)
- Correção — deploy.yml publicava develop em vez de main (27/08/2026)

**Sprint 12 — Ausente.** Itens que deveriam constar:
- `## Sprint 12 — Batalha Parlamentar, Contador de Visitas e Congresso (29/08/2026) — FECHADA`
- Adicionado: `botao_voltar()` em `ui.py` + todas as páginas 02–11
- Adicionado: ADR-040 (contador global via backend DuckDB dedicado)
- Adicionado: `api/schemas/contador.py`, `api/routers/contador.py`, `api/repo.py::incrementar_visitas()`
- Adicionado: fetch do contador no frontend `site/index.html` com deduplicação por sessão
- Adicionado: CSS Congresso Nacional (duplas cúpulas, 6 colunas, bandeira)
- Adicionado: ADR-041 (comparabilidade de período)
- Adicionado: `dashboard/comparacao.py` + `SobreposicaoPeriodo`
- Adicionado: Página 12 — Batalha Parlamentar (`dashboard/pages/12_batalha.py`)
- Adicionado: Extra `dev-dashboard` em `pyproject.toml`
- Corrigido: `_tratar_erro_gold` NameError em `api/repo.py:106` (decorator referenciado antes da definição)

**Sprint 13 — Ausente.** Itens que deveriam constar:
- `## Sprint 13 — Hardening CI, urlFoto e Fotos do Dashboard (30/08/2026)`
- Adicionado: Gitleaks v3.0.0 (era v2) em `ci.yml`
- Adicionado: Dependabot semanal para GitHub Actions (`.github/dependabot.yml`)
- Adicionado: Todas as Actions pinadas por SHA (`ci.yml`)
- Adicionado: Extra `dev-dashboard` no `pyproject.toml`
- Adicionado: Pipeline urlFoto Bronze→Silver→Gold→API
  - Bronze: `CamaraBronzeDeputado.url_foto` + extração em `_construir_deputado()`
  - Silver: `url_foto` em `COLUNAS_SILVER_PARLAMENTAR` + DDL + transform
  - Gold: `url_foto` em `dim_parlamentar.sql` (todas as CTEs)
  - API: `url_foto` em `PerfilParlamentar`, `ParlamentarResumo`, `AgentParlamentar`
  - Resultado: 513/513 Câmara com URL, 81/81 Senado NULL (API não fornece)
- Corrigido: "Voltar ao Início" `href="/app/"` → `href="/"` em `ui.py`
- Corrigido: `Field` import faltando em `api/schemas/agent.py`
- Corrigido: Senado transform `url_foto=None` (prevenia `KeyError` no Silver)
- Adicionado: Componente `avatar_parlamentar()` em `ui.py` com fallback SVG silhouette
- Adicionado: CSS `.op-avatar` e `.op-avatar-sm` em `theme.py`
- Adicionado: Foto do parlamentar nas páginas 02, 08 e 12
- Corrigido: 4 erros ruff pre-existing no develop (I001, F401)
- Temporário: `validacao.habilitado: true` em `config/pipeline.yaml` ( Bronze OOM com histórico completo)

---

### 2.2 BACKLOG.md

**Última sprint documentada:** Sprint 12 — Batalha Parlamentar, Contador de Visitas e Congresso (29/08/2026)

A seção Sprint 12 está completa e detalhada (Ondas 1–4, documentação, débito técnico, critérios de aceite, branch).

**Sprint 13 — Ausente.** Não existe seção `## Sprint 13` no arquivo. Deveria conter:

- **Objetivo:** Hardening CI/CD, pipeline urlFoto (Bronze→Silver→Gold→API), exibição de fotos no dashboard, correção de bugs de UX.
- **Itens concluídos:**
  - ☑ Gitleaks v3.0.0 (substitui v2)
  - ☑ Dependabot semanal para Actions (`.github/dependabot.yml`)
  - ☑ Todas as Actions pinadas por SHA (checkout v4.2.2, setup-python v5.6.0, gitleaks-action v3.0.0)
  - ☑ Extra `dev-dashboard` em `pyproject.toml`
  - ☑ Pipeline urlFoto: `CamaraBronzeDeputado.url_foto` → Silver `url_foto` → Gold `dim_parlamentar.url_foto` → API (`PerfilParlamentar`, `ParlamentarResumo`, `AgentParlamentar`)
  - ☑ Componente `avatar_parlamentar()` em `ui.py` com fallback SVG silhouette cinza
  - ☑ CSS `.op-avatar` / `.op-avatar-sm` em `theme.py`
  - ☑ Fotos nas páginas 02 (perfil), 08 (ML), 12 (batalha)
  - ☑ Fix: `href="/app/"` → `href="/"` (botão voltar)
  - ☑ Fix: `Field` import em `api/schemas/agent.py`
  - ☑ Fix: `url_foto=None` no Senado transform
  - ☑ Fix: 4 erros ruff pre-existing (I001 repo.py, F401 12_batalha.py, F401 test_comparacao.py)
- **Nota:** `validacao.habilitado: true` temporário — rever Bronze OOM com histórico completo.
- **Branch:** `sprint/13-hardening` + `feature/sprint-13-fotos` → `develop` → `hml` → `main`
- **Commits:** `51d39a5`, `f036660`, `989affa` (#36), `a9f810c`, `2755a4d` (#41), `6a5083b` (#42)

---

### 2.3 PROJECT_CONTEXT.md §13 (Roadmap)

**Última linha da tabela:** Sprint 11 — ✅ Concluída

**Sprint 12 — Ausente da tabela.** Deveria ser:

```
| **12** | Batalha Parlamentar, Contador de Visitas e Congresso | Página comparativa, contador global DuckDB, CSS Congresso (ADR-040/041) | ✅ Concluída |
```

**Sprint 13 — Ausente da tabela.** Deveria ser:

```
| **13** | Hardening CI, urlFoto e Fotos do Dashboard | Gitleaks/Dependabot/SHA pins, pipeline urlFoto Bronze→API, avatar no dashboard | ✅ Concluída |
```

**Nota adicional:** a versão do documento (`PROJECT_CONTEXT.md`, rodapé linha 815) diz "Sprint 9 FECHADA" — desatualizada em relação ao próprio §13 (que já listava Sprint 10 e 11). O rodapé deveria refletir a sprint mais recente documentada.

---

## 3. Inventário de Commits (main, Sprints 12–13)

| Commit | PR | Descrição |
|---|---|---|
| `226bab2` | #32 | feat(sprint-12): Batalha Parlamentar, contador de visitas e Congresso CSS |
| `130b996` | #32 | fix(sprint-12): correcao do calculo de sobreposicao de periodo |
| `69072e3` | #32 | fix(sprint-12): reverte denominador para 'menor período' (ADR-041) |
| `c087303` | #32 | fix(sprint-12): bug _de_total_meses + infra de testes containerizada |
| `1efc541` | #32 | feat(sprint-12): Batalha Parlamentar, Contador de Visitas e Congresso CSS |
| `51d39a5` | #35 | feat(sprint-13): hardening CI + dev-dashboard para testes de UI |
| `f036660` | #35 | feat(sprint-13): urlFoto pipeline Bronze→Gold→API + fix voltar início |
| `989affa` | #36 | feat(sprint-13): urlFoto pipeline + fix voltar início |
| `a9f810c` | #41 | feat(dashboard): exibir foto do parlamentar em páginas 02, 08 e 12 |
| `2755a4d` | #41 | fix: resolver 4 erros ruff pre-existing no develop |
| `6a5083b` | #42 | feat(dashboard): fotos dos parlamentares |

---

## 4. Ações Necessárias (Prioridade)

| # | Ação | Artefato | Prioridade |
|---|---|---|---|
| 1 | Adicionar entrada `## Sprint 12 — ... — FECHADA` ao CHANGELOG.md | CHANGELOG.md | **Alta** |
| 2 | Adicionar entrada `## Sprint 13 — ...` ao CHANGELOG.md | CHANGELOG.md | **Alta** |
| 3 | Adicionar seção `## Sprint 13` ao BACKLOG.md (itinários, critérios, branch) | BACKLOG.md | **Alta** |
| 4 | Adicionar linhas Sprint 12 e 13 à tabela de roadmap em §13 | PROJECT_CONTEXT.md | **Alta** |
| 5 | Atualizar rodapé do PROJECT_CONTEXT.md (versão e sprint de referência) | PROJECT_CONTEXT.md | **Média** |
| 6 | Reverter `validacao.habilitado: true` para `false` em `config/pipeline.yaml` (após resolver Bronze OOM) | config/pipeline.yaml | **Média** |

---

## 5. Lições Aprendidas

1. **"Checkbox marcado ≠ fato até auditar"** — O código de Sprint 12/13 está em `main`, PRs foram merged, deploy funcionou, mas nenhum dos três artefatos vivos refletia o estado real. O ciclo de fechamento de Documentador (`sprint_rules.md` passo 4) precisa ser executado **antes** do merge para `main`, não depois.

2. **Backlog como fonte parcial** — O BACKLOG.md documentou Sprint 12 (o próprio autor o fez), mas Sprint 13 ficou registrada apenas em commits e PRs. O hábito de atualizar BACKLOG em tempo real (não só no fechamento) mitiga o risco.

3. **Versionamento do PROJECT_CONTEXT.md** — O rodapé ("Versão atual: Sprint 9 FECHADA") está 4 sprints desatualizado. Recomendação: atualizar o rodapé a cada merge em `main`, mesmo que parcialmente.

---

*Auditoria concluída em 30/08/2026. Pendências de atualização dos três artefatos registradas acima.*
