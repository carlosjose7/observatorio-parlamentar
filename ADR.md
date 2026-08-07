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

---

ADR-010
Título: Dimensão institucional — dim_orgao e dim_unidade_gestora (SIAFI-ready)

Status:
Aceito

Contexto:
O modelo dimensional original (PROJECT_CONTEXT.md §7) não previa
nenhuma entidade formal para os órgãos federais de origem dos dados.
A vinculação institucional (Câmara, Senado, órgãos do Executivo)
ficava implícita no nome da fonte de ingestão (`camara`, `senado`,
`cgu`), sem representação como dado consultável.

Durante a Sprint 1, dois fatores tornaram essa lacuna explícita:
- O código institucional SIAFI do Senado Federal foi identificado
  (UG 020001, Gestão 00001), confirmando que essa informação é
  pública, estável e documentável.
- A API da CGU expõe nativamente `unidadeGestora.codigo` e
  `unidadeGestora.nome` em múltiplos endpoints (cartões, despesas),
  além de um endpoint de referência `/orgaos-siafi` — evidenciando
  que o projeto já lida com dado institucional estruturado sem ter
  onde armazená-lo de forma reutilizável.

A evolução do projeto para além de dashboard — em direção a uma
plataforma de engenharia de dados capaz de integrar futuramente com
SIAFI, Tesouro Nacional e execução orçamentária — reforça a
necessidade de uma dimensão institucional própria, em vez de
metadado espalhado em `config/sources.yaml` ou hardcoded no código.

Decisão:
1. Criar duas dimensões com responsabilidades distintas:

dim_orgao
id_orgao (PK, surrogate)
poder            -- Legislativo, Executivo, Judiciário
instituicao
sigla
ug_siafi         -- nullable, aplica-se quando o próprio órgão tem UG direta
gestao           -- nullable, idem
dim_unidade_gestora
id_unidade_gestora (PK, surrogate)
codigo
gestao           -- nullable, aplica-se apenas quando fonte_origem = 'SIAFI'
nome
id_orgao (FK)
fonte_origem     -- SIAFI | CGU | Tesouro Nacional | outro
-- chave natural: (fonte_origem, codigo)

2. `dim_orgao` representa exclusivamente entidades institucionais
   (Câmara, Senado, Ministérios etc.). `dim_unidade_gestora`
   representa exclusivamente entidades administrativas/orçamentárias,
   ligada a `dim_orgao` por FK. Nenhuma dimensão acumula os dois
   conceitos.

3. `dim_unidade_gestora` é genérica desde a concepção — não acoplada
   exclusivamente ao SIAFI. O campo `fonte_origem` permite que UGs de
   outros sistemas (CGU, Tesouro Nacional, ou sistema futuro) sejam
   representadas na mesma tabela. A chave natural é composta
   (`fonte_origem`, `codigo`), não apenas `codigo`, para evitar
   colisão entre identificadores de sistemas diferentes.

4. O campo `gestao` é específico do modelo SIAFI (par UG+Gestão) e
   deve ser tratado como nullable, aplicável apenas quando
   `fonte_origem = 'SIAFI'`. Deve ser documentado explicitamente
   como tal no `data_dictionary.md`, para não se tornar um campo
   ambíguo (mesmo risco já observado em `numRessarcimento` na
   Câmara e `codTipoDocumento` sempre 0).

5. `fact_despesa` é criada desde a v1 com duas FKs institucionais:
   - `id_orgao` (**NOT NULL**) — sempre resolvido, inclusive para
     Câmara e Senado.
   - `id_unidade_gestora` (**NULLABLE**) — permanece `NULL` para
     todos os registros até que exista requisito funcional para
     análises em nível de Unidade Gestora.

6. Na v1 do MVP:
   - `dim_orgao` é populada normalmente (mínimo: Câmara dos
     Deputados e Senado Federal, com UG/Gestão SIAFI quando
     aplicável).
   - `dim_unidade_gestora` existe apenas na modelagem — schema
     criado, tabela vazia.
   - `id_unidade_gestora` permanece `NULL` para todos os registros
     de `fact_despesa`.

