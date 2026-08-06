# PROJECT_CONTEXT.md
# Plataforma de Inteligência Parlamentar Brasileira
 
> **Fonte da verdade do projeto. Nunca contradizer decisões registradas aqui sem criar um novo ADR.**
> Última atualização: Sprint 3 (Silver + Qualidade — normalização multi-fonte, Pandera, Data Quality Report; ADRs 013-016)
 
---
 
## 1. Visão do Produto
 
### Proposta de Valor
Plataforma open source de análise investigativa dos gastos parlamentares brasileiros, combinando engenharia de dados, estatística avançada, machine learning e análise de redes para revelar padrões de comportamento, concentração de fornecedores, anomalias estatísticas e redes de relacionamento entre parlamentares, partidos e empresas.
 
### O que este projeto NÃO é
- Não é um dashboard simples de BI
- Não é uma ferramenta de acusação ou julgamento
- Não substitui investigação jornalística — é insumo para ela
- Não utiliza dados privados ou obtidos de forma não oficial
 
---
### 1.1 Casos de Uso

| # | Ator | Caso de Uso | Resultado Esperado |
|---|---|---|---|
| CU-01 | Jornalista Investigativo | Buscar fornecedor por CNPJ e visualizar rede de parlamentares atendidos | Grafo de relacionamento + lista de parlamentares, valores e período |
| CU-02 | Jornalista Investigativo | Exportar histórico de despesas de um parlamentar em CSV/Excel | Arquivo com trilha de auditoria (run_id, fonte, timestamp) |
| CU-03 | Pesquisador Acadêmico | Consultar série histórica de gastos por partido/estado | Dados agregados por período, com metodologia de cálculo referenciada |
| CU-04 | Analista de Controle | Listar despesas classificadas como anomalia, ordenadas por score de risco | Lista priorizada com os 6 critérios de anomalia (§10) explicitados por item |
| CU-05 | Analista de Controle | Consultar `risk_index` composto de um parlamentar específico | Score final + decomposição nos 5 sub-scores (ADR-003) |
| CU-06 | Cidadão Engajado | Ver resumo simples de gastos de um parlamentar (linguagem acessível) | Card com total gasto, comparação com média da categoria, sem jargão técnico |
| CU-07 | Engenheiro de Dados (portfólio) | Consultar `/agent/context` para obter contexto semântico agregado | JSON estruturado, agent-ready, consumível por LLM |
| CU-08 | Pesquisador Acadêmico | Identificar comunidades de parlamentares com padrão de gasto semelhante | Clusters via NetworkX/KMeans, com parlamentares e métrica de similaridade |

---

### 1.2 Requisitos Funcionais

**RF-01** — O sistema deve ingerir dados das APIs Câmara, Senado e Portal da Transparência de forma incremental (watermark por `dataInicio`).
**RF-02** — O sistema deve permitir consulta de despesas por parlamentar, fornecedor, partido, estado e período.
**RF-03** — O sistema deve calcular e expor os 5 scores de risco e o `risk_index` composto (§9, ADR-003) para cada parlamentar.
**RF-04** — O sistema deve detectar anomalias de despesa segundo os 6 critérios formais (§10, ADR-002), exigindo ≥2 critérios simultâneos.
**RF-05** — O sistema deve expor endpoints REST documentados (OpenAPI/Swagger) para consumo por dashboard e agentes de IA (§11).
**RF-06** — O sistema deve pseudonimizar CPFs de fornecedores PF via HMAC-SHA256 antes de qualquer persistência (§17, ADR-004).
**RF-07** — O sistema deve gerar automaticamente Data Dictionary, diagramas Mermaid e relatório HTML ao final do pipeline.
**RF-08** — O sistema deve permitir exportação de dados em CSV, Excel e PDF a partir do dashboard.
**RF-09** — O sistema deve calcular índice de concentração de fornecedores (HHI) por parlamentar/partido/estado.
**RF-10** — O sistema deve identificar comunidades e métricas de centralidade na rede parlamentar-fornecedor via NetworkX.
**RF-11** — O sistema deve manter histórico rastreável de mudanças de partido/status de parlamentares (SCD Type 2 em `dim_parlamentar`).
**RF-12** — Toda execução do pipeline deve ser reprodutível via `run_id`, `pipeline_version`, `execution_timestamp` e `source_version`.

---

### 1.3 Requisitos Não Funcionais

