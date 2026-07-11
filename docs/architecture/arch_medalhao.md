# Arquitetura Medalhão

```mermaid
flowchart TB
    subgraph Fontes["Fontes Externas"]
        C[Câmara<br/>API REST]
        S[Senado<br/>API REST]
        T[Portal da Transparência<br/>API + CSV]
        R[Receita Federal<br/>CNPJ CSV]
        I[IBGE<br/>API + CSV]
    end

    subgraph Ingestao["Ingestão (Airflow)"]
        DAG[DAGs de Ingestão<br/>Retry automático<br/>Rate limiting<br/>Watermark]
    end

    subgraph Bronze["Camada Bronze (Parquet + MinIO)"]
        direction LR
        B1[bronze_camara_despesas]
        B2[bronze_senado_despesas]
        B3[bronze_transparencia_despesas]
        B4[bronze_cnpj]
        B5[bronze_ibge_municipios]
    end

    subgraph Silver["Camada Silver (DuckDB)"]
        direction LR
        SL[silver_parlamentar<br/>silver_fornecedor<br/>silver_despesa<br/>silver_partido<br/>silver_municipio]
        Q[Validação Pandera<br/>Data Quality Report]
    end

    subgraph Gold["Camada Gold (DuckDB)"]
        direction LR
        DIM[dimensões<br/>dim_parlamentar<br/>dim_fornecedor<br/>dim_partido<br/>dim_estado<br/>dim_municipio<br/>dim_categoria_despesa<br/>dim_data]
        FACT[fatoss<br/>fact_despesa<br/>fact_presenca<br/>fact_votacao<br/>fact_gastos_mensais]
        ANL[tabelas analíticas<br/>supplier_concentration<br/>politician_similarity<br/>expense_outliers<br/>supplier_growth<br/>network_edges<br/>network_nodes<br/>risk_scores]
    end

    subgraph API["Camada de Serviço (FastAPI)"]
        EP[endpoints REST<br/>/parlamentares<br/>/fornecedores<br/>/anomalias<br/>/rede<br/>/agent/*]
    end

    subgraph Dashboard["Camada de Apresentação (Streamlit)"]
        P[páginas<br/>01 a 10]
    end

    Fontes --> Ingestao
    Ingestao --> Bronze
    Bronze -->|dados brutos| Silver
    Silver -->|dados limpos| Gold
    Gold -->|métricas e agregados| API
    API --> Dashboard
    Q -.->|relatório| Silver
```

## Camadas

| Camada | Formato | Propósito |
|---|---|---|
| **Bronze** | Parquet + MinIO | Dados raw exatos, metadados de ingestão, hash, particionado por fonte |
| **Silver** | DuckDB | Limpeza, normalização, deduplicação, validação Pandera |
| **Gold** | DuckDB | Star schema, métricas semânticas, tabelas analíticas, scores de risco |

## Convenções de Nomenclatura

| Camada | Padrão | Exemplo |
|---|---|---|
| Bronze | `bronze_{fonte}_{entidade}` | `bronze_camara_despesas` |
| Silver | `silver_{entidade}` | `silver_parlamentar` |
| Gold (fato) | `fact_{entidade}` | `fact_despesa` |
| Gold (dimensão) | `dim_{entidade}` | `dim_fornecedor` |
| Gold (analítica) | `{descricao}` | `supplier_concentration` |
