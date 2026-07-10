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
