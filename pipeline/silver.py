"""pipeline/silver.py — orquestração da camada Silver (Sprint 3).

Entre Bronze (Parquet raw) e Gold (star schema) fica a Silver, que
aplica, para cada fonte/entidade:

1. Normalização multi-fonte via `pipeline.normalize` (ADR-016): datas,
   valores monetários pt-BR e CNPJ/CPF para os formatos canônicos.
2. Deduplicação própria e independente pela chave de negócio *após*
   normalização (ADR-014) — não reaproveita a dedup da Bronze.
3. Gate de validação Pandera sobre o DataFrame agregado
   (`pipeline.quality`, ADR-013): regras de lote (intervalo de datas,
   unicidade, não-negatividade). Linhas que violam vão para quarentena,
   nunca são descartadas nem derrubam a execução.
4. Persistência do Data Quality Report estruturado em DuckDB
   (`data_quality_report` particionado por `run_id`), ADR-015.

Este módulo expõe o fluxo como funções testáveis; os `transform.py` por
fonte são os pontos que chamam estas funções com os DataFrames Bronze.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import structlog

from pipeline.config import get_env
from pipeline.quality import (
    LinhaQualidadeReport,
    avaliar_qualidade,
    schema_silver_cartao,
    schema_silver_despesa,
    schema_silver_emenda,
    schema_silver_parlamentar,
)

logger = structlog.get_logger()

DIRETORIO_QUARENTENA = Path("_quarantine")

# Contrato canônico de `silver_parlamentar` — tabela alimentada por ambas as
# Casas (Câmara e Senado, Onda 2 / ADR-020). Fica aqui (Silver compartilhado)
# para que os `transform.py` por fonte mapeiem o mesmo grão de colunas.
#
# ADR-024 (paridade semântica): `id_legislativa` é **derivada do calendário
# legislativo a partir da `data`** (as-of do snapshot) — nunca copiada da API,
# pois cada API mede coisa diferente. `id_legislatura_fonte` guarda o valor
# bruto original para auditoria. `situacao_bruta` é o valor original e
# `situacao_normalizada` a taxonomia mínima comum (de-para versionado).
COLUNAS_SILVER_PARLAMENTAR = [
    "fonte",
    "id_parlamentar",
    "nome",
    "sigla_partido",
    "sigla_uf",
    "id_legislatura",
    "id_legislatura_fonte",
    "situacao_bruta",
    "situacao_normalizada",
    "url_foto",
    "data",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]


# ── Deduplicação independente (ADR-014) ──────────────────────────


def deduplicar_silver(
    df: pd.DataFrame, chaves: list[str], run_id: str, tabela: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dedup por chave de negócio pós-normalização (ADR-014).

    Mantém a primeira observação de cada chave e devolve as linhas
    removidas separadamente. A Bronze já deduplicou por chave bruta;
    esta camada re-avalia o grão pela chave *normalizada*, cobrindo
    overlaps entre partições de execuções distintas.

    Args:
        df: DataFrame Silver.
        chaves: Lista de colunas que compõem a chave de negócio.
        run_id: Identificador da execução.
        tabela: Nome da tabela Silver (para log).

    Returns:
        (df sem duplicatas, duplicatas removidas).
    """
    if df.empty:
        return df, pd.DataFrame()

    duplicadas = df.duplicated(subset=chaves, keep="first")
    if not duplicadas.any():
        return df, pd.DataFrame()

    df_unicos = df[~duplicadas].copy()
    removidas = df[duplicadas].copy()
    logger.info(
        "dedup_silver",
        tabela=tabela,
        run_id=run_id,
        chave=chaves,
        total=len(df),
        removidas=len(removidas),
    )
    return df_unicos, removidas


# ── Persistência DuckDB da Silver e DQ Report (ADR-015) ──────────


@dataclass
class ResultadoCargaSilver:
    """Resultado da carga de uma tabela Silver.

    Attributes:
        tabela: Nome da tabela carregada.
        aceitos: DataFrame validado e persistido.
        deduplicadas: Linhas removidas por dedup independente.
        quarentena: DataFrame isolado por falha de qualidade.
    """

    tabela: str
    aceitos: pd.DataFrame
    deduplicadas: pd.DataFrame
    quarentena: pd.DataFrame


