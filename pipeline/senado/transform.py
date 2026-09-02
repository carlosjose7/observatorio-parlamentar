"""pipeline/senado/transform.py — Bronze → Silver do Senado (Trilha B, ADR-023).

Duas cargas Silver a partir do Bronze do Senado:

1. Despesas CEAPS → `silver_despesa` (fonte='senado'): lê o Parquet Bronze,
   normaliza para o grão canônico e delega a carga ao `carregar_tabela_silver`.
2. Dados mestres de senadores (Onda 2, ADR-020) → `silver_parlamentar`
   (fonte='senado'), mesmo contrato da Câmara; o snapshot de
   `parlamento/senado/` alimenta o SCD2 de `dim_parlamentar`.

Diferenças de fonte (ADR-016):
- Datas em DD/MM/AAAA e valores em string pt-BR (`parse_decimal_ptbr`).
- Não existe glosa — `valor_glosa` é fixado em 0.0.
- `fonte='senado'`; chave de negócio `["fonte", "cod_documento"]`.

O CPF é pseudonimizado na própria Silver (ADR-033), via HMAC-SHA256
(`pipeline.pseudonymize`) — aqui apenas a digitação limpa
(`clean_document_number`) + classificação (ADR-011) + hash do CPF.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

from pipeline.contracts import resolve_tipo_documento
from pipeline.normalize import parse_date_multi_format, parse_decimal_ptbr
from pipeline.parlamento import legislatura_para_data, normalizar_situacao
from pipeline.pseudonymize import pseudonymize_cpf_column
from pipeline.silver import (
    COLUNAS_SILVER_PARLAMENTAR,
    ResultadoCargaSilver,
    carregar_tabela_silver,
)
from pipeline.storage import Storage

logger = structlog.get_logger()

COLUNAS_SILVER = [
    "fonte",
    "id_parlamentar",
    "nome_parlamentar",
    "ano",
    "mes",
    "cod_documento",
    "data_documento",
    "tipo_despesa",
    "cnpj_cpf_valor",
    "tipo_documento",
    "nome_fornecedor",
    "valor_liquido",
    "valor_glosa",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

DIRETORIO_BRONZE = Path("senado")

DIRETORIO_PARLAMENTO = Path("parlamento/senado")


def construir_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o DataFrame Bronze do Senado para o formato canônico Silver.

    Args:
        df_bronze: DataFrame com os registros brutos CEAPS do Senado
            (leitura de `storage`, com metadados achatados).

    Returns:
        DataFrame com as colunas canônicas de `silver_despesa` (fonte='senado')
        ou DataFrame vazio com o schema fixo quando não há registros.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER)

    n = len(df_bronze)
    classificados = [resolve_tipo_documento(v) for v in df_bronze["cnpj_cpf"]]
    tipos_documento = [par[1] for par in classificados]
    cnpj_cpf_valor = pseudonymize_cpf_column(
        (par[0] for par in classificados),
        (t.value if t else None for t in tipos_documento),
    )
    tipo_documento = [t.value if t else None for t in tipos_documento]

    df = pd.DataFrame(
        {
            "fonte": ["senado"] * n,
            "id_parlamentar": pd.Series([None] * n, dtype="object"),
            "nome_parlamentar": df_bronze["senador"],
            "ano": df_bronze["ano"].astype("int64"),
            "mes": df_bronze["mes"].astype("int64"),
            "cod_documento": df_bronze["cod_documento"].astype(str),
            "data_documento": pd.to_datetime(
                df_bronze["data"].map(parse_date_multi_format)
            ),
            "tipo_despesa": df_bronze["tipo_despesa"],
            "cnpj_cpf_valor": cnpj_cpf_valor,
            "tipo_documento": tipo_documento,
            "nome_fornecedor": df_bronze["fornecedor"],
            "valor_liquido": pd.to_numeric(
                df_bronze["valor_reembolsado"].map(parse_decimal_ptbr)
            ).astype("float64"),
            "valor_glosa": pd.Series([0.0] * n, dtype="float64"),
            "run_id": df_bronze["run_id"],
            "pipeline_version": df_bronze["pipeline_version"],
            "execution_timestamp": df_bronze["execution_timestamp"],
            "source_version": df_bronze["source_version"],
        }
    )
    return df[COLUNAS_SILVER]


def carregar_silver_despesa(
    storage: Storage, run_id: str
) -> ResultadoCargaSilver | None:
    """Lê o Bronze do Senado e carrega `silver_despesa` (fonte='senado').

    Args:
        storage: Persistência Parquet do Bronze (injetável) — lê o
            diretório `senado/` inteiro (todas as partições).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_BRONZE)
    if df_bronze.empty:
        logger.warning("silver_senado_sem_dados", run_id=run_id)
        return None

    df_silver = construir_silver(df_bronze)
    return carregar_tabela_silver(
        df_silver,
        "silver_despesa",
        run_id,
        chaves_dedup=["fonte", "cod_documento"],
        campos_criticos=["valor_liquido", "nome_fornecedor", "data_documento"],
    )