| Categoria | Requisito |
|---|---|
| **Performance** | API deve responder em < 500ms (p95) para endpoints de consulta simples; < 2s para endpoints com agregação/rede |
| **Disponibilidade** | Pipeline diário via GitHub Actions com taxa de sucesso ≥ 95%; dashboard com disponibilidade best-effort (Streamlit Community Cloud, sem SLA formal) |
| **Escalabilidade** | Arquitetura deve suportar crescimento incremental de dados (10+ anos de histórico) sem reescrita de camadas Bronze/Silver |
| **Segurança/LGPD** | Nenhum dado pessoal sensível (CPF) em texto claro em qualquer camada (ADR-004); apenas dados públicos oficiais |
| **Observabilidade** | Logging estruturado (`structlog`) em todos os módulos; relatório de qualidade de dados gerado a cada execução |
| **Manutenibilidade** | Cobertura de testes ≥ 80% (Pytest); zero hardcode — configuração externa via `config/*.yaml`/`.env` |
| **Reprodutibilidade** | Qualquer execução anterior deve ser reproduzível a partir de `run_id` e `pipeline_version` |
| **Custo** | Infraestrutura de deploy deve operar em camada gratuita (Oracle Cloud Free Tier + Streamlit Community Cloud) |
| **Portabilidade** | Toda a stack deve rodar via Docker Compose, sem dependência de serviço cloud proprietário |

---

### 1.4 Critérios de Sucesso

**Critérios de encerramento da Sprint 0A:**
- [x] Visão, personas, casos de uso, RF e RNF documentados e aprovados
- [x] Escopo de v1 (MVP) explicitamente delimitado, com itens fora do escopo listados
- [x] Roadmap de 12 sprints validado (§13)
- [x] Nenhuma pendência crítica em aberto entre `PROJECT_CONTEXT.md`, `ADR.md`, `docs/governance/sprint_rules.md` e `docs/data/data_dictionary.md`

**Critérios de sucesso do produto (validados ao longo das sprints seguintes):**
- [ ] Um jornalista consegue, sem apoio técnico, encontrar um fornecedor suspeito e exportar evidências em < 5 minutos
- [ ] O `risk_index` prioriza corretamente pelo menos os casos de anomalia conhecidos publicamente (validação qualitativa)

> Nota: distintos dos "Critérios de Conclusão do Projeto" (§16), que são globais e avaliados apenas ao final do projeto.

---

### 1.5 Escopo da v1 (MVP)

**Dentro do escopo:**
- Fontes: Câmara, Senado, Portal da Transparência (CGU), Receita Federal (CNPJ), IBGE
- Pipeline completo Bronze → Silver → Gold
- API REST + endpoints agent-ready
- Dashboard Streamlit (páginas 01–10, ver §6)
- Detecção de anomalias, risk_index, análise de rede

**Fora do escopo (backlog futuro, pós-v1):**
- Cruzamento com dados eleitorais do TSE — fonte listada em §3, sem RF associado nesta versão
- CNAE como enriquecimento — fonte listada em §3, uso ainda não formalizado em RF
- Autenticação/autorização de usuários (acesso público, sem login)
- Alertas automáticos/notificações proativas de anomalias
- Versionamento multi-tenant ou multi-instância do dashboard

## 2. Personas
 
| Persona | Perfil | Necessidade Principal |
|---|---|---|
| **Jornalista Investigativo** | Repórter de dados, veículos como Agência Pública, The Intercept | Dados brutos exportáveis, trilha de auditoria, drill-down por fornecedor/parlamentar |
| **Pesquisador Acadêmico** | Cientista político, economista, sociólogo | Séries históricas, correlações, exportação para R/Python, metodologia documentada |
| **Cidadão Engajado** | Eleitor com interesse em transparência | Número simples, frase explicativa, comparação com médias, linguagem acessível |
| **Analista de Controle** | TCU, CGU, Ministério Público | Score de risco, anomalias priorizadas, rastreabilidade de decisões analíticas |
| **Engenheiro de Dados (portfólio)** | Profissional avaliando arquitetura | Código limpo, documentação técnica, reprodutibilidade, testes |
 
---
 
## 3. Fontes de Dados
 
| Fonte | Tipo | Confiabilidade | Notas |
|---|---|---|---|
| API Câmara dos Deputados (`dadosabertos.camara.leg.br`) | API REST | Alta | Dados desde 2015; rate limit ~100 req/min não documentado |
| API Senado Federal | API REST | Alta | Schema menos consistente que a Câmara |
| Portal da Transparência (CGU) | API + CSV | Alta | Dados históricos via CSV antes de 2015 |
| TSE — Dados Abertos | CSV | Alta | Útil para cruzamento eleitoral |
| Receita Federal — CNPJ Público | CSV bulk | Alta | Atualizado mensalmente; ~10GB comprimido |
| IBGE — Municípios e Estados | API + CSV | Alta | Para enriquecimento geográfico |
| CNAE Público | CSV | Alta | Para classificação de fornecedores |
 
### Estratégia de Ingestão
- **API disponível:** consumo incremental via watermark por `dataInicio`
- **Sem API:** download automático de arquivos públicos
- **Dados históricos (pré-2015):** pipeline separado de limpeza de CSV
- **Nunca:** dados privados, scraping sem autorização, dados pessoais não públicos
 
---
 
## 4. Stack Tecnológica
 