def _conectar_duckdb():
    """Abre uma conexão DuckDB no caminho de `DUCKDB_DATABASE_PATH`.

    Cria o diretório pai se necessário (ex: primeira carga em ambiente novo
    onde `data/silver/` ainda não existe) — `duckdb.connect` não cria
    diretórios e falharia com IO Error.
    """
    from pathlib import Path

    import duckdb

    caminho = Path(get_env().duckdb_database_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(caminho))


def _criar_tabela_se_necessario(con, tabela: str, df: pd.DataFrame) -> None:
    """Cria a tabela com o schema declarativo (se mapeado) ou inferido; se a
    tabela já existe, **migra o schema legado** adicionando as colunas novas
    presentes no DataFrame. Nunca faz CREATE/DROP destrutivo nem perde dados.

    Schema explícito (`pipeline.schemas_silver`): as tabelas Silver têm os
    tipos DuckDB e descrições declarados no código — evita a inferência
    frágil do DuckDB (coluna de texto integralmente nula era inferida como
    `INTEGER`, derrubando o INSERT de outra fonte com ConversionException) e
    documenta o catálogo via `COMMENT ON`. Tabelas de controle
    (`data_quality_report`, `quarantine_*`, `dedup_removidas_*`) seguem com
    inferência (colunas internas, sem risco).

    Migração de schema legado (corretivo QA BUG-004): colunas que faltam são
    adicionadas via `ALTER TABLE ADD COLUMN` com o tipo que o DuckDB infere
    para o DataFrame (mesmo tipo do CREATE). Colunas `object` do pandas são
    normalizadas para `string` antes da inferência.
    """
    from pipeline.schemas_silver import descricao_para_tabela, schema_para_tabela

    esquema = schema_para_tabela(tabela)

    # Normaliza colunas object para string e registra o DataFrame de referência
    # para criação/migração de schema (usado em ambos os ramos abaixo).
    definicao = df.copy()
    for col in definicao.columns:
        if definicao[col].dtype.kind == "O":
            definicao[col] = definicao[col].astype("string")
    con.register("tmp_define", definicao)

    if esquema is not None:
        # DDL explícito: CREATE TABLE IF NOT EXISTS com tipos declarados.
        cols_ddl = ", ".join(
            f'"{col}" {tipo}' for col, (tipo, _desc) in esquema.items()
        )
        con.execute(f"CREATE TABLE IF NOT EXISTS {tabela} ({cols_ddl})")
        descricao = descricao_para_tabela(tabela)
        if descricao:
            con.execute(
                f"COMMENT ON TABLE {tabela} IS "
                f"'{descricao.replace(chr(39), chr(39) * 2)}'"
            )
    else:
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {tabela} AS SELECT * FROM tmp_define LIMIT 0"
        )

        # Corrige inferência incorreta: coluna de texto (object/string) inferida
        # como numérica porque todos os valores são nulos na primeira carga.
        tipos_inferidos = {
            linha[0]: linha[1]
            for linha in con.execute(f"DESCRIBE {tabela}").fetchall()
        }
        numericos = {"INTEGER", "BIGINT", "DOUBLE", "FLOAT", "HUGEINT", "SMALLINT"}
        for col in definicao.columns:
            if definicao[col].dtype.kind in ("O", "U", "S"):
                if tipos_inferidos.get(col) in numericos:
                    con.execute(
                        f'ALTER TABLE {tabela} ALTER COLUMN "{col}" TYPE VARCHAR'
                    )
                    logger.warning(
                        "correcao_tipo_texto",
                        tabela=tabela,
                        coluna=col,
                        tipo_inferido=tipos_inferidos.get(col),
                    )

    # Migração de schema legado: adiciona colunas novas presentes no DataFrame.
    existentes = {
        linha[0]
        for linha in con.execute(
            f"SELECT column_name FROM information_schema.columns"
            f" WHERE table_name = '{tabela}'"
        ).fetchall()
    }
    novos = [col for col in df.columns if col not in existentes]
    if novos:
        # Tipo da coluna nova: declarativo (se a tabela tem schema explícito e a
        # coluna está nele) ou inferido do DataFrame (tabelas de controle).
        tipos = {}
        if esquema is not None:
            tipos = {col: tipo for col, (tipo, _desc) in esquema.items()}
        tipos_inferidos = {
            linha[0]: linha[1]
            for linha in con.execute("DESCRIBE SELECT * FROM tmp_define").fetchall()
        }
        for col in novos:
            tipo = tipos.get(col) or tipos_inferidos.get(col)
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} {tipo}")
        logger.info(
            "migracao_schema_silver",
            tabela=tabela,
            colunas_adicionadas=novos,
        )

    # Aplica comentários de coluna do schema declarativo (se mapeado).
    if esquema is not None:
        for col, (_tipo, desc) in esquema.items():
            if col not in existentes:
                continue
            con.execute(
                f"COMMENT ON COLUMN {tabela}.{col} IS "
                f"'{desc.replace(chr(39), chr(39) * 2)}'"
            )


