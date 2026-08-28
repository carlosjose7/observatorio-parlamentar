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
Aceito — substitui a redação de PROJECT_CONTEXT.md §17. A camada de
aplicação foi refinada pelo ADR-033 (Sprint 6.5): o hash é aplicado na
Silver, e a Bronze mantém o CPF bruto equivalente-público sob acesso
restrito.
 
Contexto:
PROJECT_CONTEXT.md §17 definia "hash SHA-256 com salt fixo" para
CPFs de fornecedores PF. Salt fixo reutilizado em todos os registros
é vulnerável a força bruta/rainbow table, dado que o espaço de CPFs
válidos é finito e computável.
 
Decisão:
Adotar HMAC-SHA256 com chave secreta (gerenciada via GitHub Secrets
/ .env, nunca hardcoded), em substituição ao salt fixo. Nenhum CPF em
texto claro é persistido nas camadas consumíveis (Silver/Gold/API) —
hash aplicado na Silver (ADR-033 refina a camada: Bronze mantém o
dado bruto equivalente-público sob acesso restrito, sem hash).
 
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

> **Nota de reconciliação (26/08/2026 — Revisor Técnico/Documentador):**
> o item 4 desta decisão (dashboard no Streamlit Community Cloud) nunca
> foi implementado. Da Sprint 0B até a Sprint 10, o dashboard sempre
> rodou no mesmo Docker Compose da VPS Oracle, junto com API/nginx/MinIO
> — nunca houve deploy separado. O ADR-036 (Sprint 10) formaliza o
> estado real: dashboard em `/app/` atrás do mesmo Nginx, sem camada
> Streamlit Community Cloud. Mantido aqui como registro histórico da
> intenção original em Sprint 0B; a decisão vigente de deploy é
> ADR-007 (itens 1–3, 5) + ADR-036.

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
   (`config/sources.yaml:100`); a chave composta mantém a propriedade
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
   e. Autor individual sem cobertura em `dim_parlamentar` no ano da
      emenda — nome corresponde a um parlamentar que não faz parte do
      universo coberto pelos dados mestres (Câmara + Senado) vigentes
      naquele ano (ex.: mandato exercido em outro órgão, período sem
      snapshot capturado) → quarentena com motivo `autor_fora_cobertura`,
      distinguindo do `autor_nao_resolvido` (há cobertura, mas o nome
      não casou). A cobertura de `dim_parlamentar` exige a Onda 2
      materializada com Câmara **e** Senado (BACKLOG.md); sem isso,
      emendas de senador seriam mascaradas como `autor_nao_resolvido`.
4. `fact_emenda` no Gold recebe apenas emendas com autor individual
   já resolvido sem ambiguidade. Emendas colegiadas ou não resolvidas
   ficam fora do modelo dimensional atual — não descartadas, apenas
   não promovidas — até haver modelagem própria (ex: a dimensão de
   autor agregado) motivada por requisito funcional explícito (nenhum
   CU-01 a CU-08 atual depende de emendas colegiadas).