Consequências:
- O grão de `fact_despesa` não muda — continua "uma despesa". O
  benefício da decisão não é preservar o grão (que já era estável),
  e sim evitar evolução estrutural do schema: quando houver
  integração com SIAFI, Tesouro Nacional ou análises por Unidade
  Gestora, basta popular `dim_unidade_gestora` e fazer backfill da
  FK correspondente — sem alterar o esquema da tabela fato ou
  reprocessar Bronze/Silver.
- `dim_orgao` fica pequena por design (dezenas de linhas) — grão
  "órgão institucional", não "unidade gestora". Órgãos do Executivo
  entram em nível agregado, não por campus/unidade.
- Câmara e Senado não têm UG/Gestão SIAFI documentada da mesma forma
  que órgãos do Executivo em todos os casos — `ug_siafi`/`gestao`
  em `dim_orgao` devem ser tratados como nullable.
- `data_dictionary.md` deve documentar explicitamente que `gestao`
  em `dim_unidade_gestora` só se aplica quando `fonte_origem =
  'SIAFI'`, para evitar interpretação incorreta em integrações
  futuras com outras fontes.
- O modelo ER (PROJECT_CONTEXT.md §7) e o dicionário de dados devem
  ser atualizados para incluir as duas dimensões, mesmo com
  `dim_unidade_gestora` inativa, garantindo que a arquitetura já
  reflita a decisão desde a Sprint 1.
- Nenhuma mudança de comportamento em ADRs anteriores — decisão
  aditiva ao modelo dimensional existente (§7).
- `dim_orgao.ug_siafi`/`gestao` é uma denormalização de conveniência
  para órgãos com UG própria direta (ex: Senado). Não é mutuamente
  exclusivo com `dim_unidade_gestora`: quando esta for ativada, o
  mesmo órgão poderá também ter uma linha correspondente lá. As duas
  representações coexistem por design — uma não substitui a outra.  

---

ADR-011
Título: Refinamento da pseudonimização de CPF/CNPJ — tratamento de string vazia e distinção por comprimento

Status:
Aceito — refina ADR-004 (decisão original permanece válida; este ADR
cobre dois casos não tratados na redação anterior)

Contexto:
ADR-004 definiu HMAC-SHA256 para pseudonimização de CPF, mas não
especificou:
1. Como distinguir CNPJ de CPF dentro do campo `cnpjCpfFornecedor`
   (Câmara) / `CNPJ_CPF` (Senado) / `estabelecimento.cnpjFormatado`
   ou `portador.cpfFormatado` (CGU) — campo que mistura os dois
   tipos de documento na mesma coluna, conforme já documentado em
   `data_dictionary.md` §3.1 e §3.3.
2. Como tratar valores vazios (`""`) — a Câmara apresenta taxa de
   nulos de 3.55% a 13.7% (variação por tamanho de amostra, ver
   `data_dictionary.md` nota¹) neste campo especificamente.

Aplicar HMAC-SHA256 literalmente sobre uma string vazia (`""`) produz
um hash determinístico único — o mesmo hash para *todos* os
registros sem fornecedor identificado. Isso criaria, sem intenção,
uma identidade de fornecedor fantasma que agregaria indevidamente
todos os registros nulos em `dim_fornecedor`, contaminando métricas
de concentração de fornecedores (`HHI`, §8) e a própria
`supplier_concentration` (§7) com um "fornecedor" que não existe.

Além disso, CNPJ é dado de pessoa jurídica — não é dado pessoal
sensível sob a LGPD — enquanto CPF é dado pessoal e exige a proteção
já definida em ADR-004. Tratar os dois indistintamente com o mesmo
hash é proteção desnecessária sobre CNPJ (reduz utilidade analítica
sem ganho de compliance) e, pior, mascara a ausência de distinção
formal entre os dois tipos de documento no dado extraído.

Decisão:
1. **String vazia (`""`) ou nula nunca é hasheada.** Permanece como
   `NULL` em todas as camadas (Bronze inclusive, mantendo a regra de
   ADR-004 de nunca persistir dado em texto claro — mas `NULL` não é
   "dado em texto claro", é ausência de dado). Nenhuma identidade de
   fornecedor fantasma é criada.