def _insert_por_nome(con, tabela: str, registro: str, colunas: list[str]) -> None:
    """INSERT com lista explícita de colunas (corretivo QA BUG-004).

    Com a migração, `colunas ⊆ colunas da tabela`; o INSERT por nome (em vez
    de `SELECT *` posicional) garante o mapeamento campo-a-campo mesmo quando
    a tabela legada tem um subconjunto de colunas.
    """
    cols = ", ".join(f'"{c}"' for c in colunas)
    con.execute(f"INSERT INTO {tabela} ({cols}) SELECT {cols} FROM {registro}")


def escrever_validos_duckdb(
    df: pd.DataFrame, tabela: str, chaves_dedup: list[str] | None = None
) -> None:
    """Persiste linhas válidas na tabela DuckDB da Silver (INSERT/MERGE).

    A carga é idempotente por **chave de negócio** (corretivo QA BUG-003):
    quando a tabela já existe e `chaves_dedup` é informado, os registros
    já consolidados com a mesma chave são removidos antes do INSERT — a
    carga vira um UPSERT por chave natural. Re-execuções da Silver e
    correções de registros refletem nos registros existentes em vez de
    duplicarem e criarem novo `cod_documento`. O `cod_documento` continua
    sendo atribuído uma única vez na dedup (ADR-023/ADR-024) e é herdado
    pelo registro substituído (nenhuma duplicação de documento).
    """
    if df.empty:
        return
    con = _conectar_duckdb()
    try:
        _criar_tabela_se_necessario(con, tabela, df)
        con.register("tmp_validos", df)
        if chaves_dedup:
            cond = " and ".join(f"t.{col} = v.{col}" for col in chaves_dedup)
            con.execute(
                f"DELETE FROM {tabela} t USING tmp_validos v WHERE {cond}"
            )
        _insert_por_nome(con, tabela, "tmp_validos", list(df.columns))
    finally:
        con.close()


def escrever_quarentena_duckdb(df: pd.DataFrame, tabela: str) -> str | None:
    """Grava linhas em quarentena em DuckDB e retorna caminho relativo.

    A quarentena nunca interrompe o pipeline (ADR-013).
    """
    if df.empty:
        return None
    nome = "quarantine_" + tabela
    con = _conectar_duckdb()
    try:
        _criar_tabela_se_necessario(con, nome, df)
        con.register("tmp_q", df)
        _insert_por_nome(con, nome, "tmp_q", list(df.columns))
    finally:
        con.close()
    return str(DIRETORIO_QUARENTENA / f"{tabela}.parquet")


def escrever_dedup_removidas_duckdb(df: pd.DataFrame, tabela: str) -> None:
    """Grava as linhas removidas pela dedup independente em DuckDB.

    A dedup (ADR-014) calcula `removidas` mas nada persistia — apenas o
    agregado ia ao log. Persistir em `dedup_removidas_{tabela}` (padrão
    `quarantine_` reusado) permite distinguir, auditando, remoção por
    duplicação real de remoção por chave mascarada (ex: `codigo_emenda =
    "S/I"`, ADR-017) e reprocessar manualmente sem reextração da fonte.
    """
    if df.empty:
        return
    nome = "dedup_removidas_" + tabela
    con = _conectar_duckdb()
    try:
        _criar_tabela_se_necessario(con, nome, df)
        con.register("tmp_dedup", df)
        _insert_por_nome(con, nome, "tmp_dedup", list(df.columns))
    finally:
        con.close()


