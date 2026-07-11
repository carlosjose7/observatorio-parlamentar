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
        UFW[UFW<br/>Firewall]
    end

    subgraph Streamlit["Streamlit Community Cloud"]
        DASH[Dashboard<br/>Páginas 01-10]
    end

    REPO -->|git push| ACTIONS
    ACTIONS -->|executa pipeline| AIRFLOW
    SECRETS -.->|env vars| ACTIONS
    AIRFLOW --> MINIO
    AIRFLOW --> DUCKDB
    DUCKDB --> API
    API -->|dados agregados| DASH

    subgraph Seguranca["Segurança"]
        HARD[SSH key only<br/>root/senha desabilitados]
        SECL[Security List OCI<br/>portas 22, 80, 443]
        UFW
    end
```

## Componentes

| Componente | Função | Custo |
|---|---|---|
| **Oracle Cloud A1.Flex** | Compute (Docker Compose + Airflow + DuckDB + API) | R$ 0/mês |
| **Streamlit Community Cloud** | Dashboard público | R$ 0/mês |
| **GitHub Actions** | CI/CD diário | R$ 0/mês (público) |
| **MinIO** | Object storage camada Bronze | Docker local (sem custo adicional) |

## Fluxo de CI/CD

1. Push na branch `main` dispara GitHub Actions
2. Pipeline executa ingestão, transformação e carga
3. API FastAPI é servida na Oracle Cloud
4. Dashboard Streamlit consome a API
