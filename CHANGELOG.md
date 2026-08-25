# Changelog

Plataforma de Inteligência Parlamentar Brasileira.

Histórico das alterações, organizado por sprint (ver
`docs/governance/sprint_rules.md`). Segue as boas práticas do
[Keep a Changelog](https://keepachangelog.com/).

---

## Segurança — Hardening pós-auditoria (25/08/2026)

### Segurança
- **Console MinIO removida do proxy público:** `location /minio/` publicava a
  console administrativa do object storage (login com credenciais root) para a
  internet, anulando o bind local `127.0.0.1:9001`. Acesso operacional agora é
  exclusivamente via SSH tunnel (`nginx/default.conf`, `nginx/bootstrap.conf`).
- **Rate limit por IP no nginx:** `limit_req` (10r/s, burst 20, nodelay) e
  `limit_conn` nas rotas `/api/`, `/docs`, `/openapi.json` e dashboard — mitiga
  brute force e DoS de aplicação.
- **Headers de segurança** com flag `always`: HSTS (1 ano, includeSubDomains),
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`.
- **WebSocket do Streamlit:** `proxy_read_timeout` de 86400s (24h) → 60s; o
  ping nativo do Streamlit (30s) mantém a conexão viva — fecha vetor slowloris.
- **Containers não-root:** imagens da API e do dashboard criam usuário dedicado
  (uid 10001) em vez de rodar como root.
- **`no-new-privileges:true`** em todos os serviços do compose (antes só o
  MinIO tinha).
- **Volume da API read-only:** `./data:/app/data:ro` — a fronteira de leitura
  do ADR-026 vale também no mount; nem sob RCE o container altera o Gold.
- **Env mínimo por serviço:** a API lê `.env.api` e o dashboard `.env.dashboard`
  (templates commitados). O dashboard não recebe mais `CGU_API_KEY`,
  `CPF_HMAC_SECRET_KEY`, `POSTGRES_PASSWORD` nem credenciais Airflow — RCE no
  Streamlit não vira comprometimento total de segredos.
- **Admin do Airflow sem senha na linha de comando:** entrypoint custom que
  passava `--password "$AIRFLOW_ADMIN_PASSWORD"` (visível em `ps aux`) foi
  substituído pelo mecanismo oficial da imagem (`_AIRFLOW_DB_MIGRATE` +
  `_AIRFLOW_WWW_USER_CREATE/_AIRFLOW_WWW_USER_USERNAME/PASSWORD/EMAIL`);
  criação idempotente e falhas visíveis. `AIRFLOW_ADMIN_EMAIL` configurável.
- **Rotação de segredos em HML** executada antes do deploy (console MinIO
  estava pública → credenciais tratadas como comprometidas): MinIO root,
  Postgres, admin Airflow e Fernet key renovados com CSPRNG na própria VPS;
  E2E verde pós-rotação. PRD aguarda este deploy.

### Adicionado
- **`API_DOCS_ENABLED`** (env, default `true`): desabilita `/docs`, `/redoc` e
  `/openapi.json` em produção para não autodocumentar a superfície de ataque.
  `api/main.py` expõe factory `criar_app()`; testes cobrem os dois estados.
- **`.env.api.example` / `.env.dashboard.example`:** templates dos ambientes
  mínimos por serviço.

### Corrigido
- **Overlay HML (`docker-compose.hml.yml`):** porta 18080 publicada
  simultaneamente no `airflow-webserver` e no `airflow-scheduler` — conflito de
  bind quando ambos sobem; bloco removido do scheduler.

---

## Pós-Sprint 9 — Hotfix em produção

### Corrigido
- **Busca por ID cru em `08_ml.py` e `06_rede.py` (reportado como bug de
  UX):** as duas páginas exigiam que o usuário informasse o
  `id_parlamentar` numérico diretamente (`st.number_input`), sem busca
  por nome — inconsistente com o padrão já estabelecido em
  `02_parlamentar.py`/`05_fornecedor.py`, e causava erro genérico
  (`Erro na consulta: Parlamentar {id} não encontrado`) para qualquer ID
  que o usuário não soubesse de cor. Corrigido substituindo o
  `number_input` pelo mesmo fluxo de busca+seleção (nome/UF/partido →
  `st.selectbox`) já usado em `02_parlamentar.py`, reaproveitando
  `client.listar_parlamentares` — sem endpoint novo. `08_ml.py` usa a
  sidebar (`ml_*` como prefixo de `session_state`, isolado das outras
  páginas); `06_rede.py` idem (`rede_*`), aplicado dentro da aba "Rede
  do parlamentar" (a aba "Comunidades" não depende de ID). Varredura
  completa por `number_input` no restante de `dashboard/pages/` não
  encontrou mais ocorrências do padrão. Sem novo ADR — alinhamento de UX
  a um padrão já em produção, não decisão arquitetural nova.

- **`KeyError: None` em `dashboard/pages/05_fornecedor.py`:** o seletor de
  fornecedor (`st.selectbox(..., key="forn_sel")`) é precedido, no fluxo de
  nova busca, por `st.session_state["forn_sel"] = None` — reset válido do
  Streamlit para forçar seleção vazia após uma nova busca, já usado com
  segurança em `02_parlamentar.py`. Diferente de `02_parlamentar.py`,
  porém, `05_fornecedor.py` não tinha a guarda `if sel is None: return
  None` após o `st.selectbox`, então `opcoes[sel]` explodia com
  `KeyError: None` no primeiro render pós-busca (antes do usuário
  interagir com o dropdown). Auditados os demais `selectbox` do
  dashboard (`03_partido.py`, `04_estado.py`) — não usam esse padrão de
  reset via `key`, não afetados. Corrigido replicando a guarda já
  validada em produção em `02_parlamentar.py`. Sem teste de regressão
  automatizado ainda — o projeto não usa `streamlit.testing.AppTest` para
  as páginas (`tests/dashboard/` cobre `client.py`/`ui.py`, não as
  páginas); registrado como pendência no BACKLOG.
- **Documentação retroativa — `.gitattributes` (commit `1b54475`):** o
  fix de CRLF nos scripts shell (`nginx/entrypoint.sh` crashava com
  `exit 127` no rebuild via checkout Windows) foi commitado sem entrada
  correspondente aqui, apesar do próprio `.gitattributes` referenciar
  "Ver CHANGELOG". Registrado agora: `.gitattributes` (`*.sh text
  eol=lf`) garante LF em todo `.sh` versionado, eliminando a
  reintrodução de CRLF em checkouts Windows.
- **Decimal serializado como string em JSON:** campos monetários da API
  (`valor_liquido`, `valor_glosa`, `valor_liquido_total`, `total_gasto`)
  eram tipados como `Decimal` puro nos schemas Pydantic; o Pydantic v2
  serializa `Decimal` para JSON como string (`"150.30"`), não número
  (`150.3`). Quebrava `dashboard/pages/02_parlamentar.py` em produção
  (`ValueError: Unknown format code 'f' for object of type 'str'` em
  `formatar_moeda`) e, de forma latente, `05_fornecedor.py` e
  `07_anomalias.py`. Corrigido com o novo tipo `Moeda`
  (`api/schemas/_common.py`, `PlainSerializer` no modo JSON) aplicado em
  `api/schemas/parlamentares.py`, `anomalias.py` e `fornecedores.py`.
  `Decimal` continua sendo o tipo interno; apenas o encoder JSON da API
  passa a emitir número. Sem impacto de precisão, sem novo ADR (correção
  de implementação, não reabertura de decisão arquitetural).

---

## Sprint 9 — Deploy + Documentação — FECHADA

### Adicionado
- **ADR-034** — execução diária do pipeline via `systemd timer` na VPS Oracle
  (Opção B); GitHub Actions restrito a CI (sem CD).
- **`ci.yml`** (substitui `pipeline.yml` placeholder) — Gitleaks + Ruff +
  `pytest --cov` com gate 80% em PR/push em `develop`/`main`. No CI o Airflow
  existe → `test_dag.py` roda como barreira real (379 testes esperados).
- **`scripts/run_pipeline_daily.sh`** — sobe perfil `pipeline` (postgres +
  scheduler), healthcheck `list-import-errors`, unpause explícito, trigger com
  `run_id` determinístico, polling via `list-runs --output json` (compatível
  com Airflow 2.9), `down` garantido no trap EXIT.
- **`infra/observatorio-pipeline.service`/`.timer`** — oneshot às 03:00
  America/Sao_Paulo, `Persistent=true`.
- **Gate 3 — Ruff estrito:** habilitados `I`, `W292`, `UP017/UP035/UP037`;
  auto-fix aplicado (113 correções). Deferidos: `E501` (massivo), `B904/B905`
  (semânticos).
- **Gate 4 — Documentação:** `README.md` §II.6 (observabilidade) e §III
  (case com dados reais), `docs/guia_deploy_operacao.md`, healthchecks no
  `docker-compose.yml`.

### Corrigido
- **`pipeline_dag.py::_executar_gold`** — `NameError` latente: o snippet do
  subprocesso dbt usava `json.dumps`/`sys.path` sem importar `json`/`sys`
  (quebraria o Gold em produção). Import adicionados ao snippet.
- **Duplicação de agendamento (Gate 2):** o DAG tinha `schedule="@daily"`
  simultaneamente ao timer `systemd` — dois relógios independentes disparando
  o mesmo pipeline (scheduler interno do Airflow + timer externo), causando
  execuções concorrentes na primeira tentativa de backfill em produção.
  Corrigido para `schedule=None` — agendamento passa a ser **exclusivamente
  externo** via `observatorio-pipeline.timer` (ADR-034). `test_dag.py`
  atualizado para refletir o novo contrato (`schedule_interval is None`).
- **Reconciliação de cobertura:** medição anterior de 87% (pós-fixes E2E
  HML) era resultado de `.coverage` acumulado/sujo entre execuções.
  Medição limpa (`rm -f .coverage` + suíte completa) no commit `61c4c66`:
  **374 passed, 93,53% cobertura** — valor de referência para o fechamento
  da sprint.
- **`pipeline_runs` vazio em produção (ADR-019):** a Bronze grava o
  controle no MinIO (storage MinIO, ADR-007), mas o dbt Gold lia o glob
  local `data/bronze/...` → 0 arquivos. Fix: `httpfs` + secret S3 no
  `profiles.yml` (endpoint SEM scheme — DuckDB 1.0.0 quebra URL com
  `http://`) e `get_dbt_vars()` injetando `bronze_pipeline_runs_dir` S3
  quando `MINIO_ENDPOINT` configurado.
- **Gold falha sem dados CGU:** `_garantir_silver_cgu_vazio` cria
  `silver_cartao`/`silver_emenda` vazias (schema de `schemas_silver.py`)
  quando a CGU não retorna dados — o dbt build falhava com "table does not
  exist".
- **Deploy:** `chmod +x scripts/run_pipeline_daily.sh` no passo 4/6 do
  `deploy.sh` (unit sem prefixo `bash` → 203/EXEC sem o bit).
- **SELinux (Oracle Linux):** systemd falhava com 203/EXEC mesmo com o bit
  +x (contexto `user_home_t`). `chcon -t bin_t` no script.
- **Permissões de dados:** `chmod -R a+rwx data/` para o container airflow
  (uid 50000) escrever no DuckDB da Gold (dono `opc`, uid 1000).

### Adicionado (fechamento)
- **Ambiente HML portado** (`docker-compose.hml.yml`, `config.hml/`,
  `.env.hml.example`, `scripts/run_hml_e2e.sh`) da branch `hml` órfã para
  `develop`, com isolamento corrigido (`*_ENV_FILE` → `.env.hml`).

Resultado da Sprint 9 (verificado por auditoria direta em `61c4c66` +
fixes até `9ad47c2`): **Gates 1–5 concluídos e comprovados** (CI real,
Ruff estrito **374 passed/93,53% cobertura**, README/guias completos, TLS
ao vivo, execução diária via systemd). **Gate 2 fechado em 25/08:** timer
`enabled`/`active (waiting)`, execução via systemd `SUCCESS` (run_id
`4e52260e`, 1676s), `pipeline_runs` populado via MinIO/S3 —
`GET /api/pipeline/status` → `{"total":3}` (linha nova no topo);
`GET /api/agent/context` → `pipeline.run_id=4e52260e` com dados novos na
Gold (`total_gasto` 608.742.032 → 608.821.853). **Sprint 9 FECHADA.**

---

## Sprint 8 — Testes e Qualidade — FECHADA

### Adicionado
- **`tests/pipeline/test_gold_contracts.py`** — cobertura de todos os contratos
  Pydantic Gold, com casos válidos e campos obrigatórios; `pipeline/gold.py`
  alcançou 100% de cobertura.
- **`tests/pipeline/test_storage.py`** — Local/MinIO fake, deduplicação mensal
  e anual, arquivo de controle e seleção de backend; `storage.py` alcançou 99%.
- **Gates locais** — Ruff no extra `dev` (`python -m ruff check .`) e
  `fail_under = 80` no coverage, agora incluindo `dashboard`.

### Corrigido
- Imports não utilizados e nomes mortos apontados pelo conjunto inicial do
  Ruff, preservando o comportamento dos testes existentes.

### Segunda entrega
- **Watermark** — cobertura dos stores JSON, namespace e Airflow fake (import
  lazy e serialização), sem depender da instalação opcional do Airflow.
- **Pseudonimização** — regressões para CPF vazio, chave HMAC ausente e lotes
  sem CPF, que não devem consultar segredo.
- **Senado e API** — carga Bronze→Silver vazia/delegada e tradução uniforme de
  indisponibilidade da Gold em HTTP 503 nas rotas individuais de parlamentares
  e fornecedores.

Recorte validado: **57 passed**; os cinco módulos priorizados desta etapa
atingiram 100% de cobertura.

### Terceira entrega (gate consolidado de fechamento)

Suíte completa reexecutada com `.coverage` limpo — **374 passed, 1 skipped
(Airflow)** e cobertura global de **93,58%** (0:18:31). `anomalies.py`
confirmado em 100%: o valor de 87% anteriormente registrado era artefato de
medição (`.coverage` acumulado de execuções anteriores), não uma lacuna real —
os testes de fronteira/persistência já cobriam os ramos listados.

Resultado da Sprint 8: **374 passed, 1 skipped (Airflow)**, cobertura
global **93,58%** (0:18:31). O conjunto estrito de regras de estilo/import
ordering do Ruff foi conscientemente postergado para uma migração própria
(item de backlog explícito).

### Itens aceitos e deferidos (registro explícito de fechamento)
- **Ruff estrito (import ordering/estilo)** — conjunto `E4/E7/E9/F` aplicado;
  regras de estilo/`I` (import ordering) **deferidas como item de backlog**
  (migração própria, não ficam como observação solta desta sprint).
- **`pipeline/storage.py` em 99%** (1 ramo parcial, `188->190`) — **aceito**;
  acima do limiar global, não exige 100%.
- **`dashboard/ui.py` em 62%** — **aceito** (acima do limiar global de 80%);
  cobertura de utilitários de exportação fica como dívida registrada no backlog.
- **`dashboard/app.py` em 0%** — entrypoint Streamlit (`if __name__ ==
  "__main__"`), não importado por testes; característica normal, não é lacuna.
- Nenhum ADR novo necessário — sem decisão arquitetural, apenas qualidade/teste.

### Fechamento da Sprint 8
**Sprint 8 — DONE / QA APPROVED.** Testes e qualidade: contratos Gold (100%),
persistência Parquet (99%), watermark/pseudonimização/Senado/routers/anomalias
(100%), gates locais de Ruff (`dev` extra) e coverage (`fail_under = 80` com
`dashboard` no source). **374 testes verdes, 1 skip Airflow, 93,58% de
cobertura global** em medição limpa (0:18:31). Commit de fechamento
(progresso + encerramento): `fdad9c0`. ADRs vigentes: 001-033.

---

## Sprint 7 — Dashboard (Streamlit) — FECHADA

### Adicionado
- **`dashboard/client.py`** — cliente HTTP da API REST (RF-05, ADR-026):
  um método por endpoint (`/parlamentares`, `/fornecedores`, `/anomalias`,
  `/rede`, `/qualidade`, `/pipeline/status`, `/agent/*`), com `ApiError`
  (erro de negócio com `detail`) e `ApiIndisponivel` (rede offline). A base
  URL vem de `API_URL` (config ADR-008, default `http://localhost:8000`).
- **`dashboard/ui.py`** — componentes reutilizáveis: `formatar_moeda`
  (pt-BR), `carregar_com_feedback` (spinner + erro amigável), `estado_api`,
  `metricas_seguras` e `tabela_exportavel` (CSV/Excel/PDF, RF-08).
- **`config/dashboard.yaml`** + `DashboardSettings` (`pipeline/config.py`) —
  fonte única de configuração do dashboard (ADR-008): título, base URL via
  env var, timeout e formatos de exportação.
- **Página 01 (Visão Geral)** — `dashboard/app.py`: KPIs globais (total
  gasto, transações, fornecedores, parlamentares, anomalias), períodos com
  dados, status dos serviços e execuções recentes do pipeline (RF-12).
- **Página 02 (Parlamentar)** — perfil SCD2 + despesas com filtro por ano.
- **Páginas 03/04 (Partido/Estado)** — agregação de parlamentares por
  partido/UF com total gasto.
- **Página 05 (Fornecedor)** — perfil + top parlamentares (ADR-011/033:
  CNPJ claro, CPF pseudonimizado).
- **Página 06 (Rede)** — grafo parlamentar-fornecedor (NetworkX) + 
  comunidades (ADR-030).
- **Página 07 (Anomalias)** — agregados por ano/critério + lista com
  threshold de z-score (ADR-002).
- **Página 08 (ML/Risco)** — scores de risco (radar, ADR-029), risk index e
  top fornecedores via `/agent/parlamentar/{id}` (ADR-032).
- **Página 09 (Qualidade)** — Data Quality Report do Gold (ADR-033).
- **Página 10 (Metadados)** — catálogo de fontes e execuções (RF-12).
- **`tests/dashboard/`** — 20 testes do client (rotas, erros, base URL) e
  dos utilitários de UI.
- **`pyproject.toml`** — extra `dashboard` com `openpyxl`/`matplotlib`;
  `[tool.setuptools.packages.find]` declarado (flat-layout).

### Resultado
Suíte completa: **336 passed, 1 skipped** (20 novos do dashboard + 316
anteriores). Dashboard validado com `AppTest` contra o DuckDB dev (dados do
E2E real): KPIs com dados reais (total gasto R$ 4,5M, 8.983 transações),
perfil/risco de parlamentar real, DQ report e execuções.

### Auditoria técnica (gates de revisão) — Sprint 7
Correções de robustez/segurança/performance após revisão de Tech Lead:

- **Gate 1 — HTTP client (`dashboard/client.py`):** corpo 2xx não-JSON
  vira `ApiError` (antes `JSONDecodeError` escapava para o Streamlit); retry
  limitado para transitórios (5xx/rede, GET idempotente) — 4xx NUNCA é
  retried (contractual); limite de tamanho de resposta (`resposta_max_bytes`,
  config ADR-008); mensagens de erro amigáveis sem expor URL interna.
- **Gate 2 — Exportações (`dashboard/ui.py`):** Excel/PDF limitados a
  `exportacao_max_linhas` (config) com aviso de truncamento — CSV mantém o
  dataset completo; evita DoS de memória/CPU com datasets grandes.
- **Gate 3 — Rede/NetworkX:** página 06 limita arestas/nós renderizados
  (`_MAX_ARESTAS`/`_MAX_NOS_COMUNIDADE`); **API `/rede/comunidades` ganhou
  `limite_nos`** (default 200, teto 1000, enforced no SQL via
  `row_number() over (partition by comunidade_id, periodo order by pagerank
  desc)`) — o payload nunca explode com grafos reais.
- **Gate 4 — CNPJ em URL:** `_codificar_path` faz URL-encode de segmentos de
  path (`/` de CNPJ mascarado não quebra a rota); regressão para CNPJ
  mascarado/espaços.
- **Gate 5 — E2E real:** `tests/dashboard/test_integracao_api.py` sobe a
  FastAPI real (uvicorn em subprocesso, socket TCP) sobre DuckDB Gold
  semeado e conecta o `ApiClient` via HTTP real — SEM mock de resposta.
  8 cenários (parlamentares, perfil/gastos, agent/risco, contexto, fornecedor,
  anomalias/qualidade, 404→`ApiError`, comunidades com limite).
- **Dívida registrada (não resolvida pela Sprint 7):** autenticação/TLS
  permanecem pendentes (ADR-007) — o dashboard amplia a superfície da API;
  proteger em deploy público (VPN/reverso TLS) antes de expor fora de
  rede confiável. Item no BACKLOG.

### Resultado da auditoria
Suíte completa: **349 passed, 1 skipped** (13 novos dos gates: 8 E2E HTTP +
5 robustez + anteriores). `tests/api/` 58 passed (limite_nos compatível).

### Fechamento da Sprint 7
**Sprint 7 — DONE / QA APPROVED.** Dashboard Streamlit completo: 10 páginas
(visão geral, parlamentar, partido, estado, fornecedor, rede, anomalias,
ML/risco, qualidade, metadados), cliente HTTP (RF-05), exportações
CSV/Excel/PDF (RF-08), config externa via `config/dashboard.yaml` (ADR-008).
Auditoria técnica (Gates 1-5) concluída: client HTTP robusto, exportações
com teto, rede limitada na API e no dashboard, CNPJ URL-encoded, E2E HTTP
real sem mock. **349 testes verdes** (1 skip Airflow, mesmo padrão da
Sprint 6.5). Dívida técnica registrada e não bloqueante: autenticação/TLS
pendentes (ADR-007, a resolver na Sprint 9). Commit de fechamento:
`bdf1cb3`. ADRs vigentes: 001-033.

---

## Sprint 6.5 — Validação End-to-End (manutenção estrutural) — FECHADA

### Adicionado — Validação E2E real (Bronze→Silver→Gold com APIs reais)
- `scripts/run_e2e_local.py`: runner completo em modo validação (`limite 2`,
  watermark em namespace `validacao:`, `--reset` para rebuild determinístico).
  Exercita a cadeia ponta-a-ponta com as quatro fontes e `dbt build` completo
  no subprocesso.
- Corretivos encontrados na validação real (com regressões):
  - **BUG-007** — coluna de texto toda nula (Câmara `nome_parlamentar`)
    era inferida `INTEGER` no DuckDB ao criar a tabela, derrubando o INSERT
    do Senado (`ConversionException`). `silver.py::_criar_tabela_se_necessario`
    normaliza colunas `object` → `string` (VARCHAR) na inferência.
  - **BUG-008** — cartões CGU (2012-2013) rejeitados por limite de sanidade
    do parser e gate Pandera; limites ajustados para 2012 (`normalize.py`,
    `quality.py`). Transações pré-2015 no Gold seguem para `fact_cartao_cpgf_
    quarantine` (horizonte `dim_data` 2015-2035 — limitação conhecida).
  - **BUG-009** — `ml_staging` ausente quebrava o `dbt build` completo
    (ADR-026, escrita exclusiva dos scripts de ML); o runner cria o schema
    vazio antes do build (mesmo contrato do selo de contrato).
  - **BUG-010** — `pipeline_runs` Gold vazio (glob `bronze_pipeline_runs_dir`
    resolvido relativo ao cwd, não ao arquivo do banco) e consolidação de
    arquivos com `fontes_com_erro` de tipos mistos (`INTEGER[]` legado vs
    `VARCHAR[]`). `dbt_project.yml` com caminho relativo ao repo root;
    `pipeline_runs.sql` com `union_by_name = true` + `cast(... as varchar[])`.
  - **BUG-011** — runner E2E: `import json`/`import sys` faltantes no
    subprocesso do build e `→` incompatível com cp1252 no `--reset`.
- Resultado da validação: Bronze `success` (4 fontes), Silver Câmara 9.350 +
  Senado 63.874 despesa / parlamentar 514+162 / cartão ~120k / emenda 45.799,
  Gold `dbt build` PASS=224 ERROR=0, `pipeline_runs` 12 linhas no dev.

### Corrigido (alinhamento documental de segurança — BUG-DOC-001)
- **README/PROJECT_CONTEXT/ADR-004 alinhados ao ADR-033.** A documentação
  ainda afirmava que o CPF era pseudonimizado "antes de qualquer persistência
  — inclusive na Bronze" (postura do ADR-004 original). ADR-033 mudou a
  fronteira para a Silver: a Bronze mantém o CPF bruto equivalente-público
  sob acesso restrito, e Silver/Gold/API só expõem o hash. Corrigidos
  `README.md §II.5`, `PROJECT_CONTEXT.md` (RF-06 + RNF Segurança/LGPD) e a
  redação do ADR-004 (Status/Decisão) com a nota de refinamento pelo ADR-033.

### Segurança (CWE-798 — resolução da pendência de rotação/histórico)
- **Varredura do histórico concluída (872 blobs):** o único secret
  versionado foi uma Fernet key curta (13 chars, inválida como Fernet) no
  `docker-compose.yml` — nenhuma senha real, chave CGU ou
  `CPF_HMAC_SECRET_KEY` esteve em commits. **Decisão: não reescrever o
  histórico** (sem valor de exploração; force-push sem benefício).
- **Gitleaks no CI:** job `secret-scan` em `.github/workflows/pipeline.yml`
  (dispara em `workflow_dispatch` + `pull_request`) com `.gitleaks.toml`
  próprio — regra extra para Fernet key e campos de secret do projeto
  (`CPF_HMAC_SECRET_KEY`, `CGU_API_KEY`, `MINIO_ROOT_PASSWORD`,
  `POSTGRES_PASSWORD`, `AIRFLOW_FERNET_KEY`, `AIRFLOW_ADMIN_PASSWORD`),
  allowlist de placeholders. Previne regressão da CWE-798.
- **Rotação documentada:** valores que já estiveram em repositório público
  tratam-se como comprometidos — gerar nova Fernet key
  (`Fernet.generate_key()`) e substituir no `.env`; mesma regra para
  `CGU_API_KEY`/`CPF_HMAC_SECRET_KEY` caso alguma cópia do `.env` com
  valores reais tenha sido compartilhada.

### Status final da sprint (QA approved)
**Sprint 6.5 — DONE / QA APPROVED.** Functional PASS · Integration PASS ·
E2E real PASS · Data Quality (Gold 224/0) PASS · Security Secret Audit
(872 blobs + teste de controle 3/3) PASS · Regression (316 passed + 1 skipped) PASS ·
Documentation PASS · Working tree CLEAN.
Recomendação de hardening (fora da sprint, monitorar na Sprint 9 quando o
CI real entrar): garantir proteção da branch `develop` exigindo o job
`secret-scan` (Gitleaks) como check obrigatório em qualquer caminho de
merge/commit — hoje ele dispara em `workflow_dispatch` + `pull_request`.

### Corrigido (corretivos do prompt de QA)
- **BUG-001 — progressão incremental da Bronze presa em reextração.** A
  execução incremental avançava para o período seguinte ao watermark mesmo
  quando ele ainda não existia (mês/ano futuro): a fonte só era reextraída
  quando o novo período já "existia" (senão nada era produzido e o watermark
  nunca se consolidava). `pipeline/bronze.py` ganhou `_proximo_mes_competencia`
  e `_proximo_ano_competencia`: o período seguinte ao watermark é extraído
  **apenas se já existe** (≤ mês/ano da execução); caso contrário o período
  corrente é reextraído (republicação — a dedup por chave absorve).
  `run_pipeline(..., execution_timestamp)` para testes determinísticos.
  Regressão: `test_incremental_camara_avanca_mes_seguinte_ao_watermark`,
  `test_incremental_camara_reextrai_mes_corrente_quando_proximo_nao_existe`,
  `test_incremental_emendas_reextrai_ano_corrente_sem_ano_futuro`.
- **BUG-003 — Silver não idempotente por chave de negócio.** Re-execuções
  duplicavam registros (`cod_documento`-novo) ao invés de substituir.
  `pipeline/silver.py::escrever_validos_duckdb` virou **UPSERT por chave**:
  DELETE das linhas já consolidadas (`USING tmp_validos` na chave de negócio)
  seguido de INSERT — correções de registro refletem sem duplicar. Regressão:
  `test_reexecucao_mesma_chave_upsert_nao_duplica`,
  `test_correcao_de_registro_em_reexecucao_reflete`.
- **BUG-004 — Silver sem migração de schema legado.** Tabela criada por
  versão anterior (menos colunas) falhava/desalinhava o INSERT posicional.
  `pipeline/silver.py::_criar_tabela_se_necessario` agora adiciona as colunas
  novas do DataFrame via `ALTER TABLE ADD COLUMN` (tipo inferido pelo DuckDB)
  e todos os INSERTs (`escrever_validos_duckdb`, `escrever_quarentena_duckdb`,
  `escrever_dedup_removidas_duckdb`, `persistir_qualidade_report`) passaram a
  ser **por nome** (`_insert_por_nome`) — mapeamento campo-a-campo, nunca
  posicional. Regressão: `test_migracao_de_schema_em_tabela_legada` (contrato
  com banco de schema legado).
- **BUG-005 — `fontes_com_erro` tipada como string na API.** A Bronze grava a
  lista de fontes com erro como `LIST(VARCHAR)`; o schema `api/schemas/
  pipeline.py` declarava `str | None` (a API recebia a lista sem serializar) e
  o ramo vazio de `pipeline_runs.sql` usava `cast(null as varchar)`,
  incompatível com a lista do Parquet no MERGE incremental. Corrigido para
  `list[str] | None` e `cast(null as varchar[])`; seeds e asserções de
  `tests/api` atualizados (ex.: `["camara"]`, `["senado", "cgu_emenda"]`).
- **BUG-006 — limite do endpoint `GET /pipeline/status`.** O `limite` já está
  dentro do teto configurado (`Query(ge=1, le=config.limite_maximo)`),
  confirmado e coberto por `test_limite_de_execucoes`.

### Adicionado (ADR-033)
- **ADR-033 — pseudonimização de CPF movida da Gold (plugin UDF) para a
  Silver.** O plugin `pipeline/gold/hmac_udf.py` (UDF `hmac_sha256_cpf`
  registrada no `profiles.yml`) foi **removido**; o Gold agora apenas repassa
  o valor já hasheado pela Silver (`pipeline/pseudonymize.py`:
  `pseudonymize_cpf`/`pseudonymize_cpf_column`). CPF é hashado uma única vez
  na Silver com a chave de `EnvSettings.cpf_hmac_secret_key` (leitura
  preguiçosa — cargas CNPJ-only não exigem env); o Gold faz JOIN por igualdade
  (sem hash-de-hash, evita re-pseudonimização inconsistente). Seeds dos testes
  Gold carregam o hash, preservando as asserções de dimensão. O transform de
  estabelecimento (transparência) também passa a pseudonimizar CPF.
- **Condições de acesso ao Bronze registradas no ADR-033 (BUG-002):**
  acesso restrito **satisfeito** (MinIO apenas em `127.0.0.1:9000/9001`,
  rede interna `observatorio-net`, `no-new-privileges`) e **criptografia em
  repouso do MinIO NÃO implementada** — registrada como dívida consciente em
  item explícito do `BACKLOG.md` (Sprint 6.5).

### Movido
- **Módulos analíticos realocados de `pipeline/` para `analytics/`**
  (padrão canônico do `PROJECT_CONTEXT.md §6`, que já previa o pacote como
  destino dos módulos analíticos — scaffold morto agora povoado):
  - `pipeline/analytics.py` → `analytics/parliamentarians/analytics.py` (Onda 1)
  - `pipeline/risk.py` → `analytics/parliamentarians/risk.py` (Onda 4)
  - `pipeline/anomalies.py` → `analytics/anomalies/anomalies.py` (Onda 2)
  - `pipeline/network.py` → `analytics/network/network.py` (Onda 3)
  - `pipeline/features.py` → `analytics/features.py` (contrato Feature Store, ADR-028)
  - `git mv` (histórico preservado); imports internos (`risk`→`analytics.parliamentarians.analytics`, demais→`analytics.features`), docstrings e comentários ativos sincronizados (SQL do Gold, `sources.yml`, `schema.yml`, `feature_store/registry.yaml`, `pipeline/config.py`, `docs/architecture/arch_pipeline.md`). Registros históricos (ADR/BACKLOG/CHANGELOG) preservados.
- **Removida referência a `pipeline/pipeline.py`** (entrypoint inexistente) da árvore §6 — os entrypoints reais são o DAG (`pipeline/dags/pipeline_dag.py`) e `scripts/run_e2e_local.py`.
- **Árvore §6 atualizada**: `analytics/` documentado com a estrutura real; `pipeline/` sem os módulos analíticos; suíte **306 testes verdes** (230 pipeline + 58 API + 18 integração) após a realocação.

### Adicionado (fechamento Sprint 6.5)
- **`tests/pipeline/test_dag.py` — import-test do DAG com Airflow `DagBag`**
  (sem subir o scheduler): valida o parsing de `pipeline/dags/pipeline_dag.py`,
  a estrutura de dependências (ordem Bronze→Silver→Gold), a configuração do
  DAG (`@daily`, sem catchup, tags) e a integridade XCom (`executar_silver`
  consome o `run_id` de `executar_bronze`). O módulo é importado via
  `pytest.importorskip("airflow")` — o Airflow é optional-dependency (extra
  `pipeline`), então em dev local sem o extra o teste é pulado; em
  CI/containers com o extra instalado vira barreira real.
- **Fechamento da Sprint 6.5**: suíte completa **308 passed** (232 pipeline +
  58 API + 18 integração), sem regressões.

---

## Sprint 6 — API (FastAPI / Onda 4 — agent-ready ADR-032)

### Adicionado
- **Onda 4 — endpoints agent-ready RF-05** (`tests/api/test_agent.py`, 8 testes;
  selo 14→18; suíte 276→**288**): `/agent/parlamentar/{id}` (perfil vigente do
  SCD2 + métricas §8 `total_gasto`/`gasto_medio`/`num_transacoes`/
  `num_fornecedores`/`valor_maximo`/`valor_mediano`/`percentil_95` +
  `hhi_recente`/`hhi_periodo` de `supplier_concentration` + `risk_index` e 5
  scores do período mais recente de `risk_scores` + contagem/proporção de
  anomalias + top-5 fornecedores por valor),
  `/agent/fornecedor/{cnpj_cpf_valor}` (perfil `dim_fornecedor` + agregados
  `total_recebido`/`gasto_medio`/`valor_maximo`/`num_transacoes`/
  `num_parlamentares` + top-5 parlamentares; CPF só HMAC, ADR-011),
  `/agent/anomalias` (**resumo agregado**, não espelho paginado: total, por
  ano, por critério disparado e top-10 por zscore com nome do parlamentar) e
  `/agent/context` (**retrato sistêmico**, CU-07: métricas globais do Gold,
  períodos com dados, resumo do último `data_quality_report` e da última
  execução `pipeline_runs`). Schemas `api/schemas/agent.py`
  (`extra="forbid"`), 4 funções em `api/repo.py` (agregações SQL read-only
  sobre o Gold materializado — nenhuma métrica recalcula por request,
  ADR-030), router `api/routers/agent.py` (mesmo padrão `_erro_gold` →503,
  404 nominal).
- **ADR-032** (novo registro no `ADR.md`): agent-ready ≠ espelho dos
  endpoints de negócio — payloads **semânticos** que refletem a Camada
  Semântica §8 e os scores §9/ADR-027/028, na mesma fronteira read-only do
  ADR-026. **Decisão de escopo**: `taxa_ausencia`/`indice_alinhamento` ficam
  fora (dependem de `fact_presenca`/`fact_votacao`, ainda inexistentes);
  `hhi` vem de `supplier_concentration` (grão ano×parlamentar). Aprovado na
  revisão da Onda 4 (a `docs/architecture/ai_architecture.md` era stub só de
  rotas; §11 não definia contrato).
- **Selo de contrato estendido à Onda 4** (`tests/integration/
  test_api_gold_contrato.py`, 14→18): seed de `ml_staging.risk_scores`
  atravessa o model dbt até a Gold; `supplier_concentration` derivada do dbt
  a partir de `fact_despesa` (hhi ≈ 0.5556 em 2023); bind das colunas de
  risco/concentração/fato/dimensão no `top_fornecedores` com join
  `is_current` do SCD2.

---

## Sprint 6 — API (FastAPI / Onda 3 — anomalias, comunidades, qualidade e status)

### Adicionado
- **Onda 3 — os 4 endpoints restantes do §11** (`50d7ef8`):
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
  selo, `50d7ef8`): `control` configura `incremental` e a tabela Silver de mesmo
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