2. **Distinção CNPJ vs. CPF por comprimento, após sanitização.**
   Sequência obrigatória no momento da extração/Silver:
   a. Remover toda formatação (pontos, barra, hífen) — necessário
      para Senado e CGU, que chegam formatados (`data_dictionary.md`
      §3.2, §3.3); Câmara já chega sem formatação.
   b. Contar dígitos restantes:
      - **14 dígitos → CNPJ.** Mantido em texto claro. Não é dado
        pessoal sensível; manter em claro preserva utilidade
        analítica plena (busca direta por CNPJ, CU-01).
      - **11 dígitos → CPF.** Pseudonimizado via HMAC-SHA256 com
        chave secreta, conforme ADR-004 original.
      - **Qualquer outro comprimento (≠ 11, ≠ 14, e não vazio) →
        anomalia de qualidade de dado.** Não é hasheado nem
        descartado silenciosamente — registrado no Data Quality
        Report (Sprint 3, `pipeline/quality.py`) e sinalizado para
        revisão manual. Zero tratamento implícito de dado malformado.

3. **`dim_fornecedor` precisa de um campo de tipo de documento
   explícito**, não apenas a chave hasheada/clara:

dim_fornecedor
cnpj_cpf_valor       -- CNPJ em claro OU hash HMAC do CPF OU NULL
tipo_documento        -- 'CNPJ' | 'CPF' | 'INVALIDO' | NULL

Isso evita que um consumidor da Gold precise re-inferir o tipo de
   documento pelo formato do valor armazenado (14 dígitos claros vs.
   64 caracteres hex de um hash SHA-256 é diferenciável, mas não deve
   ser responsabilidade do consumidor deduzir isso implicitamente).

Consequências:
- A chave natural de `dim_fornecedor`, hoje definida em
  PROJECT_CONTEXT.md §7 como `cnpj_cpf_hash` (nome que sugeria hash
  universal), precisa ser renomeada/redocumentada como
  `cnpj_cpf_valor` + `tipo_documento`, refletindo que nem todo valor
  ali é hash.
- `data_dictionary.md` deve documentar a regra de sanitização e
  branching por comprimento como regra de qualidade formal, não
  apenas nota de rodapé.
- `pipeline/quality.py` (Sprint 3) deve incluir uma regra Pandera
  explícita para comprimento de documento (11, 14, ou NULL —
  qualquer outro valor é falha de schema, não apenas nulo).
- Nenhuma mudança na chave HMAC nem no plano de rotação definidos em
  ADR-004 — este ADR não reabre a decisão de algoritmo, apenas
  formaliza os casos de borda que a redação original não cobria.
- Reforça RF-06 e o RNF de Segurança/LGPD (§1.3): nenhum CPF em
  claro, e agora também nenhuma identidade de fornecedor fantasma
  criada a partir de dado ausente.

---
---

ADR-012
Título: Separação de fatos por domínio de negócio — fact_emenda e fact_cartao_cpgf (modelo de constelação)

Status:
Aceito

Contexto:
A Sprint 1 identificou que dados da CGU (emendas parlamentares,
cartões CPGF) possuem grão distinto de `fact_despesa` (despesa
parlamentar individual, alimentada por Câmara e Senado):

- Emenda parlamentar tem grão "uma emenda" — não "uma despesa".
- Transação de cartão CPGF tem grão "uma transação de cartão
  corporativo", cujo portador pertence tipicamente ao Poder
  Executivo, não necessariamente a um parlamentar.

Forçar esses dois domínios para dentro de `fact_despesa` exigiria
colunas opcionais e regras condicionais numerosas (ex: campos de
emenda que não existem para despesa comum, portador de cartão sem
`id_parlamentar` correspondente), degradando a clareza semântica da
tabela e dificultando sua evolução — o mesmo tipo de problema que
ADR-010 já havia evitado para a dimensão institucional.

Decisão:
1. Cada domínio de negócio da CGU recebe sua própria tabela fato,
   com grão único e explícito:
   - `fact_despesa` — grão: uma despesa parlamentar (Câmara/Senado).
     Inalterada por este ADR.
   - `fact_emenda` — grão: uma emenda parlamentar.
   - `fact_cartao_cpgf` — grão: uma transação de cartão corporativo.

2. Todas as fatos compartilham as dimensões corporativas já
   definidas na arquitetura: `dim_data`, `dim_orgao`,
   `dim_unidade_gestora`, `dim_fornecedor`. Isso caracteriza um
   modelo de **constelação de fatos** (fact constellation / galaxy
   schema) — múltiplas fatos, dimensões compartilhadas.

