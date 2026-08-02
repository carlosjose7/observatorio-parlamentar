# versionamento.md
# Estratégia de Watermark e Versionamento — Observatório Parlamentar

> Formaliza RF-01 (ingestão incremental via watermark) e RF-12
> (reprodutibilidade via run_id/pipeline_version/execution_timestamp/
> source_version). Consolida o que ADR-009 já definia por fonte,
> estendendo para os três domínios de fato criados em ADR-012.

---

## 1. Metadados obrigatórios por carga (RF-12)

Todo registro persistido em qualquer camada (Bronze, Silver, Gold)
carrega os quatro campos definidos em `pipeline/schemas/common.py::LoadMetadata`:

| Campo | Tipo | Gerado por | Descrição |
|---|---|---|---|
| `run_id` | UUID | Airflow, no início do DAG run | Identifica unicamente uma execução completa do pipeline |
| `pipeline_version` | string (semver) | `pyproject.toml` no momento do build da imagem Docker | Versão do código que produziu a carga — não da configuração |
| `execution_timestamp` | timestamp UTC | Airflow, `execution_date`/`data_interval_end` | Momento lógico da execução (não o momento real de wall-clock, para permitir backfill determinístico) |
| `source_version` | string | Definido por fonte — ver §3 | Snapshot/versão do dado de origem no momento da extração |

**Regra de propagação:** `run_id`, `pipeline_version` e
`execution_timestamp` são **idênticos** para todos os registros de
todas as fatos gerados no mesmo DAG run. `source_version` varia por
fonte, pois cada fonte (Câmara, Senado, CGU) é extraída por uma task
independente no DAG, com seu próprio ciclo de watermark.

---

## 2. Watermark — estratégia por fonte

> Watermark controla **o que extrair** (incremental). É distinto de
> `source_version`, que documenta **o que foi de fato extraído**
> (auditoria). Um DAG run pode ter watermark avançado sem que
> `source_version` mude, se a fonte não publicou nada novo.

### 2.1 Câmara dos Deputados → `fact_despesa`

- **Campo de watermark:** `dataDocumento`
- **Mecânica:** extração incremental página a página, filtrando
  `dataDocumento >= last_watermark`. Watermark avança para o maior
  `dataDocumento` observado na página mais recente ao final da
  extração bem-sucedida.
- **Armazenamento do estado:** Airflow Variable
  `watermark_camara_despesas` (JSON: `{"last_watermark": "2026-07-01", "run_id": "..."}`),
  atualizada apenas após confirmação de escrita bem-sucedida em
  Bronze — nunca antes, para evitar perda de dado em caso de falha
  parcial.
- **Retry:** `tenacity` com `wait_exponential`, per ADR-009.

### 2.2 Senado Federal → `fact_despesa`

- **Sem watermark incremental** — a fonte publica CSV anual
  completo (`despesa_ceaps_{ano}.csv`), não paginado nem filtrável
  por data na origem (ADR-009).
- **Mecânica:** download do CSV do ano corrente a cada execução
  sazonal (mensal, após publicação). Deduplicação por
  `COD_DOCUMENTO` (chave primária natural) na carga em Bronze —
  registros já existentes com o mesmo `COD_DOCUMENTO` são
  descartados, não sobrescritos.
- **"Watermark" neste caso é o próprio ano do CSV** — controla
  *qual arquivo* baixar, não uma posição incremental dentro dele.

### 2.3 CGU — Emendas Parlamentares → `fact_emenda`

- **Campo de watermark:** `ano` (parâmetro de query `?ano=2026`,
  paginado).
- **Mecânica:** varredura completa das páginas do ano corrente a
  cada execução — a fonte não expõe um campo de data de
  atualização por emenda individual, apenas o ano do exercício.
  Deduplicação por `codigoEmenda` na carga em Bronze.
- **Rate limiting:** respeita 400 req/min (diurno) / 700 req/min
  (noturno), conforme ADR-009 — `tenacity` com throttling explícito.

### 2.4 CGU — Cartões CPGF → `fact_cartao_cpgf`

