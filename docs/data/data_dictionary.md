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
 
## 3. Distinção Formal: `contamination` vs. Threshold de Score (ADR-002)
 
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
 
## 4. Pendências desta versão
 
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