5. O mecanismo de relatório/quarentena para as categorias
   (`autor_colegiado`, `autor_nao_resolvido`, `autor_ambiguo`,
   `autor_fora_cobertura`) é escopo explícito da Sprint 4, não do
   `data_quality_report` da Silver (ADR-015) — a mecânica concreta (extensão de schema, tabela
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

Implementação (Onda 2, BACKLOG.md):
- A classificação é centralizada no modelo dbt efêmero
  `em_autor_classificacao` (`pipeline/gold/models/emenda/`), que
  materializa a regra 3.a–3.e deste ADR de forma determinística e é
  consumida por dois modelos Gold (padrão ADR-018):
  - `emenda_autor` — apenas `autor_resolvido` (matching exato com
    exatamente um `dim_parlamentar` vigente no ano da emenda; grava
    `id_parlamentar` e `surrogate_key` da versão casada);
  - `emenda_autor_quarantine` — demais status com motivo explícito
    (`autor_colegiado`/`autor_ambiguo`/`autor_fora_cobertura`/
    `autor_nao_resolvido`).
- `dim_parlamentar` SCD2 (ADR-020) é recomputada deterministicamente do
  histórico de snapshots de `silver_parlamentar` (Câmara + Senado); o
  matching usa a vigência-por-ano `[effective_date, end_date)`
  (`make_date(ano, ...)`), nunca `is_current` do momento da execução.
- Vocabulário de colegiados em `dbt_project.yml` (`emenda_tipos_colegiados`,
  padrão "Emenda de Bancada"/"Emenda de Comissão") — a confirmar contra o
  enum real da fonte (item de seguimento no BACKLOG).
- Cobertos por testes de integração dbt (`tests/pipeline/test_gold_scd2_adr017.py`).
- `fact_emenda` (ADR-012, decisão 4) promovido na Onda 3 a partir de
  `emenda_autor`: `id_parlamentar` NOT NULL (identidade do evento) e
  `surrogate_key` da versão vigente; `id_orgao` derivado da `fonte` da
  versão casada (CD=1/SF=2); `data_sk` em 31/12/ano (fonte só expõe ano);
  complemento não-resolvido em `fact_emenda_quarantine` com motivo.

---

ADR-018
Título: Adoção de dbt Core no Gold com quarentena por construção (sem hooks Pandera)

Status:
Aceito

Contexto:
ADR-006 já havia decidido manter dbt Core na stack, justificado pelo
lineage automático e data dictionary nativo exigidos por RF-07
(`dbt docs generate`), com o custo de setup (`profiles.yml`,
`dbt_project.yml`) explicitamente postergado para o momento em que
houvesse schema real a materializar — ou seja, a Sprint 4.

Silver usa Pandera + `quality.py` para validar antes de escrever,
com quarentena de registros inválidos (ADR-013, ADR-015). Ao avaliar
como preservar esse princípio na fronteira Silver→Gold com dbt,
duas alternativas foram consideradas:

(a) Testes dbt nativos (schema.yml + singular tests) como validação,
    com quarentena expressa via CTE/WHERE dentro do próprio model SQL.
(b) Pandera executando via hook (pre-hook/post-hook) do dbt.

A opção (b) foi descartada: hooks dbt rodam antes/depois da
materialização do model, o que implicaria escrever a tabela Gold e
só then aplicar a validação — reproduzindo o anti-padrão
"escrever, testar depois, decidir o que fazer com a falha", que
contraria o princípio de defesa-em-profundidade estabelecido em
ADR-014.

Decisão:
1. Adotar dbt Core exclusivamente para a camada Gold. Bronze e
   Silver permanecem procedurais em Python (inalterados).
2. Cada entidade Gold é modelada como dois models dbt, sem prefixo
   `gold_` (redundante — o diretório `gold/models/` e o target DuckDB
   já qualificam a camada):
   - `{entidade}.sql` — `SELECT ... FROM {staging} WHERE (regra_valida)`
   - `{entidade}_quarantine.sql` — `SELECT ..., 'motivo' AS
     motivo_quarentena FROM {staging} WHERE NOT (regra_valida)`
   Exemplos: `fact_despesa` / `fact_despesa_quarantine`,
   `dim_parlamentar` / `dim_parlamentar_quarantine`. O sufixo
   qualifica o destino (a tabela que falhou a regra) e não colide
   com a convenção de prefixo do Silver (`quarantine_*`), já que
   vivem em camadas distintas dentro do mesmo DuckDB.
   A regra de validade mora no próprio SQL (quarentena por
   construção), não em um passo de pós-processamento.
3. `schema.yml` + testes de estrutura dbt cobrem uma segunda camada de
   checagens: `not_null`, `unique`, `relationships` (integridade
   referencial fato→dimensão, ADR-022) e testes SQL customizados de
   órfãos.
4. Pandera permanece exclusivo da fronteira Bronze→Silver. Não é
   introduzido no runtime do dbt.
5. Setup mínimo: `profiles.yml` (target DuckDB local), `dbt_project.yml`,
   diretório `gold/models/` com subpastas por domínio (dimensões,
   fatos, analytics). `dbt-duckdb` e `dbt-core` já constam do grupo
   opcional `pipeline` do `pyproject.toml` desde a Sprint 2 (ADR-006).

Consequências:
- Estrutura de arquivos do Gold: par de models `{entidade}.sql` +
  `{entidade}_quarantine.sql` por entidade, mais `schema.yml` — não
  há pasta de hooks Pandera no Gold.
- `dbt docs generate` entrega lineage e data dictionary
  automaticamente (RF-07), sem trabalho manual adicional.
- Curva de aprendizado e setup inicial de dbt, precificados desde
  ADR-006, são absorvidos nesta sprint.
- Qualquer nova entidade Gold deve seguir o par de models
  válido/quarentena — desvio desse padrão exige justificativa
  registrada em revisão técnica.
- dbt é a única forma de escrita regular na camada Gold a partir desta
  sprint; escrita procedural direta ao Gold via Python é descontinuada
  (exceção pontual documentada no ADR-019 para o backfill de
  `pipeline_runs`).

---

ADR-019
Título: Migração de pipeline_runs de Parquet (Bronze) para tabela DuckDB (Gold)

Status:
Aceito

Contexto:
`runs.py` persiste hoje 1 arquivo Parquet por `run_id` no Bronze, com
schema de 1 linha por execução e colunas `watermark_{fonte}`. O
docstring do próprio módulo já previa a migração para DuckDB na
Sprint 4 (`versionamento.md §4`). RF-12 exige reprodutibilidade de
qualquer execução anterior a partir de `run_id` e `pipeline_version`,
e o Data Quality Report do Gold precisa referenciar `run_id` no mesmo
engine em que fatos/dimensões vivem — não é prático fazer join
DuckDB↔Parquet-Bronze em toda consulta de auditoria.

Decisão:
1. Criar tabela `pipeline_runs` no DuckDB Gold, mantendo o grão atual:
   1 linha por `run_id`, com colunas `watermark_{fonte}` (não se
   normaliza para 1 linha por fonte por run nesta sprint).
2. `pipeline_runs` é um model dbt incremental (chave única `run_id`),
   lendo o Parquet do Bronze como dbt source declarado em
   `gold/models/sources.yml`. Essa é a via de sincronização de rotina
   — preserva o princípio do ADR-018 de que dbt é a única forma
   regular de escrita no Gold.
3. Exceção pontual e documentada: `scripts/backfill_pipeline_runs.py`
   — script único, não incremental, executado uma vez para migrar o
   histórico de Parquets já gerado nas Sprints 2/3 (anterior à
   existência do model incremental). Não é caminho de escrita
   rotineiro; após o backfill, toda sincronização passa pelo model
   dbt.
4. Bronze continua recebendo o Parquet por run (não é descontinuado)
   — a tabela DuckDB é a fonte de consulta primária a partir desta
   sprint; o Parquet permanece como registro raw imutável e como
   source do model incremental.
5. Se o futuro exigir granularidade por fonte, trata-se de extensão
   da tabela de relatório, não quebra a chave `run_id` existente.

Consequências:
- Consultas de reprodutibilidade e o Data Quality Report do Gold
  passam a usar `pipeline_runs` via DuckDB diretamente.
- `scripts/backfill_pipeline_runs.py` é executado uma única vez, sob
  responsabilidade explícita do Engenheiro de Dados — não integra o
  `dbt build` de rotina.
- `gold/models/sources.yml` precisa declarar o Parquet do Bronze como
  source, o que exige o dbt ter acesso de leitura ao diretório Bronze
  (path relativo/configurável via `config/pipeline.yaml`).
- `runs.py` permanece escrevendo apenas o Parquet do Bronze; a
  sincronização DuckDB é responsabilidade exclusiva do model dbt
  incremental (ADR-018), evitando escrita dupla em Python.

---

ADR-020
Título: Estratégia SCD Type 2 para dim_parlamentar

Status:
Aceito

Contexto:
PROJECT_CONTEXT.md §7 já define as colunas de auditoria SCD2 exigidas
(`effective_date`, `end_date`, `is_current`, `surrogate_key`) para
`dim_parlamentar`, mas não a estratégia de carga. RF-11 exige
histórico rastreável de mudança de partido/status. A Sprint 4 também
introduz o mecanismo de resolução de autor de emenda (ADR-017), que
depende de consultar `dim_parlamentar` vigente em um ano específico —
ou seja, a estratégia de vigência-por-ano precisa estar definida antes
da Onda 2.

Decisão:
1. Carga via merge/upsert por snapshot: cada execução do pipeline Gold
   compara o snapshot atual (Silver/API Câmara-Senado) contra o
   registro `is_current = true` existente por `id_parlamentar`.
   - Sem mudança em atributos rastreados (partido, situação): não
     gera nova versão.
   - Com mudança: fecha o registro vigente (`end_date` = data da
     execução, `is_current = false`) e insere novo registro
     (`effective_date` = data da execução, `is_current = true`,
     novo `surrogate_key`).
2. Vigência-por-ano (consumo do ADR-017): a versão vigente de um
   parlamentar em dado ano é aquela cujo intervalo `[effective_date,
   end_date)` contém qualquer data daquele ano — necessária para
   resolver autoria de emendas de anos anteriores à execução atual.
3. `surrogate_key` é `BIGINT` autoincremental por versão, nunca
   reaproveitado.

Consequências:
- `dim_parlamentar` requer lookup por intervalo de datas, não apenas
  por chave natural — estratégia de consulta/indexação a decidir na
  implementação.
- ADR-017 (resolução de autor de emenda) passa a ter definição precisa
  de "parlamentar vigente no ano X".
- Primeira carga (bootstrap) não tem snapshot anterior — todos os
  registros entram com `effective_date` = data da primeira execução
  do Gold e `is_current = true`, sem histórico prévio reconstruível a
  partir das fontes disponíveis (limitação conhecida, não bloqueante).

Nota de emenda (Onda 2 — supersessão parcial):
A implementação de `dim_parlamentar` (pipeline/gold/models/dimensions/
dim_parlamentar.sql) diverge deliberadamente da decisão 1 acima: em
vez de carga incremental merge/upsert por snapshot, a dimensão é
**recomputada deterministicamente** do histórico completo de snapshots
de `silver_parlamentar` (append-only, ordenado por data as-of), e
registrada em nota de emenda deste ADR para registrar a decisão e sua
justificativa técnica.

Justificativa técnica (motivo da supersessão):
1. **Precisão de `end_date`**: o merge por snapshot data marca `end_date`
   como **data da execução** do Gold — uma aproximação do momento real da
   mudança. O recompute usa `end_date` = data as-of da observação seguinte
   (window `lead(effective_date)`), medida observacional exata, não
   administrativa. O teste de regressão (tests/pipeline/test_gold_scd2_adr017.py)
   prova o SCD2 pegando a versão que vigia no ano, justamente porque a
   primeira versão fecha em 2019-07-01 (observação seguinte), não "na data
   em que o pipeline rodou".
2. **Robustez a reprocessamento**: merge incremental não refaz versões já
   fechadas em execuções anteriores quando há backfill/reprocessamento da
   Silver — estado divergente (ADR clássico de SCD2 incremental). O recompute
   é idempotente e reproduz o histórico inteiro exatamente a cada execução
   (RF-12), a um custo aceitável para o volume esperado do projeto.
3. **Coerência com o modelo de materialização do Gold**: todas as camadas
   Gold são reconstruídas via `dbt build` na base da Silver, sem camada
   cumulativa que justifique o estado incremental.

Alterações de contrato documentadas:
- `surrogate_key` deixa de ser autoincremental (decidido na decisão 3)
  e passa a ser **composta determinística**:
  `namespace(fonte) + id_parlamentar * 1000 + id_versao`, onde `id_versao`
  é o ordinal de versão computado por window (soma de flag LAG de mudança
  de `(nome, sigla_partido, sigla_uf, situacao_normalizada)` ordenado por
  `data`). Propriedades: idempotente; estável para um histórico estável;
  **não garante estabilidade da numeração sob backfill retroativo** inserido
  no meio do histórico (versões adjacentes renumeram) — limitação aceita
  porque as fontes atuais são append-only sem reconstrução retroativa, e
  registrada aqui como risco observável.
- Contrato de vigência-por-ano (decisão 2) mantido integralmente.

Consequência derivada (implicação prática não bloqueante, Sprint 6):
`surrogate_key` é estável apenas dentro de uma mesma execução completa do
`dbt build`; não deve ser exposto como identificador externo durável (API,
exports, cache). Para referência externa/idempotência entre execuções, usar
a **chave natural composta** `(fonte, id_parlamentar, effective_date)`:
estável sob qualquer re-computação do histórico. A Sprint 6 (API) deve
tratar essa restrição explicitamente ao desenhar endpoints que referenciem
parlamentares — mesma classe de dívida que já custou as Sprints 3 e Onda 2
(Senado); registrada antecipadamente para não virar descoberta tardia.

Status da nota: emendado, aguarda re-aprovação do ADR-020 na revisão da
Onda 2.

---

ADR-021
Título: Escopo das tabelas analíticas (§7) na Sprint 4 — placeholder vs. populado

Status:
Aceito

Contexto:
PROJECT_CONTEXT.md §7 lista tabelas analíticas Gold com duas categorias
distintas de dependência:
- Agregações puras de Silver (GROUP BY/COUNT/SUM), sem ML:
  `supplier_concentration` (HHI direto de `fact_despesa`),
  `supplier_growth`.
- Dependentes de modelos de ML/rede (Isolation Forest, PageRank,
  NetworkX), só existentes a partir da Sprint 5: `politician_similarity`,
  `expense_outliers`, `network_edges`, `network_nodes`, `risk_scores`.

Decidir agora evita `ALTER TABLE` retroativo quando a Sprint 5
começar a popular as tabelas dependentes de ML.

Decisão:
1. Tabelas puramente agregadas (`supplier_concentration`,
   `supplier_growth`) são schema + dados populados na Onda 1 da
   Sprint 4, como models dbt regulares.
2. Tabelas dependentes de ML/rede (`politician_similarity`,
   `expense_outliers`, `network_edges`, `network_nodes`,
   `risk_scores`) são materializadas como schema vazio (placeholder)
   na Sprint 4 — contrato de colunas definido, sem dados — e populadas
   exclusivamente na Sprint 5.
3. Placeholders seguem o mesmo padrão de nomenclatura e diretório dos
   models Gold definitivos, evitando renomeação futura.

Consequências:
- O contrato completo do Gold (§7) fica estável a partir da Sprint 4,
  mesmo com dados parciais.
- Sprint 5 apenas insere/atualiza dados nas tabelas placeholder — não
  cria schema novo.
- Testes dbt (`schema.yml`) das tabelas placeholder validam apenas
  estrutura (tipos, colunas), não conteúdo, até a Sprint 5.

---

ADR-022
Título: Contrato de qualidade Gold — integridade referencial fato-dimensão

Status:
Aceito

Contexto:
Pandera valida a fronteira Bronze→Silver (ADR-013). Faltava contrato de
qualidade formal para a fronteira Silver→Gold, onde o risco muda de
natureza: não é mais "campo malformado", mas "chave estrangeira órfã"
(ex: despesa referenciando `fornecedor_sk` inexistente em
`dim_fornecedor`) — risco inerente a popular fatos a partir de
dimensões carregadas independentemente (Onda 1 vs. Onda 3).

Decisão:
1. Todo model de fato Gold (`fact_despesa`, `fact_cartao_cpgf`,
   futuramente `fact_emenda`) declara em `schema.yml`:
   - `not_null` em toda coluna de chave estrangeira (`*_sk`).
   - `relationships` test contra a dimensão correspondente para cada FK.
2. Registros de fato cuja FK não resolve contra a dimensão vigente não
   são descartados em silêncio: seguem a quarentena por construção do
   ADR-018 — model `{fato}_quarantine.sql` com `motivo_quarentena =
   'fk_orfa:{coluna}'`.
3. Testes singulares SQL cobrem casos não expressáveis por
   `relationships` puro (ex: `id_unidade_gestora` nullable em
   `fact_despesa` mas NOT NULL em `fact_cartao_cpgf` — regra
   condicional por fonte, já registrada como aprendizado do projeto).

3a. Severidade dos testes de integridade referencial: `severity: warn`
    para os singular tests de FK órfã, com contagem de `fk_orfa` por
    tabela de fato reportada no Data Quality Report. Threshold
    configurável (default: FK órfãs > 5% do total no fato dispara alerta
    no relatório) — não bloqueia `dbt build`. Implementação concreta: o
    test genérico customizado `fk_orphan_pct` (macros/) computa a razão
    órfãos/total por fato com o parâmetro `threshold_pct`
    (`var('fk_orfas_threshold_pct')`), cuja FONTE ÚNICA é
    `config/pipeline.yaml` (`data_quality.fk_orfa_threshold_pct`, chave
    registrada em `DataQualitySettings`, ADR-008): o projeto dbt NÃO
    declara o número — cada invocação (DAG Gold futura e testes) injeta
    `--vars` gerado por `pipeline.config.get_dbt_vars()`; var obrigatória,
    sem default no código (falha se ausente, PROJECT_CONTEXT §15); coexiste
    com o `relationships` genérico (inspeção binária por registro), deixando
    a decisão de bloqueio por razão de massa para o alerta `warn`.
    Justificativa: FK órfã é sintoma
    de dimensão ainda não sincronizada (ex: fornecedor novo no fato antes
    da próxima carga de `dim_fornecedor`), não necessariamente erro de
    dado — bloquear penalizaria o pipeline por condição transitória e
    esperada em cargas incrementais.
4. `dbt build` (run + test) é o comando padrão de execução do Gold.
   Falhas de teste com `severity: error` (schema estrutural `not_null`,
   `unique`) bloqueiam a promoção; falhas com `severity: warn`
   (integridade referencial, item 3a) são reportadas no Data Quality
   Report sem bloquear.

Consequências:
- Todo novo fato Gold exige `schema.yml` com `relationships` antes de
  ser considerado completo — checklist de revisão técnica atualizado.
- Volume de quarentena Gold é observável via `{entidade}_quarantine`,
  alimentando o Data Quality Report (mesmo princípio do Silver,
  ADR-015).
- `dbt build` como gate único simplifica CI futura (Sprint 9): um
  comando, falha estrutural = pipeline vermelho, falha referencial =
  alerta observável sem bloqueio.

---

ADR-023
Título: Silver sem caminho de carga — transform.py ausente nas três fontes

Status:
Aceito

Contexto:
O fechamento da Sprint 3 aprovou o item "Pipeline Silver" do
`BACKLOG.md` com base na existência do motor: `silver.py`
(orquestração dedup + gate + persistência), `quality.py` (schemas
Pandera) e os testes (44 na época). Verificação contra o repositório
real revelou que **não há caminho de chamada que transforme Bronze →
Silver**:

1. Não existe `transform.py` em nenhuma fonte (`pipeline/camara`,
   `pipeline/senado`, `pipeline/transparencia`).
2. `carregar_tabela_silver` (`silver.py:226`) só é **definida**, nunca
   invocada — `grep` não encontra chamada em lugar algum.
3. O DAG (`pipeline_dags/pipeline_dag.py:19`) expõe apenas
   `_executar_bronze`; não há task Silver.
4. `extract.py` por fonte produzem apenas registros Bronze
   (`CamaraBronzeDespesa`, `SenadoBronzeDespesa`, `CguBronzeEmenda`,
   `CguBronzeCartao`).
5. O único teste que toca o motor Silver (`test_quality.py`) o
   alimenta **manualmente com DataFrames**, não através de
   transformação de fonte.

Ou seja: a Sprint 3 entregou **contrato (schemas Pydantic/Pandera) +
gate de qualidade + persistência DuckDB**, mas nenhum dado real
percorre o pipeline Silver ainda. O próprio `silver.py` antecipa o
ponto de entrada inexistente no docstring: "os `transform.py` por
fonte são os pontos que chamam estas funções com os DataFrames
Bronze". Causa raiz: fechamento baseado na existência do motor, sem
verificação de que havia um caminho de chamada real.

Consequência transversal: qualquer sprint futura que dependa de
"Silver funcionando" (incluindo a própria Sprint 4/Gold) precisa
tratar essa lacuna como pré-requisito explícito, não implícito — é o
que a Onda 1/Trilha B da Sprint 4 faz (ver ADR-018/019/022).

Decisão:
1. Os três `transform.py` (Câmara, Senado, CGU — emenda + cartão)
   entram como **pré-requisito da Onda 1 da Sprint 4**, absorvendo o
   gap da Sprint 3. A contabilidade é feita por nota corretiva no
   `BACKLOG.md`/`PROJECT_CONTEXT.md`, não por reabertura cerimonial da
   Sprint 3.
2. Interface comum obrigatória para os três módulos (evita três
   implementações divergentes):
   - Chamam `pipeline/normalize.py` (ADR-016) para parsing de datas,
     valores pt-BR e CNPJ/CPF.
   - Constroem o DataFrame Silver unificado por entidade e chamam
     `carregar_tabela_silver(df, tabela, run_id, chaves_dedup=...,
     campos_criticos=...)` (`silver.py:226`).
   - Chaves de negócio por entidade (ADR-014):
     - `silver_despesa` → `["fonte", "cod_documento"]`
     - `silver_emenda` → `["ano", "codigo_emenda"]`
     - `silver_cartao` → chave a confirmar na implementação (o `id`
       nativo da CGU não é propagado à Silver; a dedup da camada
       repassa a chave via `chaves_dedup`, ver ADR-013/schema).
   - Campos críticos para o percentual de nulos reportado no DQ
     Report (ADR-015) também por entidade.
3. `silver_despesa` unifica Câmara e Senado: a tabela recebe a coluna
   `fonte` (`'camara'`/`'senado'`) e as colunas canônicas do schema
   Pandera (`schema_silver_despesa`); mapeamento dos campos divergentes
   entre as duas fontes (ex: `nome_fornecedor`/`fornecedor`) é
   responsabilidade do `transform.py` de cada uma.
4. `pipeline_dag.py` ganha a(s) task(s) Silver **depois** que os
   `transform.py` existirem (item derivado no BACKLOG) — sem isso, o
   gap se repete: motor pronto, nada chamando. A task Bronze
   permanece como hoje.
5. O Gold (dbt, ADR-018) só consome tabelas Silver quando a trilha de
   carga estiver operante; models dbt escritos antes disso (Trilha A:
   `dim_data`, `dim_orgao`) são independentes de `silver_*` populada.

Consequências:
- A Sprint 4 passa a cobrir explicitamente o caminho Bronze → Silver
  → Gold de ponta a ponta para as três fontes.
- `BACKLOG.md`/`PROJECT_CONTEXT.md` recebem nota corretiva sobre o
  item "Pipeline Silver" da Sprint 3 (motor apenas, carga pendente).
- Testes de transformação fonte-a-fonte passam a existir (novos
  `transform_test` por fonte) — o `test_quality.py` atual testa o
  motor, não o caminho.
- Risco residual: chave de dedup de `silver_cartao` a confirmar na
  implementação (ponto 2) — não bloqueia a Onda 1, pois
  `silver_cartao` não alimenta os models da Trilha A.

---

ADR-024
Título: Paridade semântica de `silver_parlamentar` entre Câmara e Senado —
legislatura derivada por calendário e taxonomia normalizada de situação

Status:
Aceito

Contexto:
A Onda 2 cobriu Câmara e Senado na mesma tabela `silver_parlamentar`
(chave dedup composta `(fonte, id_parlamentar, data)`, ADR-020). Revisão
técnica pós-cobertura identificou que o schema unificado partiu do
payload da Câmara e dois campos que alimentam o SCD2 de `dim_parlamentar`
não têm paridade semântica quando o Senado entra:

1. **`id_legislatura` incompatível por fonte — não é bug de mapeamento.**
   A Câmara informa a legislatura **vigente** (`ultimoStatus.idLegislatura`);
   o Senado informa a **primeira do mandato** (`Mandato.`
   `PrimeiraLegislaturaDoMandato.NumeroLegislatura` — mandato de 8 anos,
   duas legislaturas). Campos que medem coisas diferentes no mesmo lugar;
   pior: o fallback hard-coded `0` do Senado chegava à Silver como linha
   **válida** (doc e schema antigos diziam "cai no gate", mas não havia
   `gt(0)`), gerando dimensão com legislatura 0.
2. **`situacao` usa taxonomias diferentes por fonte.** Câmara: situação de
   exercício em `ultimoStatus` (ex: "Exercício", "Licença"); Senado:
   descrição de participação no mandato (ex: "Titular", "Suplente"). Os
   vocabulários não se comparam e não é possível derivá-los por cálculo —
   só por um de-para explícito e documentado.

O propósito do SCD2 é rastrear a troca de partido/status no tempo (RF-11);
um atributo de histórico assimétrico entre Câmara e Senado quebra a
semântica da dimensão.

Decisão:
1. **Legislatura derivada por calendário** (opção (a) da revisão):
   `pipeline/parlamento.py` centraliza o calendário das legislaturas federais
   (54ª–58ª, intervalo contínuo desde 2011; dado estável e público);
   `silver_parlamentar.id_legislatura` é calculada do **calendário a partir
   de `data`** (as-of do snapshot) nos dois transformadores, nunca copiada da
   API.
   - O valor bruto da API é preservado em `id_legislatura_fonte` (auditoria,
     nullable) — inclusive o `0` do Senado deixa de injetar dado falso na
     dimensão e vira só marcador de auditoria.
2. **Gate Pandera com `Check.gt(0)` em `id_legislatura`** (bug
   independente da decisão acima, corrigido já): data fora do calendário
   (ex: ano 2000) → legislatura não resolvida → `id_legislatura=0` →
   **quarentena**, não linha válida. A `data_status` é o as-of e o calendário
   cobre o histórico 2015+ (o gate `nao_anterior_a(2015)` já isola
   o absurdo), reforçando a paridade.
3. **Taxonomia normalizada de `situacao`** com de-para versionado e
   **dois campos**:
   - `situacao_bruta`: valor original da fonte (rastreável, auditável).
   - `situacao_normalizada`: enum comum de `pipeline/parlamento`
     (`ativo`, `licenca`, `afastado`, `fim_mandato`, `nao_mapeado`).
   - De-para por fonte em tabela explícita (`_DE_PARA_SITUACAO` em
     `pipeline/parlamento.py`, chaves `camara`/`senado`), versionada com
     teste; vocabulário não catalogado → sentinela `nao_mapeado` (nunca
     NULL silencioso, auditável pelo bruto).
   - Não estende de-para inline em transformador: vocabulário novo entra em
     `pipeline/parlamento.py` com teste.
4. `schema_silver_parlamentar` (quality.py) reflete:
   - `id_legislatura` `int64` + `gt(0)`.
   - `id_legislatura_fonte` `Int64` nullable (bruto).
   - `situacao_bruta` nullable; `situacao_normalizada` not-null `isin`.

Consequências:
- `silver_parlamentar` ganha `id_legislatura_fonte`, `situacao_bruta` e
  `situacao_normalizada` e perde `situacao` — quebra de schema em tabela
  ainda não consolidada em produção (Onda 2 não materializada no Gold), sem
  impacto operacional.
- O histórico SCD2 de `dim_parlamentar` passa a comparar Câmara e Senado com
  semântica comum de legislatura e de situação — evitando viés
  Câmara×Senado nos atributos rastreados por RF-11.
- `nao_mapeado` é sinal de vocabulário novo a catalogar: o Data Quality
  Report da Silver contabiliza (via `registros_quarentena` do gate `isin`,
  quando a regra captar) — ver ADR-015.
- O de-para depende do vocabulário real das APIs; uma primeira captura real
  pode trazer valores não catalogados → `nao_mapeado`, e devem ser
  adicionados ao de-para com teste na sequência (ação registrada no
  BACKLOG, Onda 2).

---

<!-- Continue with further ADRs -->

ADR-025
Título: Poder Executivo genérico como órgão do portador CPGF e materialização
inaugural de `dim_unidade_gestora`

Status:
Aceito

Contexto:
O `fact_cartao_cpgf` (ADR-012) exige `id_orgao` e `id_unidade_gestora` NOT
NULL no contrato (gold.py:183). Ao implementarmos a Onda 3 do Gold, dois vazios
de projeto vieram à tona:

1. **A CGU não expõe órgão no grão de cartão.** Cada transação nasce com
   `unidadeGestora.codigo`/`nome` (ADR-010/012), mas não há vínculo direto
   órgão→transação; o portador do CPGF é, por natureza, servidor público
   federal do **Poder Executivo**. Não existe "órgão" no grão para casar por
   chave natural — a `dim_orgao` (seed) só tem CD/SF como casos institucionais.
   A tentação de literal `id_orgao = 3` viola o ADR-022.1
   (resolução por sigla, nunca literal de id).
2. **`dim_unidade_gestor` era schema-only (BACKLOG, Onda 2).** Sem requisito
   funcional, nenhuma fonte tinha sido materializada. Com o fato, a fonte
   existe no grão (a própria CGU) e o contrato exige a FK NOT NULL — a dimensão
   passa a ser necessária e populada pelas UGs observadas.

Decisão:
1. **Poder Executivo genérico por construção (ADR-022.1-compliant).** O seed
   `dim_orgao` ganha `3,Executivo,Poder Executivo,EX,,`. A ponte efêmera
   `cartao_unidade` resolve `id_orgao` por JOIN em `dim_orgao.sigla = 'EX'`
   (mesmo padrão do `desp_orgao`/`emenda_autor_orgao` — sem literal de id).
   Se a sigla `EX` sumir da dimensão (lag/dessincronização), `id_orgao` sai
   NULL na ponte e a transação vai à quarentena `orgao_nao_resolvido`
   (ADR-018/022) — nunca NULL silencioso.
2. **Materialização inaugural de `dim_unidade_gestor`** a partir do grão de
   `silver_cartao` (CGU): distinct por `unidade_gestora_codigo`, chave natural
   composta `(fonte_origem='CGU', codigo)` (ADR-010.3 — nunca codigo isolado),
   `gestao` permanece NULL (campo específico do SIAFI) e o `nome` é consolidado
   por `max`. O `id_orgao` da UG resolve pelo mesmo JOIN `EX`. A dimensão
   passa de schema-only para ativa (BACKLOG Onda 2 → Onda 3).
3. **Contrato e quarentena.** `FactCartaoCpgf` (gold.py) já requer
   `id_unidade_gestora` NOT NULL e `id_fornecedor` nullable. A quarentena por
   construção (ADR-018) cobre `orgao_nao_resolvido`,
   `unidade_gestora_nao_resolvida` e `data_nao_resolvida` (fora do horizonte
   de `dim_data`); fornecedor NULL NÃO gera quarentena — o lag fica observado
   pelos `fk_orphan_pct`/`relationships` do fato (ADR-022.3a).

Consideração rejeitada:
- **Literal `id_orgao = 3` na resolução** (ex.: por `WHERE` na ponte ou
  `join` com valor fixo): viola o ADR-022.1 e cria um cabo de dependência
  invisível entre o SQL e a seed. A resolução por sigla `EX` mantém a paridade
  com `desp_orgao`/`emenda_autor_orgao` e degrada graciosamente para a
  quarentena quando a dimensão regride.

Consequências:
- `dim_unidade_gestor` deixa de ser schema-only e vira modelo Gold executado;
  os builds das demais suítes agora criam uma `silver_cartao` vazia e
  selecionam a dimensão (atualizado nos testes `test_gold_despesa.py` e
  `test_gold_scd2_adr017.py`).
- O seed `dim_orgao` passa a ter três linhas; os testes de regressão dos fatos
  existentes observam `[("CD",1),("SF",2),("EX",3)]`.
- Como a UG da transação alimenta a própria dimensão,
  `unidade_gestora_nao_resolvida` só é alcançada em dessincronização entre
  builds (lag da dimensão), não por ausência na fonte — exatamente o cenário
  de ADR-022.1 coberto por teste.
- `id_fornecedor` NULL é comportamento legal do contrato (ADR-012); quando o
  estabelecimento não tem CNPJ/CPF resolúvel na dim, o fato registra NULL e o
  volume/razão é quantificado pelos testes percentuais `fk_orphan_pct`
  (ADR-022.3a).

---

ADR-026
Título: Fronteira de escrita dbt ↔ Python/ML no Gold Layer (Sprint 5)

Status:
Aceito

Contexto:
A Sprint 4 (ADR-021) deixou como placeholder consciente as 5 tabelas Gold
que dependem de ML/NetworkX — `risk_scores`, `expense_outliers`,
`network_edges`, `network_nodes`, `politician_similarity` — e nenhuma
existe no disco ainda (BACKLOG item 217). ADR-018 estabelece dbt como a
única forma regular de escrita no Gold. RF-07 exige lineage automático
via `dbt docs`. `pyproject.toml` já inclui scikit-learn e NetworkX no
grupo `analytics`; o adapter `dbt-duckdb` instalado suporta materialização
`language: python`, tornando viável — mas não obrigatório — rodar ML dentro
do próprio dbt.

Três opções foram avaliadas:
- **A** — Python escreve em schema intermediário `ml_staging` (DuckDB);
  dbt consome como source e materializa o Gold final via CTAS.
- **B** — Python escreve direto nas 5 tabelas Gold, fora do dbt.
- **C** — Os 5 models viram models dbt `language: python`, rodando
  sklearn/NetworkX dentro do próprio DAG do dbt.

Decisão:
Adotar **Opção A**.
1. Python (`pipeline/analytics/`) escreve **exclusivamente** no schema
   `ml_staging` (DuckDB); nenhum outro processo — Airflow direto, scripts
   ad-hoc, dbt — escreve nesse schema (single-writer, mesmo princípio do
   ADR-018 aplicado ao Gold).
2. dbt consome `ml_staging.*` como `source()` (nova entrada em
   `sources.yml` mapeada para `schema: ml_staging`) e materializa
   `risk_scores`, `expense_outliers`, `network_edges`, `network_nodes` e
   `politician_similarity` como models Gold regulares, com `schema.yml`
   e testes nativos (`not_null`, `relationships` contra
   `dim_parlamentar`/`dim_fornecedor` e `fk_orphan_pct` com
   `severity: warn` — ADR-022.3a).
3. Opção C fica registrada como alternativa avaliada e descartada nesta
   sprint — **não** como item de backlog para POC. Reabertura futura
   exige novo ADR de superseding com justificativa própria.

Consequências:
- Preserva ADR-018 (dbt como single-writer do Gold) e RF-07 (lineage
  completo em `dbt docs`) sem exceção.
- Introduz um hop Python→DuckDB→dbt por tabela — custo aceitável em troca
  de testabilidade dbt-nativa.
- Treino e serialização de modelo (Isolation Forest, KMeans/DBSCAN,
  PageRank/NetworkX) permanecem em Python puro, fora do grafo de lineage
  do dbt — apenas o *output* tabular entra no lineage.
- `ml_staging` exige contrato de schema próprio (mínimo: chaves para join
  com dimensões Gold) — detalhado nos ADRs de features/scores desta mesma
  sprint.
- A entrada `ml_staging` no `sources.yml` do dbt passa a existir (hoje
  inexistente).

---

ADR-027
Título: Fórmulas explícitas dos 5 scores individuais de risco (§9)

Status:
Aceito

Contexto:
ADR-003 formalizou o `risk_index` composto (média ponderada, pesos 0.2
uniformes) mas remeteu os 5 scores individuais a §9/PROJECT_CONTEXT.md
sem fórmula fechada. Cada índice deve ser documentado matematicamente no
`ADR.md` (§9). A Sprint 5 implementa `risk_scores` — sem fórmula por score,
o mesmo score pode ser calculado com semânticas diferentes entre Onda 3
(rede) e Onda 4 (scores), gerando quebra silenciosa de consistência.
Também fecha o ciclo de rastreabilidade do §9: os scores são features
registráveis na Feature Store (ADR-028) e alimentam o `risk_index`.

Nomenclatura adotada:
- `p`: parlamentar; `P`: conjunto de todos os parlamentares.
- `f`: fornecedor; `F_p`: fornecedores do parlamentar `p` no período.
- `v_{p,f}`: valor gasto por `p` com `f` no período; `V_p = Σ_{f∈F_p} v_{p,f}`.
- Normalização Min-Max: `norm(x) = (x − min_X(x)) / (max_X(x) − min_X(x))`
  no universo `X` do período — refeita por execução da Sprint 5
  (estado transitório para `risk_index` de produção, revisada no ADR-029).

Decisão:
1. **`supplier_concentration_score`** = `hhi_p` já formalizado na Onda 3
   (ADR-021, `supplier_concentration`):
   `hhi_p = Σ_{f∈F_p} (v_{p,f} / V_p)²`.
   Score = `norm(hhi_p)` sobre todos os parlamentares do período.
2. **`political_exposure_score`** mede exposição a fornecedores
   compartilhados: para cada fornecedor `f`, `n_f = |{p ∈ P : v_{p,f} > 0}|`
   (número de parlamentares que usam o fornecedor). Para `p`:
   `exposure_p = média_{f∈F_p} (n_f − 1)`. Score = `norm(exposure_p)`.
   (Fornecedor usado por 1 parlamentar → contribuição 0; quanto mais
   compartilhado, maior a exposição.)
3. **`supplier_dependency_score`** mede o quão dependente o fornecedor é
   de poucos parlamentares (concentração por fornecedor — HHI do lado do
   fornecedor, granularidade pendente no BACKLOG item 173):
   `dep_f = Σ_{p∈P} (v_{p,f} / (Σ_{p'∈P} v_{p',f}))²`.
   Para `p`: `dependency_p = média_{f∈F_p} dep_f`. Score = `norm(dependency_p)`.
4. **`expense_anomaly_score`** usa a definição formal de anomalia (§10,
   ADR-002 — ≥2 dos 6 critérios): `a_p = |{despesas d de p : anomalia(d)}| /
   |{despesas de p}|`. Score = `norm(a_p)`.
   O Isolation Forest entra como um dos 6 critérios (score < −0.1,
   contamination = 0.05), não como score isolado — coerente com ADR-002.
5. **`network_influence_score`** = PageRank no grafo bipartido
   parlamentar↔fornecedor (arestas = valor gasto): `pr_p` = valor de
   PageRank do nó parlamentar (NetworkX, Onda 3). Score = `norm(pr_p)`.

Score agregado final (ver ADR-003):
`risk_index_p = Σ_{i=1..5} w_i · score_i(p)`, `w_i = 0.2` (baseline,
revisão na Sprint 5 — ADR-029).

Consequências:
- `risk_scores` (tabela) tem como grão `(período, id_parlamentar)` e as 5
  colunas `{score}_{tipo}` + `risk_index` — fecham §7/§9.
- Cada score vira feature registrável na Feature Store (ADR-028) com
  `fórmula` apontando para esta seção.
- O `expense_anomaly_score` depende da Onda 2 (Isolation Forest) e o
  `network_influence_score` da Onda 3 (PageRank) — ordem de ondas
  coerente com a Onda 4 (scores) consumindo as anteriores.
- Min-Max por período é dependente do universo de dados de cada carga;
  a estabilização dos pesos/controles é responsabilidade do ADR-029.

---

ADR-028
Título: Contrato da Feature Store — `ml_feature` e `registry.yaml` validável

Status:
Aceito

Contexto:
PROJECT_CONTEXT.md §9 documenta que a normalização Min-Max dos scores
e as features associadas devem registrar-se na Feature Store
(`docs/data/ml_feature.md`). Hoje `feature_store/registry.yaml` é um
scaffold vazio (`features: []`), e `ml_feature.md` apenas lista os
campos (nome, descrição, fórmula, origem, tipo, última atualização,
consumidores) sem contrato validável. Sem schema, o primeiro score
calculado na Sprint 5 (Onda 4) nasceria sem features rastreáveis —
violando o propósito do registro (que feature alimenta qual score e de
onde veio).

A Sprint 5 produz features de natureza variada: agregados puros
(`supplier_concentration.hhi`), derivados de ML (Isolation Forest score,
PageRank), composições (`risk_index`) e funções de normalização
(`norm(x)` Min-Max). O contrato precisa distinguir `feature` (valor cujo
grão não persiste em `ml_staging`/Gold) da `função derivada` (fórmula
reutilizada que produz features).

Decisão:
1. **Schema validável em Pydantic** (`pipeline/features.py` —
   `Feature`, `FeatureRegistry`), validando `feature_store/registry.yaml`
   na carga e em testes; os metadados passam a ter fonte única e
   validável (o YAML é a fonte de verdade, não texto livre do md).
2. **Campo `categoria` obrigatório** — enum `FeatureCategoria`:
   `agregado`, `ml`, `composicao`, `funcao`. O registro aceita os 4;
   só `funcao` não persiste em tabela Gold (fórmula reutilizável, ex:
   `minmax`, `regra_anomalia`) — as demais exigem `tabela` de origem.
3. **Campos mínimos por feature** (fecham `ml_feature.md`):
   - `nome` (snake_case, único no registry).
   - `descricao` (português).
   - `formula` (referência a ADR/seção ou expressão).
   - `origem` (camada/tabela fonte — convenção `bronze_*`, `silver_*`,
     `ml_staging.*`, `fact_*`, `calculado`).
   - `tipo` (tipo Python/duckdb).
   - `categoria` (enum acima).
   - `ultima_atualizacao` (data ISO; `null` até ser calculada).
   - `consumidores` (lista de tabelas/models/features que consomem —
     ex: `risk_scores`, `risk_index`).
4. **`registry.yaml` reescrito em formato policial** — parse YAML→Pydantic
   sem transformação manual (o scaffold `features: []` preservará a
   estrutura flat com lista).
5. **Teste obrigatório** (`tests/pipeline/test_features.py`): o registry
   do repo valida no Pydantic e toda feature de `categoria != funcao`
   possui `tabela` não vazia — evita feature órfã.

Consequências:
- Feature Store vira infraestrutura ativa a partir da Onda 1 —
  `pipeline/features.py` + teste; nada de "registro após o cálculo".
- As 5 fórmulas do ADR-027 e o `norm(x)` entram como primeiras entradas
  do registry (`risk_index` como `composicao`, `norm`/`regra_anomalia`
  como `funcao`).
- O contrato reutiliza o padrão Pydantic do projeto (schemas Bronze/
  Silver/Gold) e valida o YAML também em CI.
- `ml_feature.md` passa a referenciar o contrato em vez de ser a fonte
  dos campos.

---

ADR-029
Título: Revisão dos pesos do `risk_index` — quando ocorre e com quais critérios

Status:
Aceito

Contexto:
ADR-003 fixou pesos uniformes w_i = 0.2 (baseline da Sprint 0B) com
revisão prevista para a Sprint 5 "com base em validação empírica". A
Sprint 5 agora está aberta (ADR-026/027/028), mas os dados reais de
despesa/emendas (Sprint 6.5 — validação end-to-end) ainda **não existem
no ambiente**: o DuckDB de produção nunca foi populado. Revisar pesos "na
sprint 5" literalmente significaria calibrar com dados sintéticos/fixture,
cujo sinal não reflete a população real de parlamentares/fornecedores.

Este ADR decide **quando** a revisão ocorre e **quais critérios** ela usa,
antecipando que uma revisão indisciplinada entre as ondas 3 e 4 mudaria a
escala de cada score sem documentação.

Decisão:
1. **Os pesos 0.2 permanecem o baseline durante toda a Sprint 5.**
   `risk_index` é implementado com pesos configuráveis
   (`config/analytics.yaml` → `risk.pesos`, fonte única ADR-008) — a
   composição usa os pesos de config, não constantes no código.
2. **A revisão de pesos (superseding/amendment do ADR-003-029) é um
   evento pós-Sprint 6.5**, não da Sprint 5: efetiva quando existir
   histórico real de pelo menos 1 ciclo completo de carga (período
   ≥ 12 meses com fact_despesa publicado) no DuckDB Gold. Documentado em
   ADR próprio (amendment de ADR-003) com:
   - distribuições empíricas de cada score (norm Min-Max, §9/ADR-027);
   - análise de sensibilidade: variação do `risk_index` per-parlamentar
     por peso (lado robustez);
   - feedback da persona Analista de Controle (validação de face, ranking
     de risco qualitativo contra casos conhecidos).
3. **Regras de transição de peso registradas no ADR**: pesos só mudam por
   ADR de amendment; uma mudança exige (a) nova normalização Min-Max
   recalculara no mesmo período e (b) dataset de scores versionado —
   reprodução de ranking histórico `risk_index` antes/depois para medir o
   impacto na comparação de perfil de risco ao longo do tempo.
4. Enquanto houver pesos configuráveis, **nenhum peso pode ser alterado
   por operação manual** em produção sem ADR aprovado (mesmo princípio de
   ADR-003 "não reajustar contamination sem ADR"; ADR-002).

Consequências:
- Semanticamente, `w_i = 0.2` deixa de ser "temporário até a Sprint 5" e
  passa a ser "baseline vigente até consolidação pós-Sprint 6.5".
- `config/analytics.yaml` ganha a chave `risk.pesos` (validation Pydantic
  vira checklist de DQ); o teste da Onda 4 garante que `sum(pesos) == 1`.
- A Sprint 5 (Onda 4) entrega `risk_scores` completo e estável com o
  baseline — sem risco de rework por calibração prematura.
- A revisão empírica fica amarrada a dado real (não fixture), em linha com
  o fluxo de ADRs que mitigou o erro do ADR-023 (fechamento sem dado real).

---

ADR-030
Título: Materialização e atualização do grafo NetworkX —
`network_edges`/`network_nodes` (Onda 3)

Status:
Aceito

Contexto:
A Onda 3 da Sprint 5 constrói o grafo bipartido parlamentar↔fornecedor
(aresta = valor gasto; nós = parlamentares e fornecedores, com `PageRank`
e centralidade como features). O output alimenta `network_influence_score`
(ADR-027.5) e `politician_similarity` (§7). Conforme ADR-026, o produto do
ML/rede é escrito em Python em `ml_staging` e materializado como models
dbt Gold (`network_edges`, `network_nodes`). Falta decidir a estratégia de
atualização: **recálculo total por execução** vs. **atualização
incremental**.

Características que constrangem a decisão:
- O grafo é **global**: listas/centralidades/PageRank dependem do grafo
  completo do período — não há subgrafo incremental com semântica idêntica
  sem aproximação (PageRank é computado sobre o grafo inteiro).
- DuckDB embarcado (ADR-001): volume da carga parlamentar+fornecedor é
  pequeno (CD ~594 deputados + SF ~81 senadores + fornecedores; arestas na
  ordem de milhares a dezenas de milhares por período) — recálculo total
  tem custo trivial nessa escala.
- Reprodutibilidade RF-12 exige `run_id` por carga; um recálculo total
  chaveado por `run_id` é deterministicamente reproduzível; incremental
  exigiria versionar quantas arestas mudaram e re-convergir centrais
  globais sem garantia de idempotência simples.

Decisão:
1. **Recálculo total do grafo por execução do pipeline**, chaveado por
   `(run_id, periodo)` nas tabelas `ml_staging.network_edges`/
   `ml_staging.network_nodes` — sem estado incremental persistido entre
   execuções. A DAG da Sprint 5 ganha task Python `executar_ml_rede`
   (após `executar_silver`), que re-le o Gold (`fact_despesa`,
   `dim_parlamentar`, `dim_fornecedor`), reconstrói o grafo completo e
   escreve as duas tabelas de staging.
2. **Models dbt** `network_edges`/`network_nodes` (Gold) fazem clean-slate
   sobre `ml_staging` do run id da execução, sem incrementar — consistentes
   com ADR-026 e com o materializado `table` das demais analytics (§7,
   ADR-021). O build Gold é `dbt build` do run corrente.
3. **Volume como gate futuro**: o parâmetro de corte para reavaliar
   incremental é quando o custo de um recálculo (ou o tempo da DAG) exceder
   limite definido empiricamente — registrado em `config/analytics.yaml`
   (`rede.limite_ares_tas_recorte` — arestas acima do qual o recálculo
   dispara alerta de custo no DQ Report, sem bloquear). Passou do limite
   com notificação → ADR de superseding reavalia incremental (não é
   decisão às cegas).
4. **Sem persistência entre execuções de grafo em memória**: cada execução
   reconstrói em memória exclusivamente no processo da task; nenhuma
   versão anterior de `network_*` é "atualizada" — substituição íntegra via
   `run_id` mais recente.
5. **`politician_similarity`** deriva do mesmo grafo do run corrente
   (comunidades/similaridade), compartilhando o staging — mesmo ciclo de
   vida (recálculo total).

Consequências:
- `network_influence_score` (ADR-027.5) fica deterministicamente
  reproduzível por `run_id` — alinhado à RF-12 e ao padrão idempotente que
  já adotamos no SCD2 e na aggregation (ADR-020, ADR-021).
- Custo por execução aceito: a escala atual torna incremental um
  desperdício de complexidade sem ganho de correção semântica (PageRank
  global); o limite de arestas oferece disjuntor futuro dirigido por dado.
- Tabelas `network_edges`/`network_nodes` entram no lineage do dbt docs
  (RF-07) via ADR-026 — staging Python fora do lineage, resultado dentro.
- A nota de custo no DQ Report serve de insumo objetivo ao futuro ADR de
   superseding (evita a repetição do padrão de fechamento sem dado real —
   lição do ADR-023).

---

ADR-031
Título: Promoção de `data_quality_report` (Silver) à Gold para o
`GET /qualidade/relatorio`

Status:
Aceito

Contexto:
`ADR-015` (Sprint 3) persistiu o Data Quality Report em tabela estruturada
`data_quality_report` na Silver e previu que `GET /qualidade/relatorio`
(Sprint 6) consumiria a tabela "diretamente". `ADR-026` (Sprint 5),
posterior, fixou a fronteira de leitura da API: **read-only sobre o Gold**,
nunca Bronze/Silver/`ml_staging`. Ao abrir a Onda 3 da Sprint 6, constatamos
um buraco: `data_quality_report` não têm model Gold — é apenas source
declarada em `sources.yml` — e o endpoint previsto não teria Gold para ler.
Havia, portanto, tensão entre dois ADRs aceitos: "consumir diretamente"
(ADR-015) vs. "Gold-only" (ADR-026).

Decisão:
1. **Promover `data_quality_report` à Gold** com model dbt regular
   (`pipeline/gold/models/control/data_quality_report.sql`) que consome a
   source `silver.data_quality_report` e a materializa como Gold — o mesmo
   mecanismo da Opção A do ADR-026 (dbt consome source e materializa o Gold;
   precedente forte: `pipeline_runs` já é Gold e lê Bronze parquet no build,
   ADR-019). Nenhuma métrica nova: as colunas do relatório já são
   formalizadas pelo ADR-015 (contagem válidos/quarentena/dedup, regras
   violadas, percentual de nulos críticos, timestamp).
2. **`GET /qualidade/relatorio` lê a Gold**, como todo endpoint da Sprint 6.
   A API continua incapaz de ler a Silver (ADR-026 inalterado).
3. Esta decisão **supersede a interpretação literal de "consumir
   diretamente"** do ADR-015: "diretamente" passa a significar "diretamente
   da Gold promovida, sem reprocessamento nem parsing de HTML" — a fronteira
   de camada é a do ADR-026, mais recente.

Consequências:
- `data_quality_report` entra no lineage do `dbt docs` (RF-07) como os demais
  models Gold; a Silver continua sendo o produtor do relatório
  (`pipeline/silver.py`, single-writer).
- O contrato do endpoint herda as colunas do ADR-015; `regras_violadas`
  (lista serializada em JSON string na Silver) é desserializada no consumo.
- `schema.yml` do novo model declara `not_null` de `run_id`/`tabela`/
  totais; o selo de contrato pipeline→Gold→API (`tests/integration`) passa a
  construir o model no dbt real.
- Silver mantém-se inacessível à API; qualquer outro endpoint futuro que
  precise de dado Silver deve repetir o mesmo padrão de promoção, não
  estreitar a fronteira.

---

ADR-032
Título: Endpoints agent-ready (RF-05) — JSON semântico agregado, não espelho
dos endpoints de negócio

Status:
Aceito

Contexto:
A RF-05/§11 exige endpoints agent-ready (`/agent/parlamentar/{id}`,
`/agent/fornecedor/{cnpj}`, `/agent/anomalias`, `/agent/context`) que
retornem "JSON semântico para consumo por LLMs" — e a CU-07 define
`/agent/context` como "contexto semântico agregado". Ao abrir a Onda 4
constatamos que **não havia decisão sobre a composição desses payloads**:
`docs/architecture/ai_architecture.md` é um stub com as rotas; §11 não
descreve contrato. A matéria-prima está definida em artefatos separados:
Camada Semântica §8 (métricas com fórmula oficial, "nunca recalcular
inline"), §9/ADR-027 (5 scores + risk_index), ADR-028 (Feature Store).
Ondas 1–3 só leram Gold já existente; aqui a composição do payload é
decisão nova — este ADR a formaliza antes de implementar.

Decisão:
1. **Agent-ready ≠ espelho dos endpoints de negócio.** Os 4 endpoints
   retornam JSON aninhado, com rótulos semânticos (nomes legíveis, métricas
   nomeadas conforme a Camada Semântica §8, datas ISO) — desenhado para um
   LLM formular respostas, não para um componente chamar outra API.
2. **Mesma fronteira das Ondas 1–3:** leitura read-only do Gold (ADR-026).
   Métricas da §8 que dependem de fato são **agregados SQL sobre o Gold já
   materializado** (`fact_despesa`, `supplier_concentration`, `risk_scores`,
   `expense_outliers`) — mesmo padrão do `/fornecedores/{cnpj}` da Onda 2.
   Proibido recalcular análise/ML por request (ADR-030); o vocabulário
   segue a §8/§9/ADR-028.
3. **Escopo das métricas:** apenas as computáveis sobre tabelas Gold que
   existem hoje. `taxa_ausencia`/`indice_alinhamento` (§8) ficam **fora** —
   dependem de `fact_presenca`/`fact_votacao`, ainda inexistentes no Gold.
   `hhi` vem de `supplier_concentration` (grão ano×parlamentar); scores de
   `risk_scores` (período mais recente do parlamentar).
4. **Composição dos payloads** (definição exata nos schemas
   `api/schemas/agent.py`, `extra="forbid"`):
   - `/agent/parlamentar/{id}`: perfil vigente do SCD2 (ADR-020) +
     métricas §8 do parlamentar (`total_gasto`, `gasto_medio`,
     `num_transacoes`, `num_fornecedores`, `valor_maximo`, `valor_mediano`,
     `percentil_95`) + `hhi` recente + risco (`risk_index` e os 5 scores do
     período mais recente) + contagem de anomalias + top-5 fornecedores por
     valor.
   - `/agent/fornecedor/{cnpj_cpf_valor}`: perfil (`dim_fornecedor`) +
     agregados (`total_recebido`, `gasto_medio`, `valor_maximo`,
     `num_transacoes`, `num_parlamentares`) + top-5 parlamentares por valor.
     CPF exposto apenas como hash HMAC (ADR-011).
   - `/agent/anomalias`: **resumo agregado**, não a lista crua paginada —
     total, contagem por ano, contagem por critério disparado e top-10 por
     zscore (com nome do parlamentar).
   - `/agent/context`: **agregação sistêmica** (CU-07): métricas globais do
     Gold (total gasto, nº despesas/fornecedores/parlamentares/anomalias),
     períodos com dados, resumo do último relatório de qualidade e da última
     execução do pipeline. É o "retrato" pedido antes de investigar um caso.

Consequências:
- Payloads agent-ready e endpoints de negócio evoluem de forma
  independente: mudar um não quebra o outro (contratos próprios
  `extra="forbid"`).
- Métricas §8 permanecem com fonte única na tabela oficial (§8), mesmo
  quando re-materializadas por request como agregação sobre o Gold —
  nenhuma fórmula é reinventada no repo.
- `fact_presenca`/`fact_votacao` futuras podem ampliar o payload via
  amendment deste ADR, sem mudar a fronteira.
- Suíte: `tests/api/test_agent.py` + selo de contrato estendido validam os
  4 payloads contra o dbt real (200 honesto com staging/agregados vazios,
  bind das colunas de `risk_scores`/`supplier_concentration`/etc.).

---

ADR-033
Título: Pseudonimização de CPF aplicada na Silver (transform), não na Gold
(UDF) nem na Bronze

Status:
Aceito — corretivo do prompt de QA (Sprint 6.5); refina ADR-004/ADR-011.

Contexto:
ADR-004/011 definiram que CPF de fornecedor PF é pseudonimizado com
HMAC-SHA256, mas não fixaram a **camada** onde o hash é aplicado. Na
implementação, o hash acontecia na Gold via um plugin dbt (`pipeline/
gold/hmac_udf.py`, UDF `hmac_sha256_cpf` registrada no `profiles.yml`).
O prompt de QA apontou duas fragilidades dessa materialização no
modelo SQL:

1. Cada `JOIN`/`WHERE` textual comparando a coluna hasheada precisava
   chamar a UDF — re-hash no ponto de consumo, sujeito a inconsistência
   se a chave do ambiente não estivesse presente no build.
2. Os consumidores leem o dado "como está" na Gold; qualquer caminho
   analítico que não chamasse a UDF exporia o CPF cru.

Decisão:
1. **A pseudonimização passa a ocorrer uma única vez, na Silver, dentro
   do `transform.py` de cada fonte** (`pipeline/pseudonymize.py`:
   `pseudonymize_cpf`/`pseudonymize_cpf_column`). O valor hasheado é o
   que chega a `silver_despesa`/`silver_cartao`/`silver_emenda` e,
   portanto, o que o Gold consome.
2. **Gold repassa, nunca re-hasha.** Os models `dim_fornecedor`,
   `desp_fornecedor` e `cartao_fornecedor` fazem JOIN por igualdade
   direta do valor já hasheado; a UDF `hmac_sha256_cpf` e o plugin
   `hmac_udf.py` foram removidos (e o registro correspondente em
   `profiles.yml`).
3. **A chave é lida de `EnvSettings.cpf_hmac_secret_key` com leitura
   preguiçosa** (`_chave_ativa` com fail-fast): só é exigida quando o
   lote contém ao menos um CPF — cargas CNPJ-only não dependem do env.
4. **Bronze permanece com o dado bruto equivalente-público** (CPF de
   fonte pública) e a Silver é a fronteira de pseudonimização; o Gold e
   a API só expõem o hash (ADR-026 read-only preservado).

Condições de acesso ao Bronze (exigência do prompt de QA, BUG-002):
- **Acesso restrito — satisfeito.** O MinIO (object storage da camada
  Bronze) é exposto apenas em `127.0.0.1:9000/9001` (docker-compose.yml),
  nunca em interface pública; a rede interna `observatorio-net` isola o
  acesso entre serviços e `no-new-privileges` reduz privilégios do
  container. Nenhuma rota externa publica o MinIO.
- **Criptografia em repouso — NÃO implementada (dívida consciente).** O
  volume `minio_data` não tem criptografia em repouso configurada. A
  mitigação atual é o próprio pseudonimização na Silver + acesso restrito;
  criptografia em repouso (server-side do MinIO ou disco cifrado) fica
  registrada como item explícito no `BACKLOG.md` (Sprint 6.5).

Consequências:
- Fonte única de hash: a chave é lida uma vez por transform, com
  determinismo para os testes (seed do Gold carrega o hash esperado
  calculado com a mesma chave de teste).
- Remoção do acoplamento dbt↔UDF: builds do Gold não dependem de
  registro de plugin nem de `CPF_HMAC_SECRET_KEY` no ambiente de
  build.
- `dim_fornecedor.cnpj_cpf_valor` continua "CNPJ em claro OU hash do
  CPF OU NULL" (ADR-011) — sem hash-de-hash.
- Chave continua em `EnvSettings.cpf_hmac_secret_key` (ADR-004) com o
  mesmo plano de rotação; rotação exige re-materializar a Silver, não
  o Gold.
- Segurança do Bronze repousa em defesa em profundidade parcial:
  restrição de rede (satisfeita) + pseudonimização na Silver (satisfeita);
  a criptografia em repouso é débito conhecido e rastreado no BACKLOG.

---

ADR-034
Título: Estratégia de execução diária do pipeline — cron na VPS Oracle (sem CD via GitHub Actions)

Status:
Aceito

Contexto:
A Sprint 9 exige que o pipeline seja executado diariamente em
produção (PROJECT_CONTEXT.md §13, sprint_rules — "GitHub Actions
(CI/CD com execução diária)"). Duas opções foram avaliadas:

- Opção A — Schedule no GitHub Actions (`on: schedule`), rodando o
  pipeline completo em runner efêmero do GitHub.
- Opção B — Cron/systemd timer na própria VPS Oracle Cloud, disparando
  `docker compose --profile pipeline` localmente.

ADR-007 já decidiu explicitamente que "Pipeline sempre executa na
Oracle Cloud" e que o perfil `pipeline` (postgres + airflow-webserver
+ airflow-scheduler) é ativado apenas durante a execução do pipeline
diário, não continuamente. A Opção A contradiria essa decisão sem
justificativa nova: runners do GitHub Actions são efêmeros e sem
estado — não têm acesso a `./data` (Bronze/Silver/Gold persistidos em
DuckDB local) nem ao `minio_data` (volume Docker local), exigindo
transporte desses dados a cada execução (upload/download de
artefatos), o que reescreveria a estratégia de persistência já
implementada nas Sprints 2-4 sem ganho real.

Decisão:
1. Adotar a Opção B: `systemd timer` (preferencial sobre `crontab`,
   por integração nativa com logs via `journalctl` e melhor
   tratamento de falhas) na VPS Oracle, agendado para horário fixo
   diário (ex: 03:00 America/Sao_Paulo, fora do horário de pico de
   consultas à API/dashboard).
2. O timer executa uma sequência controlada por script
   (`scripts/run_pipeline_daily.sh`):
   a. `docker compose --profile pipeline up -d postgres
      airflow-webserver airflow-scheduler`
   b. Aguarda o scheduler disparar e concluir o DAG diário
      (`pipeline/dags/pipeline_dag.py`), com timeout configurável.
   c. `docker compose --profile pipeline down` ao término — os
      containers do perfil `pipeline` não ficam residentes,
      preservando o modelo de custo/recursos de ADR-007.
3. Dados persistidos (`./data/bronze`, `./data/silver`, `./data/gold`,
   `minio_data`) sobrevivem ao ciclo up/down, pois são volumes Docker
   montados fora dos containers efêmeros do perfil `pipeline`.
4. GitHub Actions permanece restrito a **CI** (testes, lint, secret
   scanning — Gates 1-4 da Sprint 9), sem responsabilidade de
   execução do pipeline ou de deploy automatizado a cada push. Não há
   CD no sentido estrito: a API/dashboard já rodam continuamente na
   VPS (ADR-007); a "execução diária" exigida pelo roadmap é batch
   agendado, não deploy.

Consequências:
- Nenhuma mudança na estratégia de persistência Bronze/Silver/Gold
  (ADR-001, ADR-007) — dados continuam locais à VPS.
- **O DAG deve declarar `schedule=None`** (sem `schedule_interval`): o
  agendamento é exclusivamente o timer systemd (script despausa + dispara
  o DAG). Com `schedule="@daily"` haveria DOIS relógios independentes
  (systemd + scheduler interno do Airflow) competindo e duplicando
  execuções — falha observada no backfill de 22/08/2026 e corrigida no
  `pipeline/dags/pipeline_dag.py` (ver teste `test_dag_configuracao_basica`).
- `scripts/run_pipeline_daily.sh` e a unit `systemd`
  correspondente (`observatorio-pipeline.timer` /
  `observatorio-pipeline.service`) passam a ser artefatos de infra
  versionados em `infra/`, com provisionamento documentado em
  `infra/cloud-config.yaml` e/ou guia de deploy do README.
- Falhas na execução diária exigem monitoramento externo ao GitHub
  Actions (o timer roda fora do GitHub) — observabilidade via
  `structlog` + logs do `systemd`/`journalctl`; alertas automáticos
  continuam fora do escopo do MVP (backlog futuro, já registrado em
  README §IV).
- GitHub Actions (`pipeline.yml`) precisa ser renomeado/reestruturado
  para refletir seu escopo real de CI (ex: `ci.yml`), evitando o nome
  `pipeline.yml` sugerir execução do pipeline de dados — ajuste a ser
  feito no item 1 da Sprint 9.
- Se o escopo evoluir para múltiplas VPS/réplicas, o cron local deixa
  de ser suficiente e exigiria um orquestrador externo - não é
  necessidade do MVP.

---

ADR-035
Título: Orquestração das ondas de ML no DAG - build Gold em duas fases
(core → analytics) com etapa Python entre elas

Status:
Aceito

Contexto:
O DAG `observatorio_pipeline` encadeava apenas bronze → silver →
gold(dbt). Os pontos de entrada das ondas de ML (`executar_carga_outliers`,
`executar_carga_ml_rede`, `executar_carga_ml_risco`) nunca eram invocados:
a task de Gold garantia o schema `ml_staging` VAZIO antes do build e o dbt
materializava os cinco models que leem `source('ml_staging', ...)` sobre
staging sempre vazio. Resultado observado em produção (ago/2026):
`expense_outliers`, `network_nodes`, `network_edges`,
`politician_similarity` e `risk_scores` nasciam vazias a cada execução -
páginas de Anomalias/Rede/Risco exibiam zero, e o "1 nó" da página de Rede
era o grafo sem arestas. Não era parâmetro de modelo: era fio de
orquestração solto (os docstrings das cargas já diziam "o ponto de entrada
da DAG" - a task é que não existia).

Decisão:
1. Dividir o build do Gold em DUAS fases com seletores dbt explícitos:
   `executar_gold_core` (`dbt build --exclude` dos cinco models analytics -
   dimensões, fatos e agregados puro-SQL como `supplier_concentration`
   permanecem aqui) e `executar_gold_analytics` (`dbt build --select` dos
   cinco models que leem `source('ml_staging', ...)`).
2. Nova task `executar_analytics` ENTRE as duas, chamando
   `pipeline/analytics_stage.executar_etapa_analytics(run_id)` - módulo
   compartilhado também por `scripts/run_e2e_local.py`. Lê o Gold core
   materializado (`fact_despesa`, `dim_data`, `supplier_concentration`)
   em modo read-only e escreve EXCLUSIVAMENTE em `ml_staging`, na ordem de
   dependência Onda 2 → 3 → 4.
3. Fronteira ADR-026 PRESERVADA: Python single-writer de `ml_staging`;
   dbt apenas consome como source; API segue read-only sobre o Gold.
   Nenhuma premissa anterior é violada - este ADR formaliza o fluxo que o
   ADR-026 (Opção A) já presumia ("os scripts de ML rodam como etapa
   separada") e que não havia sido cabeado.
4. Sem fatos promovidos, a etapa encerra sem escrever; os models analytics
   são materializados vazios (mesmo contrato da Fase 1 de test_gold_risk).
5. Guardrail: após o build analytics, `alertar_analytics_vazio` registra
   warning estruturado quando existem fatos no Gold mas alguma tabela
   analítica ficou vazia (sintoma exato do bug original).

Consequências:
- Cadeia passa a ser bronze >> silver >> gold_core >> executar_analytics
  >> gold_analytics; `tests/pipeline/test_dag.py` atualizado para as cinco
  tasks e a nova ordem.
- PageRank/similaridade passam a rodar a cada execução diária (recálculo
  total do ADR-030) - escala atual validada no backfill de ago/2026 (~9 mil
  despesas em segundos); o disjuntor de custo futuro permanece o ADR-030.
- `scripts/run_e2e_local.py` espelha as duas fases + etapa ML, então o E2E
  volta a validar o produto analítico completo, não só o relacional.
- Falha na etapa ML derruba apenas `executar_gold_analytics`; o Gold core
  (fatos/dimensões consumidos pelos endpoints de negócio da API) permanece
  com a última execução íntegra.

---

ADR-036
Título: Landing page institucional na raiz do domínio; Streamlit movido
para `/app/`

Status:
Aceito — amenda o roteamento definido em ADR-007 (decisão #2) e
PROJECT_CONTEXT.md §5/§11

Contexto:
ADR-007 (decisão #2) e PROJECT_CONTEXT.md §5 fixaram `/` (raiz) →
Streamlit como roteamento do Nginx. Na Sprint 10, uma landing page
estática (`site/index.html`) foi adicionada como vitrine institucional
do case para a banca avaliadora, servida pela raiz do domínio
(`observatorio-parlamentar.com.br/`), e o Streamlit foi movido para o
subcaminho `/app/` (`--server.baseUrlPath=/app` no container, WebSocket
via `proxy_http_version 1.1` + `Upgrade`/`Connection` no Nginx). Essa
mudança foi implementada e registrada em CHANGELOG.md, mas nunca
formalizada como ADR nem refletida em PROJECT_CONTEXT.md — divergência
identificada em auditoria de Revisor Técnico (Sprint 10, pós-release).

A landing page é puramente estática: não faz nenhuma chamada a `/api/`
nem a qualquer dado do Gold/Semantic Layer (auditado — nenhuma
ocorrência de `fetch(`, `XMLHttpRequest` ou `/api/` no HTML). Portanto
não fere a decisão de fundo do ADR-007/§5 ("Streamlit como camada de
apresentação exclusiva" refere-se à apresentação de *dados*, não à
existência de uma página de apresentação do projeto em si) — mas o
texto literal dos dois documentos ficou desatualizado.

Decisão:
1. Manter a landing page estática na raiz (`/`), servida diretamente
   pelo Nginx a partir de `/var/www/site` (sem upstream, sem proxy) —
   menor superfície de ataque possível para essa rota.
2. Streamlit passa a viver em `/app/` (com redirect 301 de `/app` para
   `/app/`), mantendo o Nginx como único reverse proxy na porta 443,
   conforme já decidido em ADR-007 (decisão #2 é amendada apenas no
   mapeamento de caminho, não na arquitetura de proxy único).
3. `/api/`, `/docs` e `/openapi.json` continuam roteados para a
   FastAPI sem alteração.
4. Amendar ADR-007 (decisão #2) e PROJECT_CONTEXT.md §5/§11 para
   refletir o novo mapeamento:
   - `/` (raiz) → landing estática (Nginx, sem upstream)
   - `/app/` → Streamlit (porta 8501)
   - `/api/`, `/docs`, `/openapi.json` → FastAPI (porta 8000)
   - `/minio/` → **não exposta** publicamente (ver nota de segurança
     no próprio `nginx/default.conf`; console MinIO restrita a
     `127.0.0.1:9001` + túnel SSH — atualização adicional em relação
     ao ADR-007 original, que prescrevia `/minio/` via proxy)

Consequências:
- Nenhuma mudança de código adicional é necessária — este ADR apenas
  formaliza uma decisão já implementada e testada em produção.
- PROJECT_CONTEXT.md §5 (diagrama de arquitetura) e §11 (se citar
  URLs) devem ser atualizados na próxima rodada de Documentador para
  citar `/app/` em vez de `/` para o dashboard.
- Links/documentação voltados à banca avaliadora (README) devem usar
  `observatorio-parlamentar.com.br/app/` ao referenciar o dashboard.
- Qualquer novo serviço de apresentação (ex: segunda landing page,
  status page pública) deve seguir o mesmo padrão: estático e servido
  direto pelo Nginx quando não precisar de dado dinâmico, evitando
  proxy_pass desnecessário.

---

ADR-037
Título: Deploy automático via GitHub Actions com self-hosted runner na VPS

Status:
Aceito

Contexto:
O projeto necessitava de deploy automático a cada merge na branch principal.
As alternativas avaliadas foram: (1) deploy via SSH-action a partir do
GitHub Actions cloud, (2) webhook simples na VPS, e (3) self-hosted runner
na VPS. A opção (1) esbarra no firewall da Oracle Cloud (Security List não
permite tráfego SSH de IPs externos sem configuração manual da VCN). A
opção (2) exigiria expor um endpoint HTTP na VPS e manter um servidor
webhook customizado. A opção (3) elimina a necessidade de portas externas
e permite que o workflow execute localmente na VPS.

Decisão:
1. Utilizar self-hosted runner (label: self-hosted, linux, arm64) rodando
   como serviço systemd na VPS, executado pelo usuário `opc` (nunca root).
2. O workflow `deploy.yml` dispara exclusivamente no evento `push` para
   `main` (não `pull_request`), garantindo que apenas merges aprovados
   disparam deploy.
3. Branch protection configurada em `develop` e `main` exigindo:
   - Status checks obrigatórios: Gitleaks, Ruff, pytest
   - Review obrigatório (≥1 aprovação)
   - Dismiss stale reviews ativado
   - `main` com enforce_admins (sem bypass para admins)
4. Runner registrado como GitHub App com permissão read-only de código
   (deploy key com write para push, mas o runner apenas faz pull).

Consequências:
- Deploy não depende de portas externas abertas na Oracle Cloud, eliminando
  superfície de ataque de rede.
- Self-hosted runner em repo público tem risco conhecido: workflows maliciosos
  poderiam executar código na VPS. Mitigado por: (a) trigger exclusivo em
  `push` a branches protegidas, (b) branch protection com review obrigatório,
  (c) runner como usuário não-privilegiado (`opc`).
- Runner requer manutenção: atualizações do GitHub Actions Agent devem ser
  monitoradas (o serviço reinicia automaticamente após updates).
- O diretório `observatorio-parlamentar.old` foi removido após validação de
  que nenhum segredo ou dado não versionado foi perdido.

---

ADR-038
Título: Padronização de motor de gráficos no dashboard — Altair + Plotly

Status:
Aceito

Contexto:
O dashboard hoje mistura `st.bar_chart` (default Streamlit, sem tema),
`matplotlib` inline (páginas 06 e 08) e Altair isolado (só página 11,
com estilo duplicado). Resultado: identidade visual inconsistente entre
páginas e nenhum reaproveitamento de tema. Adicionalmente, `ui.py` está
em 62% de cobertura — abaixo da média do projeto (93,53%) — e é o
módulo mais frágil frente ao gate de 80% (`fail_under`, `pyproject.toml`);
qualquer expansão de superfície de código sem teste correspondente arrisca
derrubar o gate.

Decisão:
1. Altair como padrão para gráficos estatísticos (rankings, séries
   temporais, barras) — já em produção na página 11, zero dependência
   nova.
2. Plotly como complemento cirúrgico, restrito a dois casos onde Altair
   é fraco: grafo de rede interativo (página 06) e gráfico radar
   (página 08). Nova dependência: `plotly>=5.22.0` no extra `dashboard`
   do `pyproject.toml` — nunca hardcoded em Dockerfile (ADR-006).
3. `dashboard/charts.py` — novo módulo com builders tematizados,
   consumido por 100% dos gráficos estatísticos do dashboard.
4. ECharts avaliado e descartado: visualmente competitivo, mas wrapper
   JS menos maduro no ecossistema Streamlit — motor duplo (Altair +
   ECharts) aumentaria a superfície de manutenção sem ganho
   proporcional para um projeto solo.
5. `matplotlib` permanece como dependência — **não é substituído**.
   Após a migração dos usos em gráficos (páginas 06 e 08, itens 2 e
   3), seu único uso remanescente é a exportação de tabelas em PDF
   (`ui.py`), fora do escopo de gráficos interativos desta decisão.
6. Página 06 (rede) continua renderizando sobre `network_nodes`/
   `network_edges` já materializados em Gold (ADR-030) — zero
   recálculo por request, tetos de performance do Gate 3/Sprint 7
   preservados; só o motor de renderização muda.

Consequências:
- +1 dependência (`plotly`) no extra `dashboard`.
- `dashboard/charts.py` passa a ser dependência de `ui.py` e de todas
  as páginas 02–07, 11.
- Migração de 100% dos gráficos fora da paleta é entregável
  obrigatório da Onda 2.
- Cobertura de `charts.py` (novo) e da superfície tocada em `ui.py`/
  `06_rede.py`/`08_ml.py` precisa de `AppTest` correspondente.

---

ADR-039
Título: Landing page consome dados agregados via API em runtime
(emenda ao ADR-036)

Status:
Aceito

Contexto:
O ADR-036 fixou a landing como estática (sem `fetch`, sem `/api/`),
justificando isso como redução de superfície de ataque. Na prática,
isso significa que o "Panorama" da landing mostra um retrato manual,
imutável entre re-gerações — hoje desatualizado (`ago/2026 · 8.983
despesas · R$ 4,57 mi`, quando produção já passa de 3,6 mi registros /
R$ 608 mi). Para um projeto cuja proposta de valor é justamente
transparência de dados públicos, uma landing institucional com números
defasados é uma tensão direta com o propósito do produto — e exigiria
disciplina manual recorrente (re-gerar o HTML a cada atualização
relevante do Gold) que não escala e tende a ficar esquecida.

Uma tentativa de implementação (`d0edcc1`, revertida) já provou o
caminho tecnicamente viável: landing e API estão na mesma origem
(`observatorio-parlamentar.com.br/` e `/api/` roteados pelo mesmo
Nginx), então não há problema de CORS; o rate limit já existente em
`/api/` (`10r/s` por IP, burst 20) cobre a rota sem configuração
adicional.

Decisão:
1. A landing passa a buscar dados via `fetch('/api/agregacoes/por-uf')`
   e `/por-partido` no carregamento da página, populando o Panorama
   com números reais do Gold.
2. **Fallback estático obrigatório** — se o fetch falhar (API
   indisponível, erro de rede, timeout), a landing mantém o conteúdo
   estático atual como conteúdo de fallback, nunca uma tela quebrada
   ou vazia. Isso preserva a landing como vitrine funcional
   independentemente do estado da API.
3. Superfície de ataque: a landing passa a depender do endpoint
   `GET /agregacoes/*`, que é **somente leitura, público, já exposto**
   para o dashboard consumir — não abre nenhuma rota nova, nenhum
   método de escrita, nenhuma superfície que já não existisse. O rate
   limit por IP já protege contra abuso. Avaliação: o incremento de
   risco é marginal frente ao ADR-007 original (API já pública), e não
   justifica manter dado desatualizado como troca.
4. Timeout curto no fetch (3s) para não degradar a percepção de
   carregamento da landing caso a API esteja lenta/fora.
5. `ADR-036` item 1 ("landing servida sem upstream, sem proxy")
   permanece verdadeiro para o **HTML/CSS/JS estático em si** — o
   Nginx continua servindo a landing diretamente de `/var/www/site`,
   sem proxy. O que muda é que o **JS da própria página**, já no
   navegador do usuário, faz uma chamada cliente-side à API pública
   — não é o Nginx proxying a landing através da API.

Consequências:
- Landing sempre mostra dados atuais do Gold, sem depender de
  re-geração manual.
- Fallback estático precisa ser mantido sincronizado periodicamente
  mesmo assim (para o caso de API fora do ar por período prolongado)
  — mas deixa de ser a fonte principal, só rede de segurança.
- Landing ganha uma dependência funcional (não crítica, dado o
  fallback) da API estar no ar.
- `site/index.html` deixa de ser 100% estático em sentido estrito
  — precisa de nota clara nisso em qualquer auditoria futura de
  superfície de ataque.
- OG image continua sendo gerada manualmente (esse artefato é para
  preview em redes sociais, não pode ser dinâmico por natureza do
  protocolo Open Graph).

---