| Componente | Tecnologia | Versão | Justificativa |
|---|---|---|---|---|
| Orquestração | Apache Airflow | 2.9.3 | DAGs versionadas, retry nativo, observabilidade |
| Storage Raw | Parquet + MinIO | RELEASE.2025-09-07 | Open source, compatível com Delta Lake |
| Banco Analítico | DuckDB | 1.0+ | Serverless, OLAP embarcado, integração nativa com Parquet |
| Transformações | dbt Core | 1.7+ | Versionamento SQL, lineage, testes nativos (RF-07) |
| Qualidade | Pandera | 0.18+ | Data contracts, validação de schema em runtime |
| API | FastAPI | 0.110+ | Alta performance, OpenAPI automático, agent-ready |
| Dashboard | Streamlit | 1.35+ | Camada de apresentação exclusivamente |
| ML | scikit-learn | 1.4+ | Isolation Forest, DBSCAN, KMeans, PCA |
| Grafos | NetworkX | 3.2+ | Análise de redes; exportação para Gephi |
| Testes | Pytest | 8.0+ | Cobertura mínima 80% |
| CI/CD | GitHub Actions | — | Deploy automatizado diário |
| Containerização | Docker + Docker Compose | latest | Ambiente reproduzível |
| Linguagem | Python | 3.11 | Type hints, performance, ecossistema |
| **CLI HTTP** | **httpx** | 0.27+ | Chamadas às APIs externas (Câmara, Senado, CGU) |
| **Logging** | **structlog** | 24.1+ | Logging estruturado em todos os módulos |
| **Retry** | **tenacity** | 8.2+ | Exponential backoff em operações de rede |
| **Config** | **PyYAML + pydantic-settings** | 6.0+ / 2.0+ | Config externa via YAML + .env, zero hardcode |
| **Validação** | **Pydantic** | 2.0+ | Schemas de dados e settings |
| **Manipulação** | **Pandas + NumPy** | 2.0+ / 1.24+ | Transformações e análise exploratória |
| **Client MinIO** | **minio** | 7.2+ | SDK Python para object storage |
| **Adapter dbt** | **dbt-duckdb** | 1.7+ | Conector dbt ↔ DuckDB |
| **Server ASGI** | **uvicorn** | 0.29+ | Servidor ASGI para FastAPI |
| **Env loader** | **python-dotenv** | 1.0+ | Carregamento de `.env` |
| **Cobertura** | **pytest-cov** | 4.0+ | Relatório de cobertura de testes |
| **Banco auxiliar** | **PostgreSQL** | 16-alpine | Metadados do Airflow |
 
### Infraestrutura de Deploy (gratuita)
- **Compute:** Oracle Cloud Always Free Tier — instância `VM.Standard.A1.Flex`
  (Ampere A1, ARM), **2 OCPUs / 12GB RAM**, região `sa-saopaulo-1`
- **Nota de reconciliação (Sprint 0B):** a Oracle reduziu a alocação
  Always Free do shape Ampere A1 de 4 OCPUs/24GB para 2 OCPUs/12GB
  em meados de 2026, sem anúncio formal — mudança externa à
  plataforma, não a uma decisão do projeto. A infraestrutura foi
  provisionada já dentro do novo limite vigente, mantendo o
  requisito de custo R$0/mês (RNF de custo, §1.3)
- **Compartment dedicado:** `observatorio-parlamentar`
- **Rede:** VCN + subnet pública dedicadas, Security List restrita
  (porta 22 liberada apenas para IP de administração; 80/443
  liberadas para acesso público futuro da API/dashboard)
- **Hardening aplicado:** autenticação SSH somente por chave
  (login root e autenticação por senha desabilitados); firewall
  local (`ufw`) replicando a mesma restrição de porta 22 da
  Security List (defesa em profundidade)
- **Dashboard público:** Streamlit Community Cloud
- **Repositório:** GitHub (público)
- **Secrets:** GitHub Secrets + `.env` local
- **Custo estimado:** R$ 0/mês

## 5. Arquitetura — Visão Geral
 
> Diagramas e documentos de arquitetura em `docs/architecture/`: `arch_medalhao.md`, `arch_deploy.md`, `arch_pipeline.md`, `ai_architecture.md` (agentes) e `ddd.md` (organização por domínio).

```
Fontes Externas (APIs + CSVs)
        │
        ▼
┌─────────────────────────────────────────────────┐
│  INGESTION (Airflow DAGs)                       │
│  Retry automático, rate limiting, watermark     │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│  BRONZE (Parquet + MinIO)                       │
│  Raw exato, metadados, hash, particionado       │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│  SILVER (DuckDB)                                │
│  Limpeza, normalização, deduplicação, Pandera   │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│  GOLD (DuckDB)                                  │
│  Star Schema, tabelas analíticas, scores        │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│  SEMANTIC LAYER                                 │
│  Métricas padronizadas e reutilizáveis          │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌──────────────────────┐
│  FastAPI             │  ← Camada de serviço
│  REST + Agent-Ready  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Streamlit           │  ← Apresentação apenas
│  Dashboard           │
└──────────────────────┘
```
 
---
 
## 6. Estrutura de Diretórios