def _gerar_backfill_scd2(
    df_bronze: pd.DataFrame,
    df_despesas: pd.DataFrame | None,
) -> pd.DataFrame:
    """Gera snapshots sintéticos de legislaturas passadas para senadores.

    A API do Senado só expõe ``lista/atual`` (senadores em exercício),
    resultando em um único snapshot por senador. Este backfill cria rows
    adicionais para legislaturas históricas em que o senador teve despesas,
    permitindo que o SCD2 de ``dim_parlamentar`` gere janelas de vigência
    que cobrem o período das despesas CEAPS (2015–hoje).

    Partido e UF são aproximados (valor atual da API) — a coluna
    ``partido_uf_aproximado`` sinaliza isso para auditoria.

    Args:
        df_bronze: Snapshot Bronze dos senadores (saída de ``extract_senadores``).
        df_despesas: DataFrame de ``silver_despesa`` (fonte='senado') com colunas
            ``nome_parlamentar``, ``data_documento``. Se None ou vazio, sem backfill.

    Returns:
        DataFrame com rows sintéticas (mesmo schema de ``construir_silver_parlamentar``)
        ou vazio quando não há dados de despesa.
    """
    if df_bronze.empty or df_despesas is None or df_despesas.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_PARLAMENTAR)

    from pipeline.parlamento import LEGISLATURAS

    rows_backfill: list[dict] = []
    for _, senador in df_bronze.iterrows():
        nome = senador.get("nome_parlamentar") or senador.get("nome_completo") or ""
        if not nome:
            continue

        despesas_senador = df_despesas[df_despesas["nome_parlamentar"] == nome]
        if despesas_senador.empty:
            continue

        min_date = despesas_senador["data_documento"].min()
        max_date = despesas_senador["data_documento"].max()

        # Converte para date para comparar com LEGISLATURAS (datetime.date)
        if hasattr(min_date, "date"):
            min_date = min_date.date()
        if hasattr(max_date, "date"):
            max_date = max_date.date()

        for num_leg, inicio, fim in LEGISLATURAS:
            if inicio > max_date or fim <= min_date:
                continue

            data_snapshot = pd.Timestamp(inicio)
            id_leg = (legislatura_para_data(inicio) or 0)

            rows_backfill.append(
                {
                    "fonte": "senado",
                    "id_parlamentar": int(senador["id_senador"]),
                    "nome": senador["nome_parlamentar"] or senador.get("nome_completo", ""),
                    "sigla_partido": senador.get("sigla_partido"),
                    "sigla_uf": senador.get("sigla_uf"),
                    "id_legislatura": id_leg,
                    "id_legislatura_fonte": int(senador.get("id_legislatura", 0) or 0),
                    "situacao_bruta": senador.get("situacao"),
                    "situacao_normalizada": normalizar_situacao(
                        "senado", senador.get("situacao")
                    ),
                    "url_foto": senador.get("url_foto"),
                    "partido_uf_aproximado": True,
                    "data": data_snapshot,
                    "run_id": senador.get("run_id", ""),
                    "pipeline_version": senador.get("pipeline_version", ""),
                    "execution_timestamp": senador.get("execution_timestamp", ""),
                    "source_version": senador.get("source_version", ""),
                }
            )

    if not rows_backfill:
        return pd.DataFrame(columns=COLUNAS_SILVER_PARLAMENTAR)

    return pd.DataFrame(rows_backfill)[COLUNAS_SILVER_PARLAMENTAR]


