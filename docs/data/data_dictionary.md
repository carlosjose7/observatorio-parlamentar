# data_dictionary.md
# Plataforma de Inteligência Parlamentar Brasileira — Dicionário de Dados
 
> Este documento é referenciado por ADR-002 e PROJECT_CONTEXT.md §10,
> mas não existia como artefato até esta versão. Estrutura inicial —
> a ser preenchida em detalhe durante a Sprint 1 (Modelagem de Dados).
 
---
 
## 1. Propósito
 
Documentar, para cada tabela do Data Warehouse (Bronze/Silver/Gold),
os campos abaixo — conforme exigido em `data_catalog`:
 
- Nome da tabela
- Descrição
- Origem
- Frequência de atualização
- Chave primária
- Chaves estrangeiras
- Owner
- Regras de qualidade
- Linhagem
 
Este dicionário é gerado/atualizado automaticamente ao final do
pipeline (ver `documentation`), mas mantém aqui uma versão de
referência versionada em Git.
 
---
 
## 2. Catálogo de Tabelas — Gold Layer (Sprint 1)

> Substitui a versão resumida da Sprint 0A/0B. Cobre o modelo
> dimensional completo de PROJECT_CONTEXT.md §7, incluindo as
> dimensões institucionais introduzidas em ADR-010 e o schema
> revisado de `dim_fornecedor` (ADR-011).
>
> **Schema físico por camada (ADR-042):** `Bronze` = Parquet/MinIO
> (sem DuckDB) · `Silver` = schema `silver` · `Gold` = schema `gold`
> · `Gold (controle)` = exceção, permanece em `main`
> (`data_quality_report` — única tabela; ADR-015).

| Tabela | Camada | Origem | Frequência | Chave Primária | Owner |
|---|---|---|---|---|---|
| `bronze_camara_despesas` | Bronze | API Câmara dos Deputados | Diária | — (raw) | Engenheiro de Dados |
| `bronze_senado_despesas` | Bronze | API Senado Federal | Diária | — (raw) | Engenheiro de Dados |
| `bronze_cgu_emenda` | Bronze | API CGU (emendas) | Diária | — (raw) | Engenheiro de Dados |
| `bronze_cgu_cartao` | Bronze | API CGU (cartões CPGF) | Diária | — (raw) | Engenheiro de Dados |
| `dim_parlamentar` | Gold | Silver consolidado | Diária | `id_parlamentar` + `surrogate_key` | Engenheiro de Dados |
| `dim_fornecedor` | Gold | Silver consolidado | Diária | `cnpj_cpf_valor` + `tipo_documento` | Engenheiro de Dados |
| `dim_orgao` | Gold | Estático/curado | Sob demanda | `sigla` | Engenheiro de Dados |
| `dim_unidade_gestora` | Gold | CGU (`silver_cartao`) | Diária | (`fonte_origem`, `codigo`) | Engenheiro de Dados |
| `fact_despesa` | Gold | Silver consolidado | Diária | `id_despesa` | Engenheiro de Dados |
| `fact_emenda` | Gold | Silver consolidado | Diária | `id_emenda` | Engenheiro de Dados |
| `fact_cartao_cpgf` / `fact_cartao_cpgf_quarantine` | Gold | Silver consolidado | Diária | `id_transacao` / `id` (CGU) | Engenheiro de Dados |
| `pipeline_runs` | Gold (controle) | Airflow | A cada execução | `run_id` | Engenheiro de Dados |
| `risk_scores` | Gold | Analytics (Sprint 5) | Diária (pós-batch) | `id_parlamentar` + `data_sk` | Cientista de Dados |

### 2.1 dim_orgao

| Campo | Tipo | Nulos | Descrição |
|---|---|---|---|
| `id_orgao` | BIGINT | 0% | PK surrogate |
| `poder` | VARCHAR | 0% | `Legislativo` \| `Executivo` \| `Judiciário` |
| `instituicao` | VARCHAR | 0% | Nome completo (ex: `Senado Federal`) |
| `sigla` | VARCHAR | 0% | Ex: `CD`, `SF` |
| `ug_siafi` | VARCHAR | nullable | Aplica-se quando o próprio órgão tem UG direta (ex: Senado = `020001`) |
| `gestao` | VARCHAR | nullable | Aplica-se apenas junto com `ug_siafi` preenchido |