```
observatorio-parlamentar/
├── .github/
│   └── workflows/
│       └── pipeline.yml              # CI/CD (placeholder, Sprint 9)
├── api/                              # FastAPI (scaffold, Sprint 6)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── parlamentares.py          # ┐
│   │   ├── fornecedores.py           # │ Sprint 6
│   │   ├── anomalias.py              # │
│   │   ├── rede.py                   # │
│   │   └── agent.py                  # ┘
│   ├── schemas/
│   │   └── __init__.py
│   ├── __init__.py
│   ├── Dockerfile
│   ├── dependencies.py               # Sprint 6
│   └── main.py
├── pipeline/                         # ETL (Sprint 3 parcial — Bronze concluído; Silver em andamento; Gold, 4)
│   ├── camara/
│   │   ├── __init__.py
│   │   ├── extract.py                # Sprint 2
│   │   ├── schemas.py                # Sprint 1
│   │   └── transform.py              # Sprint 3
│   ├── senado/
│   │   ├── __init__.py
│   │   ├── extract.py                # Sprint 2
│   │   ├── schemas.py                # Sprint 1
│   │   └── transform.py              # Sprint 3
│   ├── transparencia/
│   │   ├── __init__.py
│   │   ├── extract.py                # Sprint 2
│   │   ├── schemas.py                # Sprint 1
│   │   └── transform.py              # Sprint 3
│   ├── dags/
│   │   └── pipeline_dag.py
│   ├── __init__.py
│   ├── Dockerfile
│   ├── contracts.py                  # Sprint 1
│   ├── bronze.py                     # Sprint 2
│   ├── watermark.py                  # Sprint 2
│   ├── storage.py                    # Sprint 2
│   ├── runs.py                       # Sprint 2
│   ├── utils.py
│   ├── config.py
│   ├── normalize.py                  # Sprint 3
│   ├── silver.py                     # Sprint 3
│   ├── gold.py                       # Sprint 4
│   ├── quality.py                    # Sprint 3
│   ├── analytics.py                  # Sprint 5
│   ├── network.py                    # Sprint 5
│   ├── features.py                   # Sprint 5
│   └── pipeline.py                   # Entrypoint principal
├── analytics/                        # Módulos analíticos (scaffold, Sprint 5)
│   ├── suppliers/
│   │   └── __init__.py
│   ├── parliamentarians/
│   │   └── __init__.py
│   ├── anomalies/
│   │   └── __init__.py
│   └── network/
│       └── __init__.py
├── dashboard/                        # Streamlit (scaffold, Sprint 7)
│   ├── pages/
│   │   ├── .gitkeep
│   │   ├── 01_visao_geral.py        # ┐
│   │   ├── 02_parlamentar.py        # │
│   │   ├── 03_partido.py            # │
│   │   ├── 04_estado.py             # │ Sprint 7
│   │   ├── 05_fornecedor.py         # │
│   │   ├── 06_rede.py               # │
│   │   ├── 07_anomalias.py          # │
│   │   ├── 08_ml.py                 # │
│   │   ├── 09_qualidade.py          # │
│   │   └── 10_metadados.py          # ┘
│   ├── __init__.py
│   ├── Dockerfile
│   └── app.py
├── config/                           # Configuração externa (zero hardcode)
│   ├── sources.yaml
│   ├── pipeline.yaml
│   ├── analytics.yaml
│   └── dashboard.yaml
├── data/                             # Dados persistidos (Docker volumes)
│   ├── bronze/                       # Parquet raw
│   │   └── .gitkeep
│   ├── silver/                       # DuckDB trusted
│   │   └── .gitkeep
│   └── gold/                         # DuckDB warehouse
│       └── .gitkeep
├── feature_store/                    # Features para ML
│   └── registry.yaml
├── tests/                            # Testes (scaffold, Sprint 8)
│   ├── unit/
│   │   └── __init__.py
│   ├── integration/
│   │   └── __init__.py
│   ├── pipeline/
│   │   └── __init__.py
│   ├── api/
│   │   └── __init__.py
│   └── __init__.py
├── docs/
│   ├── architecture/
│   │   ├── ai_architecture.md
│   │   ├── arch_deploy.md
│   │   ├── arch_medalhao.md
│   │   ├── arch_pipeline.md
│   │   └── ddd.md
│   ├── data/
│   │   ├── data_dictionary.md
│   │   ├── ml_feature.md
│   │   ├── risk_level.md
│   │   └── semantic_layer.md
│   ├── engineering/
│   │   ├── documentation.md
│   │   ├── external_config.md
│   │   ├── tests.md
│   │   └── versionamento.md
│   ├── governance/
│   │   ├── sprint_rules.md
│   │   └── system_prompt.md
│   └── guia_provisionamento_oci.md
├── infra/                            # Provisionamento de infraestrutura
│   └── cloud-config.yaml             # Cloud-init Oracle Cloud (Docker + UFW + SSH)
├── nginx/                            # Reverse proxy
│   ├── default.conf
│   └── Dockerfile
├── scripts/                          # Scripts auxiliares
│   ├── deploy.ps1
│   └── deploy.sh
├── notes/                            # Anotações pessoais (não versionar)
│   ├── anotações_projeto.md
│   └── teste.ipynb
├── logs/                             # Logs de execução (ignorados pelo git)
├── .agents/
├── .dockerignore
├── .env.example                      # Template de variáveis de ambiente
├── .gitignore
├── ADR.md                            # Architecture Decision Records
├── BACKLOG.md                        # Backlog vivo
├── LICENSE
├── PROJECT_CONTEXT.md                # Este arquivo
├── README.md
├── docker-compose.yml
├── opencode.json
└── pyproject.toml                    # Dependências e configuração do projeto
```
 