def persistir_qualidade_report(linha: LinhaQualidadeReport) -> None:
    """Persiste uma linha do Data Quality Report em `data_quality_report`."""
    con = _conectar_duckdb()
    try:
        dados = pd.DataFrame(
            [
                {
                    "run_id": str(linha.run_id),
                    "tabela": linha.tabela,
                    "total_registros": linha.total_registros,
                    "registros_validos": linha.registros_validos,
                    "registros_quarentena": linha.registros_quarentena,
                    "registros_deduplicados": linha.registros_deduplicados,
                    "regras_violadas": json.dumps(linha.regras_violadas),
                    "percentual_nulos_criticos": linha.percentual_nulos_criticos,
                    "execution_timestamp": linha.execution_timestamp.isoformat()
                    if linha.execution_timestamp
                    else None,
                }
            ]
        )
        _criar_tabela_se_necessario(con, "data_quality_report", dados)
        con.register("tmp_dq", dados)
        _insert_por_nome(con, "data_quality_report", "tmp_dq", list(dados.columns))
        logger.info(
            "data_quality_report_persistido",
            run_id=str(linha.run_id),
            tabela=linha.tabela,
        )
    finally:
        con.close()


# ── Fluxo principal de uma tabela Silver ─────────────────────────


def _schema_para(tabela: str):
    """Retorna o schema Pandera da tabela Silver (ADR-013).

    Schemas declarados: `silver_despesa`, `silver_cartao`,
    `silver_emenda` e `silver_parlamentar`; novas tabelas são adicionadas
    à medida que os transform.py por fonte forem integrados.
    """
    if tabela == "silver_despesa":
        return schema_silver_despesa()
    if tabela == "silver_cartao":
        return schema_silver_cartao()
    if tabela == "silver_emenda":
        return schema_silver_emenda()
    if tabela == "silver_parlamentar":
        return schema_silver_parlamentar()
    raise ValueError(f"Schema Pandera não registrado para a tabela Silver: {tabela}")


def carregar_tabela_silver(
    df: pd.DataFrame,
    tabela: str,
    run_id: str,
    *,
    chaves_dedup: list[str],
    campos_criticos: list[str] | None = None,
) -> ResultadoCargaSilver:
    """Orquestra dedup + gate Pandera + persistência de uma tabela Silver.

    Executa, com falhas isoladas (não derrubam a execução):
      1. Dedup independente por chave de negócio pós-normalização (ADR-014).
      2. Validação Pandera com separação de quarentena (ADR-013).
      3. Persistência DuckDB dos válidos, da quarentena e do DQ report.

    Args:
        df: DataFrame Silver já normalizado, pronto para validar.
        tabela: Nome da tabela Silver (ex: `silver_despesa`).
        run_id: Identificador da execução.
        chaves_dedup: Colunas da chave de negócio para dedup independente.
        campos_criticos: Campo(s) usados para o percentual de nulos.

    Returns:
        `ResultadoCargaSilver`.
    """
    schema = _schema_para(tabela)
    df_dedup, removidas = deduplicar_silver(df, chaves_dedup, run_id, tabela)

    df_validos, linha = avaliar_qualidade(
        df_dedup,
        schema,
        run_id=run_id,
        tabela=tabela,
        campos_criticos=campos_criticos,
        chaves_negocio=chaves_dedup,
    )
    linha.registros_deduplicados = len(removidas)
    linha.execution_timestamp = datetime.now(UTC)

    # O gate recebe todo o DataFrame deduplicado; as linhas em quarentena
    # são reextraídas do conjunto original por índices já isolados internamente.
    quarentena = _quarentena_do_conjunto(df_dedup, df_validos)

    escrever_validos_duckdb(df_validos, tabela, chaves_dedup)
    escrever_quarentena_duckdb(quarentena, tabela)
    escrever_dedup_removidas_duckdb(removidas, tabela)
    persistir_qualidade_report(linha)

    return ResultadoCargaSilver(
        tabela=tabela,
        aceitos=df_validos,
        deduplicadas=removidas,
        quarentena=quarentena,
    )


def _quarentena_do_conjunto(
    df_original: pd.DataFrame, df_validos: pd.DataFrame
) -> pd.DataFrame:
    """Isola as linhas que não passaram no gate Pandera."""
    if df_validos.empty and not df_original.empty:
        return df_original.copy()
    if df_validos.empty:
        return pd.DataFrame()
    mascara = ~df_original.index.isin(df_validos.index)
    return df_original.loc[mascara].copy()
