# ADR.md
ADR-001
Título: Utilização de DuckDB como camada Silver e Gold
 
Status:
Aceito
 
Contexto:
Necessidade de banco analítico embarcado.
 
Decisão:
DuckDB será utilizado...
 
Consequências:
- Sem necessidade de servidor.
- Excelente desempenho analítico.
- Fácil integração com Parquet.
 
---
 
ADR-002
Título: Critérios de detecção de anomalia estatística em despesas
 
Status:
Aceito
 
Contexto:
PROJECT_CONTEXT.md §10 já define 6 critérios (Z-score > 2.5,
Isolation Forest score < -0.1, fornecedor com <3 clientes, empresa
nova, valores idênticos repetidos, despesa em dia sem sessão),
exigindo ≥2 critérios simultâneos. Faltava formalizar por que
contamination=0.05 e threshold de score (-0.1) coexistem no
Isolation Forest sem serem redundantes.
 
Decisão:
Manter os 6 critérios como definidos em PROJECT_CONTEXT.md §10.
contamination=0.05 é hiperparâmetro de treino (calibra a proporção
esperada de outliers no dataset de treino). O threshold de score
(-0.1) é regra de decisão aplicada em inferência sobre novas
despesas, sem necessidade de retreinar o modelo. Os dois parâmetros
atuam em momentos distintos do ciclo de vida do modelo e não são
redundantes.
 
Consequências:
- Nenhuma mudança de comportamento nos critérios existentes.
- O parâmetro de contaminação não deve ser reajustado sem novo ADR,
  pois isso alteraria implicitamente a calibração do threshold.
- Documentar essa distinção em `docs/data/data_dictionary.md`.
 
---
 
ADR-003
Título: Fórmula do Risk Index composto
 
Status:
Aceito
 
Contexto:
PROJECT_CONTEXT.md §8 e §9 referenciam "risk_index" como média
ponderada de 5 scores, mas os pesos nunca haviam sido definidos.
 
Decisão:
Pesos uniformes (0.2 cada) como baseline da Sprint 0B, com
normalização Min-Max de cada score para [0,1] antes da ponderação:
 
risk_index = 0.2 * norm(supplier_concentration_score)
           + 0.2 * norm(political_exposure_score)
           + 0.2 * norm(supplier_dependency_score)
           + 0.2 * norm(expense_anomaly_score)
           + 0.2 * norm(network_influence_score)
 
Pesos definitivos serão revisados na Sprint 5 com base em validação
empírica e/ou feedback da persona Analista de Controle.
 
Consequências:
- risk_index calculável desde já, sem bloquear a Sprint 5.
- Pesos uniformes são baseline explícito, não definitivo.
- Exige função de normalização documentada na Feature Store.
 
---
 
ADR-004
Título: Estratégia de pseudonimização de CPF de fornecedores PF
 
Status:
Aceito — substitui a redação de PROJECT_CONTEXT.md §17
 
Contexto:
PROJECT_CONTEXT.md §17 definia "hash SHA-256 com salt fixo" para
CPFs de fornecedores PF. Salt fixo reutilizado em todos os registros
é vulnerável a força bruta/rainbow table, dado que o espaço de CPFs
válidos é finito e computável.
 
Decisão:
Adotar HMAC-SHA256 com chave secreta (gerenciada via GitHub Secrets
/ .env, nunca hardcoded), em substituição ao salt fixo. Nenhum CPF em
texto claro é persistido em qualquer camada, incluindo Bronze — hash
aplicado no momento da extração.
 
Consequências:
- Requer atualização de PROJECT_CONTEXT.md §17.
- Requer plano de rotação de chave (ex: anual) com re-hash de dados
  históricos quando a chave for rotacionada.
- Requer gestão adequada de secret (fora do repositório, fora do
  Parquet/DuckDB).
- Join determinístico entre fornecedor PF e despesas continua
  possível, pois HMAC com a mesma chave é determinístico.

---

ADR-005
Título: Organização da documentação e dos artefatos de governança

Status:
Aceito

Contexto:
Os artefatos de referência e documentos auxiliares estavam todos na
raiz do repositório, reduzindo a legibilidade da estrutura inicial.

Decisão:
Manter na raiz apenas `README.md`, `PROJECT_CONTEXT.md`, `ADR.md`,
`BACKLOG.md` e, quando criado, `CHANGELOG.md`. Mover documentos de
apoio para `docs/`, agrupados por domínio (`architecture`, `data`,
`engineering` e `governance`). Mover configurações operacionais de
infraestrutura para `infra/`.

Consequências:
- A raiz passa a expor apenas os documentos de entrada e governança.
- Referências internas devem usar os novos caminhos.
- Conteúdo preexistente em `docs/` é preservado; a organização não
  altera sua semântica.

---

ADR-006
Título: Stack tecnológica e gestão de dependências

Status:
Aceito

Contexto:
Durante a Sprint 0B, a stack tecnológica (PROJECT_CONTEXT.md §4) foi
revisada formalmente. Constatou-se que:
- `pyproject.toml` não declarava dependências — os Dockerfiles
  instalavam pacotes soltos sem versão fixa, e `pip install -e .` não
  trazia pacote algum por falta de `[project.dependencies]`.