---
 
## 7. Modelo Dimensional — Gold Layer

> **Modelo de constelação de fatos (fact constellation / galaxy
> schema)** — ADR-012. Três domínios de negócio distintos
> (`fact_despesa`, `fact_emenda`, `fact_cartao_cpgf`) compartilham
> dimensões corporativas, cada um preservando grão analítico
> próprio. Ver `docs/architecture/arch_er.md` para o diagrama
> completo.

### Dimensões

| Tabela | Descrição | Chave Natural |
|---|---|---|
| `dim_parlamentar` | Deputados e senadores (SCD Type 2) | `id_parlamentar` |
| `dim_fornecedor` | Empresas e pessoas físicas fornecedoras | `cnpj_cpf_valor` + `tipo_documento` (ADR-011) |
| `dim_orgao` | Órgãos institucionais — Câmara, Senado, Ministérios (ADR-010) | `sigla` |
| `dim_unidade_gestora` | Unidades gestoras/orçamentárias — SIAFI, CGU, Tesouro (ADR-010) | (`fonte_origem`, `codigo`) |
| `dim_partido` | Partidos políticos com ideologia | `sigla` |
| `dim_estado` | UFs com dados geográficos IBGE | `uf` |
| `dim_municipio` | Municípios com código IBGE | `cod_ibge` |
| `dim_categoria_despesa` | Tipos de despesa CEAP | `cod_tipo` |
| `dim_data` | Calendário completo com flags | `data_sk` (YYYYMMDD) |

### Dimensão Institucional — `dim_orgao` e `dim_unidade_gestora` (ADR-010)

`dim_orgao` representa exclusivamente entidades institucionais
(Câmara, Senado, Ministérios etc.). `dim_unidade_gestora` representa
exclusivamente entidades administrativas/orçamentárias, ligada a
`dim_orgao` por FK. Nenhuma dimensão acumula os dois conceitos.

`dim_unidade_gestora` é genérica desde a concepção — o campo
`fonte_origem` (`SIAFI` | `CGU` | `Tesouro Nacional` | `outro`)
evita acoplamento a um único sistema de origem. Chave natural
composta (`fonte_origem`, `codigo`), nunca `codigo` isolado.

**Estado na v1:** `dim_orgao` populada normalmente (mínimo: Câmara
dos Deputados e Senado Federal, com UG/Gestão SIAFI quando
disponível — Senado: UG `020001`, Gestão `00001`). `dim_unidade_gestora`
existe apenas como schema — tabela vazia até existir requisito
funcional que justifique análise nesse nível de granularidade.

### Dimensão `dim_fornecedor` — schema revisado (ADR-011)

| Campo | Descrição |
|---|---|
| `cnpj_cpf_valor` | CNPJ em claro (14 dígitos) OU hash HMAC-SHA256 do CPF (11 dígitos) OU `NULL` se origem vazia |
| `tipo_documento` | `CNPJ` \| `CPF` \| `INVALIDO` \| `NULL` |

String vazia/nula nunca é hasheada — permanece `NULL`, evitando
identidade de fornecedor fantasma. Substitui a antiga chave natural
`cnpj_cpf_hash` (nome descontinuado — sugeria hash universal, o que
deixou de ser verdade após ADR-011).

### Colunas de Auditoria SCD Type 2 (`dim_parlamentar`)

Toda dimensão SCD2 deve conter explicitamente:

| Coluna | Tipo | Descrição |
|---|---|---|
| `effective_date` | DATE | Data de início de vigência do registro |
| `end_date` | DATE (nullable) | Data de fim de vigência; NULL se registro vigente |
| `is_current` | BOOLEAN | Flag do registro vigente atual |
| `surrogate_key` | BIGINT | Chave técnica interna, gerada por versão do registro |

Sem essas colunas explícitas, o histórico de mudanças (ex: troca de
partido de um parlamentar) não é rastreável de forma confiável.

### Fatos (ADR-012 — modelo de constelação)

> Cada tabela fato representa um único evento de negócio e um único
> grão analítico. Fontes distintas originam fatos distintas; as
> dimensões corporativas (`dim_data`, `dim_orgao`,
> `dim_unidade_gestora`) são compartilhadas entre todas elas.