3. `dim_parlamentar` é reutilizada quando aplicável ao grão do fato:
   - `fact_emenda.id_parlamentar` — **NOT NULL**. Faz parte da
     identidade do evento — toda emenda tem autor identificável
     (`nomeAutor` na fonte).
   - `fact_cartao_cpgf` **não referencia `dim_parlamentar`** na
     versão inicial da arquitetura. O portador de um cartão CPGF
     pertence estruturalmente ao domínio do Poder Executivo — o
     fato de um portador poder, em casos excepcionais, ser também
     um parlamentar é uma coincidência de dados, não uma relação
     estrutural do grão. Uma FK opcional que reflita apenas essa
     exceção violaria o princípio de que toda FK deve representar
     uma relação natural do domínio modelado, não uma correlação
     externa. Caso um requisito funcional futuro exija cruzar
     transações de CPGF com parlamentares, essa associação deve ser
     implementada por meio de uma tabela de relacionamento (bridge)
     ou camada analítica derivada — nunca por uma FK direta em
     `fact_cartao_cpgf` — preservando o grão original da tabela
     fato.

4. Princípio formal adotado para o projeto, aplicável a qualquer
   fato futura:

   > Cada tabela fato representa um único evento de negócio e um
   > único grão analítico. Fontes distintas podem originar fatos
   > distintas, enquanto as dimensões corporativas são
   > compartilhadas entre todos os fatos.

Consequências:
- Pipeline Bronze/Silver permanece organizado por domínio de origem
  (`pipeline/camara/`, `pipeline/senado/`, `pipeline/transparencia/`)
  — nenhuma mudança na DDD já estabelecida.
- Gold ganha duas tabelas fato novas; nenhuma mudança em
  `fact_despesa` existente.
- `dim_orgao` e `dim_unidade_gestora` (ADR-010) passam a ser
  efetivamente reutilizadas entre múltiplos domínios — validação
  prática de que a decisão de generalizar essas dimensões
  (`fonte_origem` em vez de acoplamento único ao SIAFI) foi
  acertada.
- RF-12 (reprodutibilidade via `run_id`/`pipeline_version`/
  `execution_timestamp`/`source_version`) se aplica a todas as
  novas fatos, sem exceção — detalhado no próximo artefato da
  sprint (estratégia de watermark/versionamento).
- Consultas analíticas que combinem domínios (ex: parlamentar com
  despesa CEAP alta E autor de emendas concentradas) usam as
  dimensões compartilhadas como ponto de junção — nenhuma fato
  referencia outra fato diretamente.
- Novas bases da CGU (ex: contratos, viagens) podem originar novas
  fatos seguindo o mesmo princípio, sem remodelar as existentes.
- PROJECT_CONTEXT.md §7 (Modelo Dimensional) e o modelo ER
  (`docs/architecture/arch_er.md`) devem ser atualizados para
  incluir as duas novas fatos e suas dimensões compartilhadas.
- `fact_cartao_cpgf` permanece com FK apenas para as dimensões que
  pertencem estruturalmente ao seu grão (`dim_orgao`,
  `dim_unidade_gestora`, `dim_fornecedor`, `dim_data`). Qualquer
  cruzamento futuro com `dim_parlamentar` é responsabilidade de uma
  bridge table dedicada (ex: `bridge_cartao_parlamentar`), não da
  fato — mantendo a fato "pura" e evitando FK opcional baseada em
  coincidência de dados em vez de relação de domínio.

---

ADR-013
Título: Fronteira de validação entre Pydantic e Pandera (Bronze/Silver)

Status:
Aceito

Contexto:
`pipeline/contracts.py` e os `schemas.py` por fonte (Pydantic) já
validam estrutura e tipo por registro individual desde a Sprint 1,
na extração. `sprint_rules` exige adicionalmente Pandera na Sprint 3
("validações com Pandera"), sem que a fronteira entre as duas
camadas estivesse definida — risco de sobreposição de
responsabilidade ou de uma delas se tornar redundante.

Decisão:
Manter as duas camadas com responsabilidades complementares, não
substitutas:
1. Pydantic (já implementado) continua validando registro individual
   no momento da extração — tipo, presença de campo obrigatório,
   parsing inicial.