- dbt Core estava listado na stack sem implementação. A alternativa
  de removê-lo (substituindo por SQL puro DuckDB) foi avaliada:
  - Prós: menos uma ferramenta para aprender/manter, setup mais simples.
  - Contras: RF-07 exige lineage e data dictionary automáticos, que
    `dbt docs generate` entrega nativamente — remover dbt significaria
    reimplementar essa funcionalidade manualmente.
- Não havia separação entre dependências base, por serviço (API,
  pipeline, dashboard) e de desenvolvimento.

Decisão:
1. Manter dbt Core na stack. O lineage automático e a documentação
   gerada por `dbt docs` justificam o custo de aprendizado, dado que
   RF-07 exige esses entregáveis.
2. Adotar `[project.dependencies]` para pacotes comuns a todos os
   serviços (pydantic, structlog, tenacity, httpx, pandas, numpy,
   pyyaml, python-dotenv) e `[project.optional-dependencies]` para
   grupos por serviço: `api`, `pipeline`, `dashboard`, `analytics`,
   `dev` — cada Dockerfile instala apenas seu grupo.
3. Fixar versões mínimas de todos os pacotes (ex: FastAPI >=0.110,
   Streamlit >=1.35, Airflow ==2.9.3, DuckDB >=1.0, dbt-core >=1.7,
   scikit-learn >=1.4, NetworkX >=3.2).

Consequências:
- Dependências centralizadas e versionadas — mesmo pacote com mesma
  versão em todos os ambientes.
- Dockerfiles mais simples: um `pip install -e ".[grupo]"` substitui
  múltiplos `pip install` soltos.
- dbt exige `profiles.yml` e `dbt_project.yml` a serem criados na
  Sprint 4 — custo de setup postergado, não eliminado.
- Qualquer nova dependência deve ser adicionada ao grupo opcional
  correspondente, não diretamente no Dockerfile.

---

ADR-007
Título: Arquitetura de containers e deploy

Status:
Aceito

Contexto:
O projeto precisa de uma estratégia de containerização e deploy que
suporte o ciclo de desenvolvimento local e a implantação em infraestrutura
gratuita (Oracle Cloud Always Free + Streamlit Community Cloud). Durante
a Sprint 0B, os seguintes requisitos emergiram:
- Serviços de pipeline (Airflow webserver + scheduler + PostgreSQL) não
  precisam rodar 24/7 — apenas durante a execução do pipeline diário.
- API e dashboard precisam estar sempre disponíveis.
- Um reverse proxy é necessário para rotear `/api/*` → FastAPI,
  `/` → Streamlit, `/minio/` → MinIO Console.
- O deploy deve ser reproduzível via Docker Compose, sem dependência
  de serviço cloud proprietário.

Decisão:
1. Docker Compose multi-serviço com três perfis:
   - Perfil padrão (default): nginx, api, dashboard, minio — serviços
     core sempre ativos.
   - Perfil `pipeline`: postgres, airflow-webserver, airflow-scheduler
     — ativado apenas durante execução do pipeline (`docker compose
     --profile pipeline up`).
2. Nginx como reverse proxy único na porta 80, roteando:
   - `/api/` e `/docs` → FastAPI (porta 8000)
   - `/` (raiz) → Streamlit (porta 8501)
   - `/minio/` → MinIO Console (porta 9001)
3. Cada serviço tem seu próprio Dockerfile multi-estágio (quando
   aplicável) na raiz do módulo correspondente (`api/Dockerfile`,
   `pipeline/Dockerfile`, `dashboard/Dockerfile`, `nginx/Dockerfile`).
4. Deploy em duas camadas gratuitas:
   - Oracle Cloud A1.Flex (2 OCPU, 12GB): Docker Compose com todos os
     serviços (API + pipeline batch).
   - Streamlit Community Cloud: apenas o dashboard, consumindo a API
     remota.
5. MinIO como storage local em Docker, não como serviço externo —
   dados transitam dentro da rede Docker, sem expor MinIO
   publicamente.

Consequências:
- Perfil `pipeline` reduz consumo de recursos em 99% do tempo (três
  containers a menos ociosos).
- Nginx adiciona um ponto único de configuração de rede — qualquer
  novo serviço exige atualização do `default.conf`.
- Streamlit Community Cloud não consegue rodar o pipeline completo —
  apenas o dashboard. Pipeline sempre executa na Oracle Cloud.
- Para desenvolvimento local, `docker compose up` sobe toda a stack
  sem necessidade de Oracle Cloud.

---

ADR-008
Título: Estratégia de configuração externa

Status:
Aceito

Contexto:
O RNF de manutenibilidade (PROJECT_CONTEXT.md §1.3) exige "zero
hardcode — configuração externa via `config/*.yaml`/`.env`". Durante
a Sprint 0B, foi identificado que:
- Os arquivos `config/sources.yaml` e `config/pipeline.yaml` existiam
  vazios (apenas comentários), sem schema definido.