- **Campo de watermark:** `mesExtrato` (parâmetro
  `mesExtratoInicio=MM/AAAA`, paginado).
- **Mecânica:** extração incremental por mês de extrato — watermark
  avança para o `mesExtrato` mais recente processado com sucesso.
  Deduplicação por `id` (chave primária nativa da CGU) na carga em
  Bronze.
- **Rate limiting:** mesmo padrão de §2.3.

---

## 3. `source_version` — definição por fonte

| Fonte | Definição de `source_version` |
|---|---|
| Câmara | Data de execução da extração (`execution_timestamp` truncado para data) — a API não expõe versão/ETag de resposta |
| Senado | Nome do arquivo CSV baixado, incluindo ano (ex: `despesa_ceaps_2026.csv`) — versão é o próprio arquivo, imutável por natureza de publicação anual |
| CGU (emendas) | `{ano}` do parâmetro de query + data de execução (ex: `2026-execution-2026-07-12`) — a fonte não versiona respostas |
| CGU (cartões) | `{mesExtrato}` do parâmetro de query + data de execução |

> Nenhuma das três fontes expõe versionamento nativo (ETag,
> `Last-Modified` confiável, hash de conteúdo) — `source_version` é
> portanto uma convenção do projeto, não um dado fornecido pela
> fonte. Isso está documentado aqui para que ninguém assuma
> futuramente que `source_version` permite detectar mudança de
> conteúdo sem reprocessar.

---

## 4. Reprodutibilidade (RF-12)

Dado um `run_id` de uma execução anterior, a reprodução exige:

1. **Consultar `run_id` na tabela de controle** (`pipeline_runs`,
   Gold — schema abaixo) para obter `pipeline_version` e o watermark
   de cada fonte **no momento daquela execução** (não o watermark
   atual).
2. **Fazer checkout do código na tag/commit correspondente a
   `pipeline_version`** (versionado via Git tags, alinhado a
   `pyproject.toml`).
3. **Re-executar a extração com o watermark congelado daquele run**
   — não o watermark corrente da Variable do Airflow, que já avançou.

pipeline_runs (Gold — tabela de controle, não é fato de negócio)
run_id              UUID PK
pipeline_version    VARCHAR
execution_timestamp TIMESTAMP
status               VARCHAR  -- success | failed | partial
watermark_camara     VARCHAR  -- dataDocumento no momento do run
watermark_senado      VARCHAR  -- ano do CSV processado
watermark_cgu_emenda   VARCHAR  -- ano processado
watermark_cgu_cartao   VARCHAR  -- mesExtrato processado

Essa tabela é o artefato que efetivamente torna RF-12 verificável —
sem ela, `run_id` embutido em cada fato não seria suficiente para
reconstruir o *estado do watermark* daquele momento, apenas para
identificar quais registros pertencem a qual execução.

---

## 5. Consequências

- Toda task de extração no Airflow DAG (`pipeline/dags/pipeline_dag.py`)
  deve gravar em `pipeline_runs` ao final da execução, sucesso ou
  falha — falhas parciais registram `status = 'partial'` com o
  watermark do que foi de fato consolidado em Bronze.
- Watermark é **sempre lido do Airflow Variable / `pipeline_runs`**,
  nunca inferido do estado atual da tabela Gold — evita
  dessincronia se um backfill manual for feito diretamente no banco.
- `source_version` não substitui `run_id` como identificador de
  execução — é metadado de auditoria complementar, não chave.
- As quatro fontes de watermark (§2.1–2.4) evoluem
  independentemente — uma falha na extração da CGU não impede o
  avanço do watermark da Câmara no mesmo DAG run, já que são tasks
  distintas.
- `dim_data.data_sk` não deve ser confundido com watermark — é
  dimensão de calendário, não controle de ingestão.

---

*Documento consolidado na Sprint 1, cobrindo `fact_despesa`,
`fact_emenda` e `fact_cartao_cpgf` (ADR-012). Implementação real do
Airflow Variable e da tabela `pipeline_runs` ocorre na Sprint 2
(Pipeline Bronze).*