def construir_silver_parlamentar(
    df_bronze: pd.DataFrame,
    df_despesas: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Mapeia o snapshot Bronze de `parlamento/senado/` para o grão canônico.

    Mesmo contrato de `silver_parlamentar` da Câmara (ADR-020), com
    `fonte='senado'`: em `nome` prefere o nome parlamentar (urna) e recai no
    completo. **ADR-024**: `id_legislatura` é derivada do calendário a partir
    de `data` (a API do Senado mede a legislatura do *mandato* — semântica
    distinta da Câmara); o bruto vai para `id_legislatura_fonte`.
    `situacao_bruta` (ex: Titular) e `situacao_normalizada` (de-para
    versionado). `data` = `data_status` (as-of do SCD2).

    Quando ``df_despesas`` é fornecido, gera snapshots de backfill para
    legislaturas históricas em que o senador teve despesas (partido/UF
    aproximados, sinalizados por ``partido_uf_aproximado=True``).

    Args:
        df_bronze: DataFrame achatado dos snapshots (`records_to_dataframe`).
        df_despesas: DataFrame de `silver_despesa` (fonte='senado') para
            inferir legislaturas servidas. None = sem backfill.

    Returns:
        DataFrame canônico de `silver_parlamentar` (fonte='senado') ou vazio
        com o schema fixo quando não há registros.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_PARLAMENTAR)

    n = len(df_bronze)
    data = pd.to_datetime(df_bronze["data_status"], errors="coerce")
    id_legislatura = pd.Series(
        [
            (legislatura_para_data(ts.date()) or 0) if pd.notna(ts) else 0
            for ts in data
        ],
        dtype="int64",
    )

    df_atual = pd.DataFrame(
        {
            "fonte": ["senado"] * n,
            "id_parlamentar": df_bronze["id_senador"].astype("int64"),
            "nome": df_bronze["nome_parlamentar"].fillna(df_bronze["nome_completo"]),
            "sigla_partido": df_bronze["sigla_partido"],
            "sigla_uf": df_bronze["sigla_uf"],
            "id_legislatura": id_legislatura,
            "id_legislatura_fonte": df_bronze["id_legislatura"].astype("Int64"),
            "situacao_bruta": df_bronze["situacao"],
            "situacao_normalizada": df_bronze["situacao"].map(
                lambda v: normalizar_situacao("senado", v)
            ),
            "url_foto": df_bronze.get("url_foto"),
            "partido_uf_aproximado": False,
            "data": data,
            "run_id": df_bronze["run_id"],
            "pipeline_version": df_bronze["pipeline_version"],
            "execution_timestamp": df_bronze["execution_timestamp"],
            "source_version": df_bronze["source_version"],
        }
    )

    df_backfill = _gerar_backfill_scd2(df_bronze, df_despesas)

    if df_backfill.empty:
        return df_atual[COLUNAS_SILVER_PARLAMENTAR]

    return pd.concat([df_atual, df_backfill], ignore_index=True)[
        COLUNAS_SILVER_PARLAMENTAR
    ]


def carregar_silver_parlamentar(
    storage: Storage, run_id: str
) -> ResultadoCargaSilver | None:
    """Lê o snapshot Bronze e carrega `silver_parlamentar` (fonte='senado').

    Consolida todo o diretório `parlamento/senado/` (todos os dias já
    ingeridos): a dedup independente colapsa snapshots idênticos pela chave
    `(fonte, id_parlamentar, data)` e o gate Pandera das cargas, junto com o
    da Câmara, mantém a dimensão parlamentar completa (ADR-020).

    Quando há dados de despesa CEAPS disponíveis, gera snapshots de backfill
    para legislaturas históricas (partido/UF aproximados).

    Args:
        storage: Persistência Parquet do Bronze (injetável).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_PARLAMENTO)
    if df_bronze.empty:
        logger.warning("silver_parlamento_senado_sem_dados", run_id=run_id)
        return None

    df_despesas = None
    try:
        from pipeline.config import load_env_settings

        settings = load_env_settings()
        import duckdb

        con = duckdb.connect(settings.duckdb_database_path, read_only=True)
        try:
            df_despesas = con.execute(
                "SELECT nome_parlamentar, data_documento "
                "FROM silver.silver_despesa WHERE fonte = 'senado'"
            ).fetchdf()
        finally:
            con.close()
    except Exception:
        logger.debug("backfill_scd2_sem_despesas", run_id=run_id)

    df_silver = construir_silver_parlamentar(df_bronze, df_despesas)
    return carregar_tabela_silver(
        df_silver,
        "silver_parlamentar",
        run_id,
        chaves_dedup=["fonte", "id_parlamentar", "data"],
        campos_criticos=["nome", "id_parlamentar"],
    )