**Registros iniciais conhecidos (v1):**

| id_orgao | poder | instituicao | sigla | ug_siafi | gestao |
|---|---|---|---|---|---|
| 1 | Legislativo | Câmara dos Deputados | CD | — | — |
| 2 | Legislativo | Senado Federal | SF | 020001 | 00001 |
| 3 | Executivo | Poder Executivo | EX | — | — |

> O `Poder Executivo` (EX) é um órgão **genérico por construção** (ADR-025):
> a fonte CGU do cartão CPGF não expõe órgão no grão de transação — cada
> transação é resolvida para `EX` por JOIN em `dim_orgao.sigla` (ADR-022.1,
> sem literal de id). UG/Gestão da Câmara ainda não identificados (pendência
> aberta, não bloqueia Sprint 1 — grão de `dim_orgao` não depende disso).

### 2.2 dim_unidade_gestora (ADR-010/ADR-025 — ATIVA desde o `fact_cartao_cpgf`)

| Campo | Tipo | Nulos | Descrição |
|---|---|---|---|
| `id_unidade_gestora` | BIGINT | 0% | PK surrogate |
| `codigo` | VARCHAR | 0% | Código da UG na fonte de origem |
| `gestao` | VARCHAR | nullable | **Aplica-se apenas quando `fonte_origem = 'SIAFI'`** — não preencher para outras fontes |
| `nome` | VARCHAR | 0% | Ex: `CAMPUS DUQUE DE CAXIAS` |
| `id_orgao` | BIGINT (FK) | 0% | Referencia `dim_orgao` (v1: sempre EX, via JOIN) |
| `fonte_origem` | VARCHAR | 0% | `SIAFI` \| `CGU` \| `Tesouro Nacional` \| outro |

**Chave natural:** (`fonte_origem`, `codigo`) — nunca `codigo` isolado.

> Na v1 esta dimensão era schema-only (ADR-010, item 6). Com o
> `fact_cartao_cpgf` (ADR-012/025) ela passa a ser **materializada a partir do
> próprio grão de `silver_cartao`** (CGU): as UGs observadas nas transações são
> o conteúdo da dimensão, permitindo `fact_cartao_cpgf.id_unidade_gestora`
> NOT NULL (contrato gold.py). Para despesa parlamentar,
> `fact_despesa.id_unidade_gestora` permanece `NULL` — a Câmara/Senado não
> expõem UG no grão de despesa.

### 2.3 dim_fornecedor (schema revisado — ADR-011)

| Campo | Tipo | Nulos | Descrição |
|---|---|---|---|
| `id_fornecedor` | BIGINT | 0% | PK surrogate |
| `cnpj_cpf_valor` | VARCHAR | nullable | CNPJ em claro (14 dígitos) OU hash HMAC-SHA256 do CPF (11 dígitos) OU `NULL` se origem vazia |
| `tipo_documento` | VARCHAR | nullable | `CNPJ` \| `CPF` \| `INVALIDO` \| `NULL` (espelha `cnpj_cpf_valor`) |
| `nome_fornecedor` | VARCHAR | variável por fonte | Ver §3 para nulos por origem |
| `id_municipio` | BIGINT (FK) | **100% nulo na v1** | Referencia `dim_municipio`. Não populado — nenhuma fonte fornece endereço do fornecedor |

> **Regra de qualidade (ADR-011):** `tipo_documento = 'INVALIDO'`
> sinaliza comprimento ≠ 11 e ≠ 14 após sanitização — não descartado,
> registrado no Data Quality Report (Sprint 3). Substitui a antiga
> chave natural `cnpj_cpf_hash` (nome descontinuado — sugeria hash
> universal, o que não é mais verdade após ADR-011).

> **Nota (Revisão Sprint 1) — `id_municipio`:** campo nullable, **não
> populado na v1**. Nenhuma das três fontes (Câmara, Senado, CGU)
> fornece endereço/município do fornecedor diretamente. Enriquecimento
> via CNAE/Receita Federal está fora do escopo do MVP
> (`PROJECT_CONTEXT.md §1.5`). O campo existe desde já apenas para
> evitar migração de schema quando esse enriquecimento for
> implementado — mesmo padrão de "schema estável, dado ausente" já
> aplicado a `id_unidade_gestora` (ADR-010).