| Tabela | Grão | Métricas Principais | Fontes |
|---|---|---|---|
| `fact_despesa` | 1 linha por despesa parlamentar | `valor_liquido`, `valor_glosa` | Câmara, Senado |
| `fact_emenda` | 1 linha por emenda parlamentar | `valor_empenhado`, `valor_liquidado`, `valor_pago` | CGU |
| `fact_cartao_cpgf` | 1 linha por transação de cartão corporativo | `valor_transacao` | CGU |
| `fact_presenca` | 1 linha por parlamentar/sessão | `resultado`, `is_ausencia_injustificada` | Câmara |
| `fact_votacao` | 1 linha por parlamentar/votação | `voto`, `seguiu_partido` | Câmara |
| `fact_gastos_mensais` | Agregado mensal por parlamentar | `total_gasto`, `num_fornecedores` | derivado |

**FKs institucionais e regras de nullability (ADR-010, ADR-012):**

| Tabela | `id_orgao` | `id_unidade_gestora` | `id_parlamentar` | `id_fornecedor` |
|---|---|---|---|---|
| `fact_despesa` | NOT NULL | nullable — inativo v1, fonte não fornece | NOT NULL | NOT NULL |
| `fact_emenda` | NOT NULL | nullable | **NOT NULL** — identidade do evento | — (não aplicável ao grão) |
| `fact_cartao_cpgf` | NOT NULL | **NOT NULL** — CGU sempre fornece `unidadeGestora.codigo` | **não referenciada** — ver nota | nullable — via CNPJ do estabelecimento |

> **Nota — `fact_cartao_cpgf` e `dim_parlamentar` (ADR-012):**
> `fact_cartao_cpgf` não referencia `dim_parlamentar` na versão
> inicial da arquitetura. O portador de um cartão CPGF pertence
> estruturalmente ao Poder Executivo — um portador eventualmente
> identificável como parlamentar é coincidência de dados, não
> relação de domínio, e não justifica FK opcional. Caso um
> requisito futuro exija esse cruzamento, a associação deve ser
> implementada via tabela bridge (ex: `bridge_cartao_parlamentar`),
> preservando o grão original da fato.

> **Nota — nullable não é regra universal:** a nullability de
> `id_unidade_gestora` depende exclusivamente da disponibilidade da
> informação na fonte, não de um princípio arquitetural único. Em
> `fact_despesa` é nullable porque Câmara/Senado ainda não fornecem
> essa informação; em `fact_cartao_cpgf` é NOT NULL porque a CGU já
> entrega `unidadeGestora.codigo` nativamente.

### Metadados de Reprodutibilidade (RF-12)

Toda fato carrega `run_id`, `pipeline_version`, `execution_timestamp`
e `source_version`. Estratégia completa de watermark por fonte e
reprodutibilidade documentada em `docs/engineering/versionamento.md`.

### Tabelas Analíticas (Gold)

| Tabela | Propósito |
|---|---|
| `supplier_concentration` | Índice HHI por fornecedor/parlamentar |
| `politician_similarity` | Score de similaridade entre parlamentares |
| `expense_outliers` | Anomalias detectadas por Isolation Forest |
| `supplier_growth` | Crescimento de receita pública por fornecedor |
| `network_edges` | Arestas do grafo parlamentar-fornecedor |
| `network_nodes` | Nós com métricas de centralidade |
| `risk_scores` | Score composto de risco por parlamentar |

---
 
## 8. Camada Semântica — Métricas Padronizadas
 
Todas as visualizações devem consumir essas definições. Nunca recalcular inline.
 
| Métrica | Fórmula | Fonte |
|---|---|---|
| `total_gasto` | `SUM(valor_liquido)` | `fact_despesa` |
| `gasto_medio` | `AVG(valor_liquido)` | `fact_despesa` |
| `num_fornecedores` | `COUNT(DISTINCT fornecedor_sk)` | `fact_despesa` |
| `ticket_medio` | `total_gasto / num_transacoes` | calculado |
| `valor_maximo` | `MAX(valor_liquido)` | `fact_despesa` |
| `valor_mediano` | `PERCENTILE_CONT(0.5)` | `fact_despesa` |
| `percentil_95` | `PERCENTILE_CONT(0.95)` | `fact_despesa` |
| `participacao_no_total` | `valor_liquido / SUM(valor_liquido) OVER (partição)` | calculado |
| `hhi` | `SUM(participacao^2)` | `supplier_concentration` |
| `taxa_ausencia` | `faltas_injustificadas / total_sessoes` | `fact_presenca` |
| `indice_alinhamento` | `votos_com_partido / total_votos` | `fact_votacao` |
| `risk_index` | média ponderada normalizada dos 5 scores de risco (ver §9, ADR-003) | `risk_scores` |
 
> **Nota de reconciliação:** `valor_maximo`, `valor_mediano` e
> `participacao_no_total` foram incorporados a esta tabela para
> eliminar a divergência anteriormente existente entre este documento
> e o artefato `docs/data/semantic_layer.md`. Esta tabela agora é a única fonte
> oficial de métricas — `docs/data/semantic_layer.md` deve ser tratado como
> histórico/rascunho, não como referência ativa.
 
