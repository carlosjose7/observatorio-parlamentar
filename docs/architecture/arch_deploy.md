# Arquitetura de Deploy

```mermaid
flowchart TB
    subgraph GitHub["GitHub"]
        REPO[observatorio-parlamentar]
        ACTIONS[GitHub Actions<br/>CI/CD diário]
        SECRETS[GitHub Secrets<br/>.env]
    end

    subgraph Oracle["Oracle Cloud Always Free<br/>VM.Standard.A1.Flex<br/>2 OCPU · 12GB · sa-saopaulo-1"]
        DOCKER[Docker Compose]
        AIRFLOW[Airflow<br/>Orquestração]
        MINIO[MinIO<br/>Storage Bronze]
        DUCKDB[DuckDB<br/>Silver + Gold]
        API[FastAPI]
        NGINX[Nginx<br/>reverse proxy]
        DASH[Streamlit<br/>Dashboard em /app/]
        FW[firewalld<br/>Firewall]
    end

    REPO -->|git push| ACTIONS
    ACTIONS -->|CI: lint/testes/gitleaks| REPO
    TIMER[systemd timer<br/>execução diária] -->|dispara| AIRFLOW
    SECRETS -.->|env vars| ACTIONS
    AIRFLOW --> MINIO
    AIRFLOW --> DUCKDB
    DUCKDB --> API
    API -->|dados agregados| DASH
    NGINX -->|"/api/, /docs"| API
    NGINX -->|"/app/"| DASH
    NGINX -->|"/ (estático)"| SITE[Landing page<br/>site/index.html]

    subgraph Seguranca["Segurança"]
        HARD[SSH key only<br/>root/senha desabilitados]
        SECL[Security List OCI<br/>portas 22, 80, 443]
        FW
    end
```

## Componentes

| Componente | Função | Custo |
|---|---|---|
| **Oracle Cloud A1.Flex** | Compute (Docker Compose: Nginx + API + Dashboard + Airflow + DuckDB + MinIO) | R$ 0/mês |
| **GitHub Actions** | CI/CD diário | R$ 0/mês (público) |
| **MinIO** | Object storage camada Bronze | Docker local (sem custo adicional) |

> **Nota de reconciliação (26/08/2026):** o ADR-007 original (Sprint 0B)
> havia desenhado um deploy split, com o dashboard no Streamlit
> Community Cloud consumindo a API remota. Esse tier nunca foi usado —
> desde a primeira implementação até a Sprint 10, o dashboard sempre
> rodou no mesmo Docker Compose da VPS Oracle. O ADR-036 (Sprint 10)
> formaliza o estado real: Nginx roteando `/app/` → Streamlit,
> `/api/`+`/docs` → FastAPI, `/` → landing estática. Diagrama e tabela
> acima corrigidos para refletir a arquitetura de fato implementada.

## Fluxo de CI/CD vs. Execução Diária do Pipeline

> Dois fluxos distintos: o CI/CD parte de `ACTIONS`, a execução diária
> parte de `TIMER` — não confundir um com o outro (ADR-034).

**CI/CD (GitHub Actions, a cada push/PR):**
1. Push/PR na branch `main` dispara `ci.yml`
2. Roda Gitleaks (secret scan), Ruff (lint) e `pytest --cov` (gate 80%)
3. GitHub Actions **não** executa o pipeline de dados — apenas valida
   o código

**Execução diária do pipeline (ADR-034, systemd timer na VPS):**
1. `observatorio-pipeline.timer` dispara às 03:00 America/Sao_Paulo
2. Sobe o perfil `pipeline` do Docker Compose (Airflow) e aciona o DAG
   `observatorio_pipeline` (bronze → silver → gold_core →
   `executar_analytics` → gold_analytics, ver ADR-035)
3. API FastAPI e Dashboard Streamlit (`/app/`) já ficam sempre no ar
   no perfil padrão, servidos juntos na Oracle Cloud atrás do mesmo
   Nginx — não dependem da execução do pipeline para responder