### 2.4 fact_despesa (FKs institucionais — ADR-010)

| Campo | Tipo | Nulos | Descrição |
|---|---|---|---|
| `id_orgao` | BIGINT (FK) | **0% — NOT NULL** | Sempre resolvido, inclusive Câmara/Senado |
| `id_unidade_gestora` | BIGINT (FK) | **100% na v1** | `NULL` até `dim_unidade_gestora` ser ativada (ver §2.2) |

*(demais campos de `fact_despesa` — `valor_liquido`, `valor_glosa`, FKs de `dim_parlamentar`/`dim_fornecedor`/`dim_data` — inalterados em relação a PROJECT_CONTEXT.md §7)*

### 2.5 fact_cartao_cpgf (ADR-012/ADR-025 — Onda 3 do Gold)

| Campo | Tipo | Nulos | Descrição |
|---|---|---|---|
| `id_transacao` | BIGINT | 0% | PK surrogate determinístico. Chave de referência externa/entre execuções: `id` nativo da CGU |
| `id_orgao` | BIGINT (FK) | **0% — NOT NULL** | `dim_orgao` — v1: sempre `Poder Executivo` (sigla `EX`, ADR-025), via JOIN por sigla (ADR-022.1) |
| `id_unidade_gestora` | BIGINT (FK) | **0% — NOT NULL** | `dim_unidade_gestora` (CGU) — a fonte entrega a UG nativamente no grão |
| `id_fornecedor` | BIGINT (FK) | **nullable** | `dim_fornecedor` — só preenchido quando o CNPJ/CPF do estabelecimento resolve na dimensão (ADR-011) |
| `data_sk` | BIGINT (FK) | 0% | `dim_data` — YYYYMMDD de `data_transacao` |
| `portador_nome` / `portador_ cpf_ mascarado` | VARCHAR | 0% | Próprio da CGU (CPF já mascarado pela fonte) |
| `valor_transacao` | DECIMAL | 0% | Valor da transação |

*> Grão: **uma transação** CPGF (`silver_cartao`). Não referencia `dim_parlamentar` — o portador pertence estruturalmente ao Executivo; correlação futura com parlamentar exige bridge dedicada (ADR-012.3). Transações cujas FKs de órgão/UG/data não resolvem vão a `fact_cartao_cpgf_quarantine` (ADR-018/022) — motivos `orgao_nao_resolvido`, `unidade_gestora_nao_resolvida`, `data_nao_resolvida`.*

### 2.6 fact_cartao_cpgf_quarantine (ADR-018/022)

> Complemento do fato: transações **não promovidas**, com `motivo_quarentena`
> explícito (`orgao_nao_resolvido` \| `unidade_gestora_nao_resolvida` \|
> `data_nao_resolvida`). Nenhuma transação é descartada em silêncio;
> reconstruível pela chave natural `id` (CGU). `id_fornecedor` NULL **não**
> gera quarentena — o contrato é nullable (ADR-012) e o lag observado pelos
> testes `fk_orphan_pct`/`relationships` (ADR-022.3a).

### 2.7 supplier_concentration (ADR-021 — agregado analítico puro)

| Campo | Tipo | Nulos | Descrição |
|---|---|---|---|
| `ano` | INT | 0% | Ano fiscal (de `dim_data.ano`) |
| `id_parlamentar` | BIGINT (FK) | 0% | `dim_parlamentar` — chave natural do parlamentar |
| `num_fornecedores` | BIGINT | 0% | nº de fornecedores distintos do parlamentar no ano |
| `total_valor` | DECIMAL | 0% | `SUM(valor_liquido)` do parlamentar no ano |
| `hhi` | DOUBLE | 0% | Índice HHI: `SUM(participacao^2)`, `participacao` = total do fornecedor / total do parlamentar no ano — ∈ (0, 1] |

> Grão: **um parlamentar por ano**. Fonte `fact_despesa` (agregado puro, sem ML — ADR-021); única tabela com a métrica `hhi` isolada para `supplier_concentration_score` (§9).

### 2.8 supplier_growth (ADR-021 — agregado analítico puro)