---
 
## 9. Índices de Risco
 
Cada índice deve ser documentado matematicamente no `ADR.md`.
 
| Índice | Descrição |
|---|---|
| `supplier_concentration_score` | Concentração de gastos em poucos fornecedores |
| `political_exposure_score` | Exposição a fornecedores compartilhados com muitos parlamentares |
| `supplier_dependency_score` | Dependência do fornecedor em relação a poucos parlamentares |
| `expense_anomaly_score` | Z-score normalizado das despesas individuais |
| `network_influence_score` | PageRank no grafo parlamentar-fornecedor |
| `risk_index` | Média ponderada normalizada dos 5 scores acima (ver ADR-003) |
 
### Fórmula do Risk Index (ADR-003 — Aceito)
 
Todos os scores individuais são normalizados via Min-Max para o
intervalo [0,1] antes da ponderação. Pesos uniformes (0.2 cada) são
o baseline da Sprint 0B — não definitivos, sujeitos a revisão na
Sprint 5 com base em validação empírica.
 
```
risk_index = 0.2 * norm(supplier_concentration_score)
           + 0.2 * norm(political_exposure_score)
           + 0.2 * norm(supplier_dependency_score)
           + 0.2 * norm(expense_anomaly_score)
           + 0.2 * norm(network_influence_score)
```
 
A função de normalização Min-Max deve estar documentada na
Feature Store (`docs/data/ml_feature.md`) como feature derivada reutilizável.
 
---
 
## 10. Definição Formal de Anomalia
 
> **Decisão crítica — não alterar sem novo ADR.**
 
Uma despesa é considerada **anomalia estatística** quando satisfaz **pelo menos dois** dos critérios abaixo:
 
| Critério | Threshold |
|---|---|
| Z-score do valor vs histórico do parlamentar | > 2.5 |
| Isolation Forest score | < -0.1 (contaminação = 0.05) |
| Fornecedor com < 3 clientes parlamentares distintos | — |
| Empresa aberta há < 12 meses na data da despesa | — |
| Despesas com valor idêntico em ≥ 3 ocorrências no mês | — |
| Despesa em dia sem sessão parlamentar (feriado/fim de semana) | — |
 
> **Nota (ADR-002 — Aceito):** `contamination=0.05` é hiperparâmetro
> de treino do Isolation Forest; o threshold de score (`< -0.1`) é
> regra de decisão aplicada em inferência. Os dois não são
> redundantes — atuam em momentos distintos do ciclo de vida do
> modelo. Distinção detalhada em `docs/data/data_dictionary.md`.
 
---
 
## 11. Endpoints FastAPI
 
### Endpoints de Negócio
```
GET  /parlamentares                    # lista com filtros
GET  /parlamentares/{id}               # perfil completo
GET  /parlamentares/{id}/gastos        # histórico de despesas
GET  /parlamentares/{id}/rede          # rede de fornecedores
GET  /fornecedores                     # lista com filtros
GET  /fornecedores/{cnpj}              # perfil completo
GET  /fornecedores/{cnpj}/parlamentares
GET  /anomalias?threshold=2.5
GET  /rede/comunidades
GET  /qualidade/relatorio
GET  /pipeline/status
```
 
### Endpoints Agent-Ready (JSON semântico para LLMs)
```
GET  /agent/parlamentar/{id}
GET  /agent/fornecedor/{cnpj}
GET  /agent/anomalias
GET  /agent/context
```
 
---
 
## 12. Papéis de Desenvolvimento
 
| Papel | Responsabilidade | Sprints Principais |
|---|---|---|
| **Arquiteto** | Define arquitetura, ADRs, stack e decisões técnicas | 0A, 0B, 1 |
| **Engenheiro de Dados** | ETL, modelo medalhão, qualidade | 2, 3, 4, 6.5 |
| **Cientista de Dados** | Estatística, ML, análise de redes | 5 |
| **Engenheiro Backend** | FastAPI, contratos de API, integração com dashboard | 6, 7 |
| **Engenheiro de QA** | Testes, validação de contratos, cobertura | 8 |
| **Revisor Técnico** | Code review, inconsistências, melhorias | toda sprint, com ênfase em 6.5 |
| **Documentador** | README, PROJECT_CONTEXT.md, diagramas | toda sprint, com ênfase em 9 |
 
---
 
## 13. Roadmap de Sprints
 
