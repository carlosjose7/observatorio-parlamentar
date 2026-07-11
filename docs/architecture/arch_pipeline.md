# Fluxo do Pipeline ETL

```mermaid
flowchart LR
    subgraph Fontes["Fontes"]
        C[Câmara<br/>API]
        S[Senado<br/>API]
        T[Transparência<br/>API + CSV]
        R[CNPJ<br/>CSV]
        I[IBGE<br/>API]
    end

    subgraph Pipeline["Pipeline (Airflow DAGs)"]
        EX[extract.py<br/>ingestão incremental<br/>watermark dataInicio]
        BR[bronze.py<br/>persistência Parquet<br/>metadados + hash]
        SL[silver.py<br/>limpeza + padronização<br/>Pandera + dedup]
        GL[gold.py<br/>Star Schema<br/>métricas semânticas]
        AN[analytics.py<br/>scores + anomalias<br/>redes + clusters]
    end

    subgraph Destinos["Destinos"]
        B[bronze/ Parquet]
        S[silver/ DuckDB]
        G[gold/ DuckDB]
    end

    C --> EX
    S --> EX
    T --> EX
    R --> EX
    I --> EX

    EX --> BR
    BR --> B
    B --> SL
    SL --> S
    S --> GL
    GL --> G
    G --> AN

    subgraph Qualidade["Qualidade"]
        Q[quality.py<br/>Data Quality Report<br/>validações Pandera]
    end

    SL -.-> Q
    Q -.->|relatório| SL
```

## Etapas do Pipeline

| Etapa | Módulo | Descrição |
|---|---|---|
| **Ingestão** | `pipeline/{fonte}/extract.py` | Extração incremental com watermark por `dataInicio` |
| **Bronze** | `pipeline/bronze.py` | Persistência raw em Parquet com metadados de ingestão |
| **Silver** | `pipeline/silver.py` | Limpeza, normalização, deduplicação, validação Pandera |
| **Gold** | `pipeline/gold.py` | Construção do Star Schema (fatos + dimensões) |
| **Analytics** | `pipeline/analytics.py` | Scores de risco, anomalias, análise de redes |
| **Qualidade** | `pipeline/quality.py` | Relatório de qualidade de dados por execução |

## Reproductibilidade

Toda execução é rastreável via:
- `run_id` — identificador único da execução
- `pipeline_version` — versão do código no momento da execução
- `execution_timestamp` — timestamp ISO 8601
- `source_version` — data/hora da última modificação da fonte externa