2. Pandera valida o DataFrame agregado no momento da carga Silver —
   schema por tabela (`silver_despesa`, `silver_parlamentar`, etc.),
   cobrindo regras que operam sobre a coluna/lote inteiro e que
   Pydantic não expressa bem: `valor_liquido >= 0`, unicidade
   pós-normalização da chave de negócio, datas em intervalo
   plausível (ex: não anterior a 2015, não futura).
3. Registros que falham no gate Pandera vão para quarentena
   (partição/log separado) — não são descartados silenciosamente,
   nem derrubam a execução do pipeline.

Consequências:
- Nenhuma reversão da decisão da Sprint 1 (`pipeline/contracts.py`
  permanece como está).
- Exige definir, por tabela Silver, o schema Pandera correspondente
  antes da implementação de `pipeline/quality.py`.
- Quarentena de registros inválidos precisa de local de persistência
  definido (ex: `data/silver/_quarantine/`) — detalhar na
  implementação.
- Falhas de parsing (ver ADR-016) são responsabilidade deste gate
  detectar e reportar, não do parser lançar exceção.

---

ADR-014
Título: Deduplicação independente por camada (defesa em profundidade)

Status:
Aceito

Contexto:
A Bronze já deduplica na escrita (read-merge-write, keep-first-seen)
pela chave natural bruta de cada fonte (Sprint 2). Levantou-se a
dúvida se a Silver poderia herdar essa garantia sem dedup próprio.
Dois fatores pesaram contra essa suposição: (1) a chave natural bruta
usada na Bronze não é necessariamente a mesma chave de negócio após
normalização (ex: CNPJ/CPF formatado vs. limpo); (2) o projeto já
identificou um bug real de suposição indevida sobre garantia de
camada anterior — o watermark de cartões usando `max()` lexicográfico
sobre `MM/AAAA` (Sprint 2).

Decisão:
A Silver implementa deduplicação própria e independente, pela chave
de negócio do grão dimensional definido *após* a normalização
(datas parseadas, CNPJ/CPF limpo) — não reaproveita nem assume a
deduplicação da Bronze. Cada camada do medalhão é responsável por
garantir sua própria integridade de grão.

Consequências:
- Cobre overlap entre partições Bronze de execuções diferentes, que
  a dedup da Bronze (por execução/chave bruta) não necessariamente
  cobre.
- Exige definir explicitamente a chave de negócio de dedup por
  tabela Silver na implementação (ex: `silver_despesa`:
  fonte + numDocumento normalizado + data).
- Custo adicional de lógica e testes por camada, aceito como
  trade-off de robustez (padrão consolidado em arquitetura
  medalhão).

---

ADR-015
Título: Persistência estruturada do Data Quality Report

Status:
Aceito

Contexto:
`sprint_rules` exige "Data Quality Report" como entregável da
Sprint 3, sem formato definido. `PROJECT_CONTEXT.md §11` já lista o
endpoint `GET /qualidade/relatorio` (Sprint 6) e o scaffold do
dashboard já reserva `dashboard/pages/09_qualidade.py` (Sprint 7) —
ambos consumidores futuros do relatório.

Decisão:
O Data Quality Report é persistido de forma estruturada em tabela
DuckDB (`data_quality_report`), particionada por `run_id`, contendo
por tabela/execução: contagem de registros válidos/quarentena,
regras Pandera violadas, percentual de nulos por campo crítico e
timestamp de execução. Geração de HTML fica reservada para a Sprint
de documentação automática (RF-07), que poderá consumir esta mesma
tabela — não implementada nesta sprint.

Consequências:
- `GET /qualidade/relatorio` (Sprint 6) e
  `dashboard/pages/09_qualidade.py` (Sprint 7) consomem a tabela
  diretamente, sem necessidade de reprocessamento ou parsing de
  HTML.
- Nenhum artefato HTML é gerado na Sprint 3 — não bloqueia o
  fechamento da sprint, mas deve constar como escopo futuro
  explícito em `BACKLOG.md` (RF-07).
- Schema da tabela `data_quality_report` deve ser adicionado a
  `docs/data/data_dictionary.md` na implementação.

---

ADR-016
Título: Módulo dedicado de normalização multi-fonte

Status:
Aceito