| Campo | Tipo | Nulos | Descrição |
|---|---|---|---|
| `ano` | INT | 0% | Ano fiscal (de `dim_data.ano`) |
| `id_fornecedor` | BIGINT (FK) | 0% | `dim_fornecedor` — id do fornecedor |
| `valor_recebido` | DECIMAL | 0% | `SUM(valor_liquido)` do fornecedor no ano |
| `valor_ano_anterior` | DECIMAL | **nulo no 1º período** | receita do fornecedor no ano anterior (YoY) |
| `variacao_pct` | DOUBLE | **nulo no 1º período** | `(valor_recebido - valor_ano_anterior) / valor_ano_anterior` |

> Grão: ``(ano, id_fornecedor)``. Fonte `fact_despesa` (agregado puro, sem ML — ADR-021).

---

## 3. Schemas das Fontes (Sprint 0B — Exploração Empírica)

### 3.1 Câmara dos Deputados (API REST)

**Endpoint:** `GET /deputados/{id}/despesas`
**Formato:** JSON
**Total na amostra:** 2.307 despesas (50 deputados, 2024)

| Campo | Tipo | Nulos | Notas |
|---|---|---|---|
| `ano` | int | 0% | |
| `mes` | int | 0% | |
| `cnpjCpfFornecedor` | string | 3.55%¹ | CNPJ (94.9%) ou CPF (5.1%); sem formatação |
| `codDocumento` | **VARCHAR** | 0% | Formato GUID em passagens aéreas (ex: `a1b2c3d4-...`) — nunca tratar como numérico, até quando o valor observado é numumerico |
| `codLote` | int | 0% | |
| `codTipoDocumento` | int | 0% | **Sempre 0** — campo obsoleto |
| `dataDocumento` | string | 0% | Formato ISO: `2024-07-03T00:00:00` |
| `nomeFornecedor` | string | 0% | |
| `numDocumento` | string | 0% | |
| `numRessarcimento` | string | **99.8%** | Campo morto — não utilizável |
| `parcela` | int | 0% | |
| `tipoDespesa` | string | 0% | Descrição textual (ex: "MANUTENÇÃO DE ESCRITÓRIO...") |
| `tipoDocumento` | string | 0% | "Nota Fiscal", "Recibo", etc. |
| `urlDocumento` | string | 2.6%² | Link para PDF do documento fiscal |
| `valorDocumento` | float | 0% | |
| `valorGlosa` | float | 0% | |
| `valorLiquido` | float | 0% | |

¹ Na amostra de 50 deputados (2024): 3.55% vazio. Em exploração anterior com ~45.794 registros (ano completo), atingiu 13-14%. A diferença é efeito de tamanho de amostra — o percentual real deve ser verificado após ingestão completa.