- O `.env.example` continha 5 variáveis, mas não havia validação de
  tipos ou valores obrigatórios.
- Cada Dockerfile passava variáveis de ambiente manualmente via
  `environment:` no `docker-compose.yml`, sem camada de validação.
- Módulos Python futuros precisarão carregar config de forma
  consistente — cada desenvolvedor implementar seu próprio loader
  geraria divergência.

Decisão:
1. Adotar `pydantic-settings` como camada única de configuração — um
   `Settings` class por domínio carrega de `.env` + variáveis de
   ambiente com validação de tipo.
2. Manter `config/*.yaml` para configuração estática e versionada
   (fontes de dados, parâmetros de pipeline, thresholds analíticos),
   carregados via `pyyaml` com schema Pydantic.
3. `.env` exclusivamente para segredos e variáveis de ambiente locais
   (CPF_HMAC_SECRET_KEY, MINIO_ROOT_PASSWORD, DUCKDB_DATABASE_PATH,
   LOG_LEVEL) — nunca versionado.
4. Criar `pipeline/config.py` como o loader centralizado que unifica
   `.env` + `config/*.yaml` e expõe objetos `Settings` tipados para
   todos os módulos.

Consequências:
- Toda configuração nova deve ser adicionada primeiro a uma class
  `Settings` — sem isso, a config não é carregada. Isso força o
  registro explícito de cada parâmetro.
- `config/pipeline.yaml` e `config/sources.yaml` devem ser
  preenchidos com valores reais antes do início da Sprint 2.
- `pipeline/config.py` é dependência de todos os módulos — qualquer
  refatoração futura deve preservar sua interface.
- Segredos continuam fora do repositório (`.env` no `.gitignore`).

---

ADR-009
Título: Estratégia de ingestão — Batch/Lambda simplificado (streaming descartado)

Status:
Aceito

Contexto:
O projeto consome dados de três fontes federais: Câmara dos Deputados
(API REST), Senado Federal (CSV anual CEAPS) e Portal da Transparência
CGU (API REST com chave). Durante a Sprint 0B, a exploração empírica
das três fontes confirmou que:

- Câmara: API REST com paginação, dados atualizados em batch pela
  própria fonte (não há endpoint de eventos/streaming). Ideal para
  ingestão incremental diária via watermark por `dataDocumento`.
- Senado: dados publicados como CSV anual estático
  (`despesa_ceaps_{ano}.csv`). Não há como consumir em "tempo real" —
  a própria natureza do dado é batch. Requer download completo do
  arquivo e parse (ISO-8859-1, decimal com vírgula, datas DD/MM/AAAA).
- CGU: API REST com autenticação via chave (`chave-api-dados`) e rate
  limit documentado no Swagger oficial (400 req/min diurno,
  700 req/min noturno). Também batch —
  consulta por páginas/ano/mês, sem streaming.

Nenhuma das três fontes oferece dados em streaming, e nenhuma persona
do projeto (jornalista, pesquisador, analista de controle) requer
latência sub-diária.

Decisão:
1. Adotar arquitetura batch com ingestão incremental (Lambda
   simplificado, sem camada de velocidade), executada via Airflow DAG
   com schedule `@daily`.
2. Estratégia por fonte:
   - **Câmara**: ingestão incremental via watermark
     (`dataDocumento`), página a página, com retry via `tenacity`.
   - **Senado**: download do CSV anual completo; deduplicação por
     `COD_DOCUMENTO` (já implementado no pipeline de referência do
     OPS). Execução sazonal (após publicação do CSV do mês anterior).
   - **CGU**: ingestão incremental via watermark (`dataLancamento`),
     página a página, com rate limiting respeitando o limite de 400
     req/min.
3. Descartar Kappa/streaming puro: exigiria broker de mensagens
   (Kafka/Redpanda) sem ganho real — a fonte não é nativamente um
   stream, seria streaming artificial sobre API/CSV batch.
4. Reproductibilidade garantida por `run_id`, `pipeline_version`,
   `execution_timestamp` e `source_version` em toda carga.
5. Caminho de evolução documentado (não implementado no MVP): se o
   escopo evoluir para fontes realmente contínuas (ex: redes sociais),
   a arquitetura permite introduzir camada de streaming (Kafka +
   Spark Structured Streaming) em paralelo ao batch existente
   (Lambda completo), sem reescrever Bronze/Silver/Gold.

Consequências:
- Pipeline é batch diário — não há latência sub-diária para nenhum
  dado.
- Senado exige tratamento especial (CSV anual vs. API incremental);
  o watermark não se aplica — usa-se deduplicação por hash do
  registro.
- CGU exige chave de API armazenada em `.env`/GitHub Secrets,
  seguindo o mesmo padrão do ADR-004 para HMAC.
- Rate limiting da CGU (400 req/min) exige controle explícito no
  extrator — `tenacity` com `wait_exponential` + throttling.
- Reproductibilidade: qualquer execução anterior pode ser reproduzida
  a partir de `run_id` e `pipeline_version`.