Contexto:
As três fontes de dados divergentes de data e valor monetário
(já documentado em `data_dictionary.md §3`): Câmara usa ISO 8601 e
float nativo; Senado e CGU usam DD/MM/AAAA e string pt-BR (vírgula
decimal, CGU com separador de milhar). Sem um módulo dedicado, a
lógica de parsing seria duplicada nos três `transform.py`
(`camara/`, `senado/`, `transparencia/`).

Decisão:
Criar `pipeline/normalize.py` com funções puras e testáveis
isoladamente (`parse_date_multi_format`, `parse_decimal_ptbr`,
`clean_document_number`, entre outras conforme necessidade),
importadas pelos três `transform.py`. Valores não-parseáveis
resultam em `NULL`/`NaT` + log estruturado — nunca lançam exceção
que interrompa o pipeline; a detecção e o reporte de falhas de
parsing são responsabilidade do gate Pandera (ADR-013), não do
parser.

Consequências:
- Elimina duplicação de lógica de parsing entre as três fontes.
- `pipeline/utils.py` permanece coeso como infraestrutura (retry,
  logging), sem lógica de domínio.
- `pipeline/normalize.py` é dependência direta dos três
  `transform.py` — cobertura de testes unitários isolada é
  pré-requisito antes da integração (Sprint 8 formaliza, mas testes
  básicos devem acompanhar a implementação da Sprint 3).
- Qualquer novo formato de fonte futura (ex: assembleias estaduais)
  reaproveita este módulo, evitando nova duplicação.

---

ADR-017
Título: Política de resolução de autor de emenda (individual vs.
colegiado) — execução diferida para a Sprint 4 por dependência de camada

Status:
Aceito

Contexto:
`fact_emenda` (ADR-012, gold.py:153) exige `id_parlamentar NOT NULL`.
O endpoint `GET /emendas` da CGU só retorna o autor como texto livre
(`autor`/`nomeAutor`, sempre duplicados) — sem ID, partido ou UF do
autor (confirmado via captura real da API, GET /emendas?ano=2024).

A captura real também confirmou que a própria fonte já classifica
estruturalmente o tipo de emenda: o registro de autor
"BANCADA DO MATO GROSSO" veio com `"tipoEmenda": "Emenda de Bancada"`
— campo já contratado em `CguBronzeEmenda.tipo_emenda` e propagado a
`FactEmenda.tipo_emenda`. Detecção por prefixo textual ("BANCADA",
"COMISSÃO") foi descartada como discriminador primário por ser
heurística degradável (falsos negativos como "RELATOR" ou nomes
livres de comissão) quando a fonte já entrega essa informação de
forma estruturada. O prefixo serve, no máximo, como checagem de
consistência (log de divergência), não como decisão.

Uma primeira proposta deste ADR previa a resolução de autor
(matching nome → `dim_parlamentar`) já na Silver (Sprint 3). Revisão
técnica identificou que isso violaria a camada: `dim_parlamentar` é
SCD Type 2 e é artefato do Gold (Sprint 4, ainda não populado nesta
sprint). Resolver contra um "snapshot próprio" da Silver duplicaria
a fonte de verdade sobre identidade de parlamentar, criando risco de
drift entre a cópia simplificada e a dimensão SCD2 real.

Uma amostragem da API (6 anos, 2 páginas por ano, ≈ 180 registros)
confirmou: (1) o `codigo_emenda` embute o ano e não apresentou colisão
real entre anos nos códigos legítimos; (2) existe a anomalia
`codigo_emenda = "S/I"` (código "sem informação"), todas concentradas
em 2020 e sempre em emendas colegiadas ou de relator com
autor="Sem informação" — um marcador de dado ausente, não um código
real, e não uma chave válida de deduplicação.

Decisão:
1. A Sprint 3 entrega `silver_emenda` sem tentativa de resolução de
   autor: `nome_autor` normalizado (uppercase, sem acento) e
   `tipo_emenda` fielmente tipado, seguindo o mesmo padrão das
   demais tabelas Silver (normalize → dedup + gate Pandera →
   persistência). Nenhuma coluna `id_parlamentar` é preenchida ou
   tentada nesta camada.
2. **Chave de negócio da deduplicação de `silver_emenda` é composta
   `(ano, codigo_emenda)`** — não `codigo_emenda` sozinho. A
   configuração já trata `codigo_emenda` como chave natural "por ano"
   (config/sources.yaml:47); a chave composta mantém a propriedade
   por-ano à prova de futuras colisões globais e torna explícita a
   anomalia `S/I` (que colide dentro de um mesmo ano, expondo a
   linha como duplicata na dedup em vez de gravar 3 códigos iguais).
