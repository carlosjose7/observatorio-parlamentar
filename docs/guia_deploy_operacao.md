# Guia de Deploy e Operação
# Observatório Parlamentar — Docker Compose, execução diária e operação

> **Status:** Sprint 9 (em validação)
> **Objetivo:** documentar o deploy do Observatório Parlamentar — local e na
> VPS Oracle —, a execução diária do pipeline (ADR-034) e a operação
> rotineira do ambiente.
> **Complementar:** `docs/guia_provisionamento_oci.md` cobre o provisionamento
> da infraestrutura OCI (instância, Docker, firewall); este guia cobre o
> código e a operação.

---

## 1. Visão geral dos serviços

O `docker-compose.yml` organiza a stack em dois grupos:

| Perfil | Serviços | Quando roda |
|---|---|---|
| `default` | nginx, api, dashboard, minio | Sempre ativos (produção/desenvolvimento) |
| `pipeline` | postgres, airflow-webserver, airflow-scheduler | Apenas durante a execução do pipeline (ADR-007) |

O reverse proxy nginx roteia:
- `/api/*` e `/docs` → FastAPI (porta 8000)
- `/` → Streamlit (porta 8501)
- `/minio/` → MinIO Console (porta 9001)

---

## 2. Deploy local (desenvolvimento)

**Pré-requisitos:** Docker + Docker Compose v2, Python 3.11+.

1. **Preparar o `.env`:**
   ```bash
   cp .env.example .env
   ```
   Preencha as credenciais reais: `CPF_HMAC_SECRET_KEY`, `CGU_API_KEY`,
   `MINIO_ROOT_PASSWORD`, `POSTGRES_PASSWORD`, `AIRFLOW_FERNET_KEY`,
   `AIRFLOW_ADMIN_PASSWORD`. O `.env` nunca é versionado.

2. **Subir a stack:**
   ```bash
   docker compose up -d          # nginx, api, dashboard, minio
   docker compose build --parallel
   ```
   Dashboard: http://localhost · API Docs: http://localhost/docs ·
   MinIO Console: http://localhost/minio

3. **Rodar o pipeline (perfil `pipeline`):**
   ```bash
   docker compose --profile pipeline up -d postgres airflow-webserver airflow-scheduler
   ```
   Airflow: http://localhost:8080 (credenciais `AIRFLOW_ADMIN_USER/_PASSWORD`).

4. **Testes e lint:**
   ```bash
   pip install -e ".[dev,api,pipeline,dashboard,analytics]"
   python -m ruff check .
   python -m pytest --cov
   ```

---

## 3. Deploy na VPS Oracle (produção)

**Pré-requisitos:** instância provisionada (ver `docs/guia_provisionamento_oci.md`),
Docker instalado, `ubuntu` no grupo `docker`, chave SSH e `.env` na VPS.

1. **Validar acesso e sudo sem senha** (uma vez):
   ```bash
   ssh -i ~/.ssh/observatorio_parlamentar_oci ubuntu@<IP> "sudo -n true && echo OK"
   ```
   Se falhar, configure o sudo passwordless antes de prosseguir.

2. **Provisionar o grupo docker** (uma vez, se a VPS foi criada antes do
   ajuste no `cloud-config.yaml`):
   ```bash
   ssh -i ~/.ssh/observatorio_parlamentar_oci ubuntu@<IP> "sudo usermod -aG docker ubuntu"
   # reconecte a sessão SSH para o grupo surtir efeito
   ```

3. **Executar o deploy** (sincroniza arquivos via rsync, instala as units
   systemd do pipeline e sobe os containers):
   ```bash
   bash scripts/deploy.sh <IP_DA_VPS> [caminho_da_chave_ssh]
   ```
   O script:
   - `[1/6]` verifica a conexão SSH
   - `[2/6]` cria `~/observatorio-parlamentar` na VPS
   - `[3/6]` sincroniza o projeto (rsync, excluindo `.env`, `data/`, `.git/`)
   - `[4/6]` instala/atualiza `observatorio-pipeline.service` e `.timer`
   - `[5/6]` constrói imagens e sobe o perfil `default`
   - `[6/6]` verifica o status dos containers

---

## 4. Execução diária do pipeline (ADR-034)

**Decisão (ADR-034):** a execução diária roda na VPS via `systemd timer`,
não no GitHub Actions (que fica restrito a CI). Dados persistidos
(`./data/`, `minio_data`, `postgres_data`) sobrevivem ao ciclo up/down.

- **Timer:** `observatorio-pipeline.timer` dispara
  `observatorio-pipeline.service` às **03:00 America/Sao_Paulo**,
  com `Persistent=true` (recupera execução perdida) e
  `RandomizedDelaySec=120`.
- **Service (oneshot):** roda `scripts/run_pipeline_daily.sh` como usuário
  `ubuntu`, sem retry automático. O script:
  1. Sobe `postgres` + `airflow-scheduler` (sem webserver — execução batch);
  2. Aguarda o Airflow ficar pronto (`airflow dags list-import-errors`);
  3. Despausa o DAG `observatorio_pipeline`
     (`DAGS_ARE_PAUSED_AT_CREATION=True` — unpause explícito é obrigatório);
  4. Dispara com `run_id` determinístico e acompanha o estado via
     `airflow dags list-runs --output json` até `success`;
  5. Garante `docker compose --profile pipeline down` ao final (trap EXIT).

**Comandos de operação do timer:**
```bash
systemctl list-timers observatorio-pipeline.timer   # próxima execução
systemctl status observatorio-pipeline.service      # resultado da última
journalctl -u observatorio-pipeline.service -n 100  # logs da execução
sudo systemctl start observatorio-pipeline.service  # disparo manual
```

