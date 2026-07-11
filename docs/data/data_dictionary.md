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
 
## 2. Catálogo de Tabelas (a ser expandido na Sprint 1)
 
| Tabela | Camada | Origem | Frequência | Chave Primária | Owner |
|---|---|---|---|---|---|
| `bronze_camara_despesas` | Bronze | API Câmara dos Deputados | Diária | — (raw) | Engenheiro de Dados |
| `bronze_senado_despesas` | Bronze | API Senado Federal | Diária | — (raw) | Engenheiro de Dados |
| `dim_parlamentar` | Gold | Silver consolidado | Diária | `id_parlamentar` + `surrogate_key` | Engenheiro de Dados |
| `dim_fornecedor` | Gold | Receita Federal (CNPJ) + Silver | Mensal | `cnpj_cpf_hash` | Engenheiro de Dados |
| `fact_despesa` | Gold | Silver consolidado | Diária | `id_despesa` | Engenheiro de Dados |
| `risk_scores` | Gold | Analytics (Sprint 5) | Diária (pós-batch) | `id_parlamentar` + `data_sk` | Cientista de Dados |
 
> Tabela incompleta por design — será populada integralmente durante
> a Sprint 1, quando o modelo dimensional completo (PROJECT_CONTEXT.md
> §7) for implementado. Esta versão cobre apenas as entidades já
> nomeadas nas decisões arquiteturais existentes.

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
| `codDocumento` | string | 0% | |
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
 
## 5. Pendências desta versão
 
- Preencher colunas completas (tipo de dado, nullability, exemplo de
  valor) para cada tabela na Sprint 1.
- Adicionar seção de linhagem (Bronze → Silver → Gold) por tabela,
  quando os pipelines de transformação existirem (Sprints 2–4).
- Adicionar regras de qualidade Pandera por tabela, assim que
  `pipeline/quality.py` for implementado (Sprint 3).
- Vincular cada tabela às features da Feature Store (`ml_feature`)
  que dela derivam, quando aplicável (ver `docs/data/ml_feature.md`).
 
---
 
*Documento inicial criado na Sprint 0A, em resposta a lacuna
identificada entre ADR-002 e os artefatos existentes do projeto.*