| Sprint | Nome | Output Principal | Status |
|---|---|---|---|
| **0A** | Descoberta | Visão, personas, casos de uso, escopo | ✅ Concluída |
| **0B** | Arquitetura | Stack, diretórios, diagramas, convenções | ✅ Concluída |
| **1** | Modelagem | Schema completo + contratos de dados | ⏳ Pendente |
| **2** | Bronze + Extração | Pipeline de ingestão funcionando | ⏳ Pendente |
| **3** | Silver + Qualidade | Dados limpos + relatório Pandera | ⏳ Pendente |
| **4** | Gold Layer | Star schema populado | ⏳ Pendente |
| **5** | Analytics + ML + Redes | Tabelas analíticas + scores de risco | ⏳ Pendente |
| **6** | FastAPI | API documentada e testada | ⏳ Pendente |
| **6.5** | Validação Real | Pipeline end-to-end com dados reais | ⏳ Pendente |
| **7** | Dashboard | Streamlit funcional | ⏳ Pendente |
| **8** | Testes | Cobertura ≥ 80% | ⏳ Pendente |
| **9** | Deploy + Docs | GitHub Actions + README completo | ⏳ Pendente |
 
> Roadmap reconciliado com `docs/governance/sprint_rules.md` — ambos os documentos
> agora concordam em 12 sprints, sem fusão entre Testes (8) e
> Deploy+Docs (9).
 
---
 
## 14. Convenções de Nomenclatura
 
| Elemento | Convenção | Exemplo |
|---|---|---|
| Tabelas Bronze | `bronze_{fonte}_{entidade}` | `bronze_camara_despesas` |
| Tabelas Silver | `silver_{entidade}` | `silver_parlamentar` |
| Tabelas Fato | `fact_{entidade}` | `fact_despesa` |
| Tabelas Dimensão | `dim_{entidade}` | `dim_fornecedor` |
| Tabelas Analíticas | `{descricao}` | `supplier_concentration` |
| Funções Python | `snake_case` | `load_bronze_despesas()` |
| Classes Python | `PascalCase` | `DespesaExtractor` |
| Variáveis | `snake_case` | `total_gasto` |
| Constantes | `UPPER_SNAKE_CASE` | `MAX_RETRY_ATTEMPTS` |
| Arquivos Python | `snake_case.py` | `extract.py` |
| Branches Git | `sprint/{numero}-{descricao}` | `sprint/2-bronze-extract` |

**Ciclo de vida de branches:**

- **Permanentes:** `main` (estável/produção) e `develop` (integração).
- **Temporárias:** branches de sprint (`sprint/{numero}-{descricao}`) são
  criadas no início de cada sprint para isolar o trabalho em andamento e são
  **deletadas após o merge em `develop`** com aprovação (ciclo da sprint,
  `sprint_rules.md`). Não acumular branches fechadas — o histórico permanece
  no `git log`. Exceções só com justificativa registrada em ADR.
 
---
 
## 15. Padrões de Código
 
- **PEP8** obrigatório
- **Type Hints** em todas as funções
- **Docstrings e comentários em português brasileiro** — variáveis,
  funções, classes e nomes de arquivos permanecem em inglês
  (decisão Sprint 1, refina a convenção original "código sempre em
  inglês"). Estrutura de docstring segue padrão Google Style,
  apenas traduzida.
- **Logging estruturado** em todos os módulos (`structlog`)
- **Configuração externa** via `config/*.yaml` e `.env` — zero hardcode
- **Retry automático** com `tenacity` (exponential backoff)
- **Tratamento de erros** explícito — nunca `except: pass`
 
---
 
## 16. Critérios de Conclusão do Projeto
 
> Volume de código não é critério. Qualidade é.
 
- [ ] Todas as funcionalidades do PRD implementadas
- [ ] Cobertura de testes ≥ 80%
- [ ] Pipeline reproduzível ponta a ponta
- [ ] Documentação suficiente para terceiro executar o projeto
- [ ] CI/CD funcionando com execução diária
- [ ] Código aderente às convenções definidas neste documento
- [ ] Todas as fontes de dados documentadas com confiabilidade
- [ ] Definição de anomalia documentada e implementada consistentemente
 
---
 
## 17. Restrições e Compliance
 
### LGPD
- CPFs de fornecedores PF: **HMAC-SHA256 com chave secreta**,
  gerenciada via GitHub Secrets / `.env` — nunca hardcoded no código
  ou em arquivos versionados (ver ADR-004). Salt fixo foi
  descontinuado por vulnerabilidade a ataque de força
  bruta/rainbow table, dado que o espaço de CPFs válidos é finito
  e computável.
- Nenhum CPF em texto claro é persistido em qualquer camada,
  incluindo Bronze — hash aplicado no momento da extração.
- Chave HMAC deve ter plano de rotação documentado (ex: anual), com
  re-hash de dados históricos quando a chave for rotacionada.
- Dados pessoais de terceiros não públicos: mascarar.
- Base legal: interesse público / transparência (Art. 7º, III, LGPD)
- README deve conter seção explícita de privacidade, incluindo a
  estratégia de pseudonimização adotada.
 
### Dados
- Nunca utilizar dados privados
- Nunca fazer scraping sem autorização explícita
- Documentar versão e data de cada fonte consumida
 
---
 
*Este documento é atualizado ao final de cada sprint pelo papel de Documentador.*
*Versão atual: 1.2 — Sprint 3 em andamento (normalização multi-fonte, validação Pandera e Data Quality Report; ADRs 001-016)*