**Timeouts configuráveis (env vars, ADR-008):**
`AIRFLOW_READY_TIMEOUT_SEC` (180s), `POLL_INTERVAL_SEC` (30s),
`DAG_TIMEOUT_SEC` (5400s — deve ser menor que `TimeoutStartSec=6000` do
service).

---

## 5. Operação rotineira

### 5.1 Atualizar o deploy
Reexecute `bash scripts/deploy.sh <IP> [chave]` — o rsync sincroniza o
código, o passo `[4/6]` atualiza as units systemd e o `[5/6]` reconstrói
imagens quando o `Dockerfile`/dependências mudam.

### 5.2 Verificar saúde dos serviços
```bash
docker compose ps
docker compose ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'
```

### 5.3 Verificar a última execução do pipeline
```bash
journalctl -u observatorio-pipeline.service -n 50
docker compose exec airflow-scheduler airflow dags list-runs --dag-id observatorio_pipeline --output json
```

### 5.4 Inspecionar o Gold (DuckDB)
```bash
docker compose exec api python -c "
import duckdb
con = duckdb.connect('data/gold/observatorio.duckdb', read_only=True)
print(con.execute('select run_id, status from pipeline_runs order by execution_timestamp desc limit 5').fetchall())
"
```

---

## 6. Segurança

- **Segredos:** apenas via `.env` na VPS (nunca versionado); o CI usa
  GitHub Secrets para Gitleaks.
- **Pseudonimização:** CPF é hasheado na Silver (ADR-033); a API só expõe
  o hash. MinIO exposto apenas em `127.0.0.1` na máquina host.
- **Firewall:** Security List OCI + UFW local permitem apenas 22/80/443
  (ver guia de provisionamento). TLS (Let's Encrypt) é o Gate 5 da
  Sprint 9 — até lá, o tráfego em `:80` é sem criptografia.

---

## 7. Testes em HML (homologação)

### 7.1 Visão geral do fluxo

O ciclo de validação de uma feature segue:

```
develop → deploy HML → validação → PR para main
```

- **HML** roda na mesma VPS, isolado do PRD (projeto Docker `-p hml`).
- **Ports:** API `:18000`, Airflow `:18080`, MinIO `:19000/:19001` (distintas do PRD).
- **Dados:** `./data.hml/` (DuckDB/Parquet independentes do PRD).
- **Credenciais:** `.env.hml` (nunca toca `.env` do PRD).

### 7.2 Pré-requisitos

- `.env.hml` configurado (copiar de `.env.hml.example` e preencher valores próprios).
- Docker + Docker Compose v2 instalados na VPS.
- Branch `develop` com as mudanças commitadas e push para `origin`.

### 7.3 Deploy da branch develop no HML

**Passo 1 — Sincronizar código:**
```bash
# Na VPS, na raiz do repo:
git pull origin develop
```

**Passo 2 — Subir containers HML:**
```bash
docker compose -f docker-compose.yml -f docker-compose.hml.yml \
  -p hml --env-file .env.hml --profile pipeline \
  up -d postgres airflow-scheduler minio api
```

**Passo 3 — Verificar status:**
```bash
docker compose -p hml ps
# Todos os serviços com status "Up"?
```

### 7.4 Rodar E2E do pipeline

```bash
bash scripts/run_hml_e2e.sh
```

O script executa:
1. 1ª execução: **backfill** (janela 2 meses, watermark vazio).
2. 2ª execução: **incremental** (mês seguinte ao watermark consolidado).
3. Valida `SUCCESS` em ambas as execuções.
4. Derruba containers ao final (`trap EXIT`).

**Timeout:** 1800s (30 min). Para acompanhar o progresso:
```bash
docker compose -p hml logs -f airflow-scheduler
```

### 7.5 Validar API e Dashboard

**API HML:** `http://127.0.0.1:18000/docs` (Swagger/ReDoc).

Endpoints-chave para validar após deploy de uma feature:
```bash
# Listagem de fornecedores
curl http://127.0.0.1:18000/fornecedores?limite=3

# Feature nova: despesas por fornecedor
curl http://127.0.0.1:18000/fornecedores/{cnpj}/gastos

# Regressão: despesas por parlamentar
curl http://127.0.0.1:18000/parlamentares/{id}/gastos

# Pipeline executou com sucesso?
curl http://127.0.0.1:18000/pipeline/status
```

### 7.6 Checklist antes do PR para main

- [ ] E2E HML: ambas execuções `SUCCESS` (backfill + incremental)
- [ ] API HML: endpoints retornam 200 com dados consistentes
- [ ] Testes unitários: `python -m pytest tests/` (todos verdes)
- [ ] Lint: `python -m ruff check .` (sem erros)
- [ ] `CHANGELOG.md` atualizado com a feature
- [ ] Nenhuma alteração em arquivos `.env` ou credenciais versionadas

### 7.7 Troubleshooting

| Problema | Solução |
|----------|---------|
| Airflow não fica pronto | `docker compose -p hml logs airflow-scheduler` — verificar erros de import |
| E2E falha no backfill | Conferir `.env.hml`: credenciais MinIO/Postgres batem com os containers |
| API retorna 404 em endpoint novo | Verificar se o endpoint existe em `api/routers/` e se o módulo está registrado no `api/main.py` |
| Containers não sobem | `docker compose -p hml down -v` e repetir §7.3 |

---

*Atualizado ao final da Sprint 10 (§7 — testes em HML).*