² Mesma ressalva: 2.6% nesta amostra vs. 4.2% na amostra inicial de 500 registros.
> **Nota de tipagem (Sprint 1):** `codDocumento` foi inicialmente
> presumido como inteiro em exploração informal. Validação em
> registros de passagem aérea confirmou formato GUID
> (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`). Campo deve ser tipado
> como `VARCHAR` em todas as camadas — tratamento como numérico
> causaria truncamento silencioso de zeros à esquerda e falha de
> parsing em registros GUID.

> **Nota de parsing (Sprint 1):** `dataDocumento` chega como string
> ISO 8601 (`2024-07-03T00:00:00`). Requer parsing explícito para
> `DATE`/`TIMESTAMP` na camada Silver — nunca comparar ou ordenar
> como string. Mesmo padrão de tratamento definido para `DATA`
> (Senado, DD/MM/AAAA) e datas da CGU (DD/MM/AAAA) em §3.2/§3.3,
> todas convergindo para `DATE` nativo na Silver.

### 3.2 Senado Federal (CSV CEAPS)

**Fonte:** `https://www.senado.leg.br/transparencia/LAI/verba/despesa_ceaps_{ano}.csv`
**Formato:** CSV (ISO-8859-1, separador `;`, quote `"`)
**Total:** ~21.433 linhas (2024), ~18.826 (2023)

| Campo | Tipo | Nulos | Notas |
|---|---|---|---|
| `ANO` | int | 0% | |
| `MES` | int | 0% | |
| `SENADOR` | string | 0% | Nome completo em maiúsculas |
| `TIPO_DESPESA` | string | 0% | Descrição textual |
| `CNPJ_CPF` | string | 0% | **Formatado** com pontuação (ex: `66.970.229/0132-26`, `004.948.028-63`) — requer sanitização |
| `FORNECEDOR` | string | 0% | Nome do fornecedor |
| `DOCUMENTO` | string | 0% | Número do documento fiscal |
| `DATA` | string | 0% | Formato DD/MM/AAAA |
| `DETALHAMENTO` | string | ~1% | Descrição adicional da despesa |
| `VALOR_REEMBOLSADO` | string | 0% | **Texto com vírgula decimal** (ex: `583,58`) — requer parse numérico |
| `COD_DOCUMENTO` | int | 0% | Chave primária natural para deduplicação |

**Observações importantes:**
- Schema completamente diferente da Câmara — justifica extractors/transformers separados (`pipeline/camara/` vs `pipeline/senado/`)
- Codificação ISO-8859-1 requer `encoding="ISO-8859-1"` no reader
- `VALOR_REEMBOLSADO` usa vírgula como separador decimal (padrão pt-BR)
- `DATA` no formato brasileiro DD/MM/AAAA
- `CNPJ_CPF` com pontuação — requer `utils.RemoveCaracteresNaoNumericos()`

### 3.3 Portal da Transparência (CGU)

**Base URL:** `https://api.portaldatransparencia.gov.br/api-de-dados`
**Autenticação:** Header `chave-api-dados` (obter via gov.br)
**Rate limit:** 400 req/min (700 entre 00:00-06:00)

Endpoints relevantes identificados no OpenAPI spec:

| Endpoint | Descrição |
|---|---|
| `GET /despesas/documentos` | Documentos de despesa (empenho/liquidação/pagamento) por órgão |
| `GET /despesas/por-orgao` | Despesas anuais agregadas por órgão |
| `GET /despesas/documentos-por-favorecido` | Despesas por CPF/CNPJ do beneficiário |
| `GET /emendas` | Emendas parlamentares com valores |
| `GET /contratos` | Contratos do Executivo Federal |
| `GET /cartoes` | Gastos com cartão de pagamento (CPGF) |
| `GET /viagens` | Viagens a serviço com valores |

**Chave de API obtida e funcional** (Sprint 0B). Schema dos endpoints mais relevantes:

**Emendas Parlamentares** (`GET /emendas?ano=2024&pagina=1`) — 15 campos, 0% nulos:

| Campo | Tipo | Exemplo |
|---|---|---|
| `ano` | int | `2024` |
| `codigoEmenda` | string | `202440340007` |
| `tipoEmenda` | string | `Emenda Individual - Transferências com Finalidade Definida` |
| `autor` / `nomeAutor` | string | `LUISA CANZIANI` |
| `numeroEmenda` | string | `0007` |
| `funcao` | string | `Saúde` |
| `subfuncao` | string | `Assistência hospitalar e ambulatorial` |
| `localidadeDoGasto` | string | `LONDRINA - PR` |
| `valorEmpenhado` | string¹ | `10.000,00` |
| `valorLiquidado` | string¹ | `10.000,00` |
| `valorPago` | string¹ | `10.000,00` |
| `valorRestoInscrito` | string¹ | `0,00` |
| `valorRestoCancelado` | string¹ | `0,00` |
| `valorRestoPago` | string¹ | `0,00` |

¹ String pt-BR com ponto de milhar e vírgula decimal.

**Cartões CPGF** (`GET /cartoes?tipoCartao=1&mesExtratoInicio=01/2024&pagina=1`) — 23 campos:

| Campo | Tipo | Nulos | Exemplo |
|---|---|---|---|
| `id` | int | 0% | `474873149` |
| `mesExtrato` | string | 0% | `01/2024` |
| `dataTransacao` | string | 0% | `28/11/2023` |
| `valorTransacao` | string¹ | 0% | `97,89` / `1.173,05` |
| `tipoCartao.codigo` | string | 0% | `1` (CPGF) |
| `estabelecimento.id` | int | 0% | `5818721` |
| `estabelecimento.cnpjFormatado` | string | 20% | `42.270.058/0001-03` |
| `estabelecimento.cpfFormatado` | string | **100%** | sempre vazio |
| `estabelecimento.nome` | string | 0% | `G M R EQUIPAMENTOS ELETRICOS LTDA` |
| `estabelecimento.razaoSocialReceita` | string | 0% | `G M R EQUIPAMENTOS ELETRICOS LTDA` |
| `estabelecimento.tipo` | string | 0% | `Entidades Empresariais Privadas` |
| `estabelecimento.numeroInscricaoSocial` | string | **100%** | sempre vazio |
| `portador.nome` | string | 0% | `DANIEL DIAS LEONARDO MARTINS` |
| `portador.cpfFormatado` | string | 0% | `***.122.497-**` (mascarado) |
| `portador.nis` | string | **100%** | sempre vazio |
| `unidadeGestora.codigo` | string | 0% | `158482` |
| `unidadeGestora.nome` | string | 0% | `CAMPUS DUQUE DE CAXIAS` |

**Órgãos SIAFI** (`GET /orgaos-siafi?pagina=1`) — 2 campos, tabela de referência:

| Campo | Tipo | Exemplo |
|---|---|---|
| `codigo` | string | `01000` (Câmara), `01901` (Fundo Rotativo Câmara) |
| `descricao` | string | `Câmara dos Deputados - Unidades com vínculo direto` |

**Campos mortos identificados na CGU:** `estabelecimento.cpfFormatado` (100% vazio), `estabelecimento.numeroInscricaoSocial` (100% vazio), `portador.nis` (100% vazio).

> **Padrão transversal entre as 3 fontes:**
> - Valores monetários: Câmara=float nativo, Senado=string pt-BR, CGU=string pt-BR com milhar
> - CNPJ/CPF: Câmara=sem formatação, Senado=formatado, CGU=formatado — HMAC deve operar sobre dígitos limpos (ADR-004)
> - Datas: Câmara=ISO 8601, Senado=DD/MM/AAAA, CGU=DD/MM/AAAA — Silver normaliza para DATE
 
---
 
## 4. Distinção Formal: `contamination` vs. Threshold de Score (ADR-002)
 
Esta seção existe porque ADR-002 exige que esta distinção seja
documentada aqui, para evitar que futuras alterações no Isolation
Forest ajustem os dois parâmetros como se fossem redundantes.
 
| Parâmetro | Momento do ciclo de vida | Papel |
|---|---|---|
| `contamination = 0.05` | **Treino** do modelo | Calibra a proporção esperada de outliers no dataset de treino. Define como o modelo aprende a fronteira de decisão. |
| `score < -0.1` | **Inferência** sobre novas despesas | Regra de decisão aplicada a cada despesa nova, sem necessidade de retreinar o modelo. |
 
**Por que não são redundantes:** alterar `contamination` muda o
modelo treinado (a fronteira de decisão inteira); alterar o
threshold de score muda apenas a sensibilidade da regra aplicada a
um modelo já treinado. Um ajuste em um dos dois parâmetros sem
revisar o outro pode descalibrar silenciosamente a taxa de
anomalias detectadas — por isso ambos exigem novo ADR para serem
alterados (ver PROJECT_CONTEXT.md §10).
 
---
 
## 5. Pendências desta versão (atualizado — Sprint 1)

- ~~Código SIAFI do Senado~~ — **Resolvido.** UG 020001, Gestão 00001.
- Código SIAFI da Câmara — ainda não identificado. Não bloqueia
  fechamento da Sprint 1 (grão de `dim_orgao` não depende disso).
- Preencher `dim_unidade_gestora` — bloqueado até RF futuro (ADR-010).
- Contratos de interface Pydantic por camada — pendente (próximo
  artefato da Sprint 1).
- Estratégia formal de watermark/versionamento consolidada —
  pendente (próximo artefato da Sprint 1).
 
 
---
> **Nota (Revisão Sprint 1):** `id_municipio` é campo nullable,
> **não populado na v1**. Nenhuma das três fontes (Câmara, Senado,
> CGU) fornece endereço/município do fornecedor diretamente.
> Enriquecimento via CNAE/Receita Federal está fora do escopo do
> MVP (`PROJECT_CONTEXT.md §1.5`). O campo existe desde já apenas
> para evitar migração de schema quando esse enriquecimento for
> implementado — mesmo padrão de "schema estável, dado ausente" já
> aplicado a `id_unidade_gestora` (ADR-010).

*Documento inicial criado na Sprint 0A, em resposta a lacuna
identificada entre ADR-002 e os artefatos existentes do projeto.*