3. A resolução de autor → `id_parlamentar` é política definida por
   este ADR, mas **executada na Sprint 4 (Gold)**, quando
   `dim_parlamentar` SCD2 estiver materializada:
   a. `tipo_emenda` é o discriminador primário de autoria colegiada
(valores como "Emenda de Bancada", "Emenda de Comissão" —
       lista a confirmar contra os valores reais do enum da fonte).
      Emendas colegiadas → quarentena com motivo `autor_colegiado`,
      sem tentativa de matching individual.
   b. Para tipo individual, matching exato normalizado do `nome_autor`
      contra `dim_parlamentar.nome`, restrito à linha **vigente no ano
      da emenda** (não `is_current` do momento da execução) —
      respeita o versionamento SCD2.
   c. Nenhum match ou mais de um match (homônimos) → quarentena com
      motivo `autor_nao_resolvido` ou `autor_ambiguo`, respectivamente.
      Nunca grava `id_parlamentar` por critério arbitrário.
   d. Matching fuzzy/similaridade permanece descartado nesta decisão
      pelo risco conhecido de falso positivo silencioso.
4. `fact_emenda` no Gold recebe apenas emendas com autor individual
   já resolvido sem ambiguidade. Emendas colegiadas ou não resolvidas
   ficam fora do modelo dimensional atual — não descartadas, apenas
   não promovidas — até haver modelagem própria (ex: a dimensão de
   autor agregado) motivada por requisito funcional explícito (nenhum
   CU-01 a CU-08 atual depende de emendas colegiadas).
5. O mecanismo de relatório/quarentena para as categorias
   (`autor_colegiado`, `autor_nao_resolvido`, `autor_ambiguo`) é
   escopo explícito da Sprint 4, não do `data_quality_report` da
   Silver (ADR-015) — a mecânica concreta (extensão de schema, tabela
   própria, etc.) será desenhada no planejamento arquitetural da
   Sprint 4, não especificada por antecipação aqui. A classificação
   primária por `tipo_emenda` já é produzida e persistida em
   `silver_emenda` (Sprint 3) — ela é o insumo direto deste
   mecanismo, não uma classificação a redescrever no Gold.

Consequências:
- `silver_emenda` (Sprint 3) segue o mesmo padrão de implementação
  das demais tabelas Silver, sem componente especial — reduz o
  escopo da Onda 2 em relação à proposta original deste ADR.
- A garantia `id_parlamentar NOT NULL` de `fact_emenda` só é
  satisfeita no momento da promoção a Gold, não antes — a Silver
  intencionalmente não tenta satisfazê-la.
- `fact_emenda` no Gold recebe apenas emendas com autor individual
  resolvido, mas `tipo_emenda` permanece populado e tipado nessas
  linhas — discrimina formas de emenda individual (ex.: Transferência
  com Finalidade Definida vs. Relator) e segue sendo útil dentro do
  subconjunto promovido; não é removido ou esvaziado pelo deferimento
  da resolução de autor.
- Cria dependência explícita e documentada: a Sprint 4 não pode
  promover `fact_emenda` sem antes implementar a política de
  resolução aqui definida — registrada em `BACKLOG.md` como
  pré-requisito de Sprint 4, não item solto.
- `codigo_emenda = "S/I"` é documentado como anomalia de qualidade
  reconhecida (na amostragem de ≈180 registros, ~3 ocorrências, todas
  em 2020, sempre em emendas colegiadas ou de relator com
  autor="Sem informação") e candidata a regra de gate Pandera de
  unicidade/validade na implementação de `silver_emenda`.
- As linhas removidas pela dedup da Silver (incluindo os casos `S/I`)
  passam a ser persistidas e contabilizadas no Data Quality Report
  (extensão de ADR-015) — ver `BACKLOG.md` Onda 2 — para que o caso
  "dado ausente mascarado" seja distinguível de duplicação real no
  futuro.
- Reabre a possibilidade de matching fuzzy como melhoria futura
  condicional à taxa obtida de `autor_nao_resolvido` no mecanismo de
  qualidade da Sprint 4 — não implementado agora.

---
