"""pipeline/camara/votacao_transform.py — Bronze → Silver de presença/votação (Onda 1, ADR-058).

Lê os Parquets Bronze do domínio votação (`camara_eventos/`, `camara_presenca/`,
`camara_votacoes/`, `camara_votos/`, `camara_orientacoes/`), normaliza para o
grão Silver canônico e chama `carregar_tabela_silver` — dedup independente
(ADR-014) + gate Pandera (ADR-013) antes de persistir.

Normalização (mesmo padrão ADR-024 — par `_bruto` + `_normalizada`, sentinela
`nao_mapeado`, de-para versionado com teste, nunca NULL silencioso):
- `situacao` do evento → taxonomia {encerrada, em_andamento, convocada,
  nao_mapeado}. O gate "só Encerrada conta" vive no Gold (fact_* filtram
  `situacao_normalizada = 'encerrada`); a Silver preserva todas.
- `tipoVoto` → {sim, nao, abstencao, artigo17, obstrucao, nao_mapeado}
  (vocabulário observado em votação nominal real 2611313-31, n=396).
- `orientacaoVoto` viaja bruta na Silver; `seguiu_partido` é derivado no Gold
  (regra ADR-058 Decisão 4: '' e 'Liberado' → NULL; voto fora do binário → NULL).

Diferente das cargas legadas, cada `carregar_*` aqui garante a tabela mesmo
com Bronze vazio (df vazio com schema fixo — `avaliar_qualidade` trata vazio
sem exceção), dispensando passo "garantido" separado no DAG: o `dbt build`
completo nunca quebra por fonte ausente.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

from pipeline.normalize import parse_date_multi_format
from pipeline.silver import ResultadoCargaSilver, carregar_tabela_silver, garantir_tabela_silver
from pipeline.storage import Storage

logger = structlog.get_logger()

DIRETORIO_EVENTOS = Path("camara_eventos")
DIRETORIO_PRESENCA = Path("camara_presenca")
DIRETORIO_VOTACOES = Path("camara_votacoes")
DIRETORIO_VOTOS = Path("camara_votos")
DIRETORIO_ORIENTACOES = Path("camara_orientacoes")

NAO_MAPEADO = "nao_mapeado"

# De-para versionado da situação do evento (ADR-058 Decisão 3, padrão ADR-024).
# Chaves em lowercase sem acento; valor fora do mapa → `nao_mapeado` (nunca
# NULL silencioso — auditável pelo bruto).
_DE_PARA_SITUACAO_EVENTO: dict[str, str] = {
    "encerrada": "encerrada",
    "em andamento": "em_andamento",
    "convocada": "convocada",
    "em andamento - votacao": "em_andamento",
}

# De-para versionado do voto nominal (ADR-058 Decisão 3). `obstrucao` é valor
# conhecido de outras votações mas não observado na amostra 2611313-31 —
# entra como candidato explícito; qualquer outro valor → `nao_mapeado`.
_DE_PARA_TIPO_VOTO: dict[str, str] = {
    "sim": "sim",
    "não": "nao",
    "nao": "nao",
    "abstenção": "abstencao",
    "abstencao": "abstencao",
    "artigo 17": "artigo17",
    "obstrução": "obstrucao",
    "obstrucao": "obstrucao",
}


def _normalizar(texto: object, de_para: dict[str, str]) -> str:
    """Aplica o de-para (lowercase/stripped) com sentinela `nao_mapeado`."""
    if texto is None:
        return NAO_MAPEADO
    chave = str(texto).strip().lower()
    if not chave:
        return NAO_MAPEADO
    return de_para.get(chave, NAO_MAPEADO)


def normalizar_situacao_evento(situacao: object) -> str:
    """Normaliza a situação do evento para a taxonomia canônica (ADR-058)."""
    return _normalizar(situacao, _DE_PARA_SITUACAO_EVENTO)


def normalizar_tipo_voto(tipo_voto: object) -> str:
    """Normaliza o voto nominal para a taxonomia canônica (ADR-058)."""
    return _normalizar(tipo_voto, _DE_PARA_TIPO_VOTO)


COLUNAS_SILVER_EVENTO = [
    "id_evento",
    "data_inicio",
    "data_fim",
    "descricao_tipo",
    "situacao_bruta",
    "situacao_normalizada",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

COLUNAS_SILVER_PRESENCA = [
    "id_evento",
    "id_deputado",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

COLUNAS_SILVER_VOTACAO = [
    "id_votacao",
    "id_evento",
    "descricao",
    "aprovacao",
    "data_registro",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

COLUNAS_SILVER_VOTO = [
    "id_votacao",
    "id_deputado",
    "tipo_voto_bruto",
    "voto_normalizado",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

COLUNAS_SILVER_ORIENTACAO = [
    "id_votacao",
    "sigla_bancada",
    "orientacao_bruta",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]


def _metadados(df_bronze: pd.DataFrame, n: int) -> dict[str, pd.Series]:
    """Colunas RF-12 repetidas em todas as Silver do domínio."""
    return {
        "run_id": df_bronze["run_id"] if "run_id" in df_bronze.columns else pd.Series([None] * n),
        "pipeline_version": df_bronze["pipeline_version"]
        if "pipeline_version" in df_bronze.columns
        else pd.Series([None] * n),
        "execution_timestamp": df_bronze["execution_timestamp"]
        if "execution_timestamp" in df_bronze.columns
        else pd.Series([None] * n),
        "source_version": df_bronze["source_version"]
        if "source_version" in df_bronze.columns
        else pd.Series([None] * n),
    }


def construir_silver_evento(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o Bronze de eventos para o grão Silver (1 linha por evento)."""
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_EVENTO)
    n = len(df_bronze)
    df = pd.DataFrame(
        {
            "id_evento": df_bronze["id_evento"].astype("Int64"),
            "data_inicio": pd.to_datetime(
                df_bronze["data_inicio"].map(parse_date_multi_format)
            ).astype("datetime64[ns]"),
            "data_fim": pd.to_datetime(df_bronze["data_fim"].map(parse_date_multi_format)).astype(
                "datetime64[ns]"
            )
            if "data_fim" in df_bronze.columns
            else pd.Series([None] * n),
            "descricao_tipo": df_bronze.get("descricao_tipo"),
            "situacao_bruta": df_bronze.get("situacao"),
            "situacao_normalizada": df_bronze.get("situacao").map(normalizar_situacao_evento)
            if "situacao" in df_bronze.columns
            else pd.Series([NAO_MAPEADO] * n),
            **_metadados(df_bronze, n),
        }
    )
    return df[COLUNAS_SILVER_EVENTO]


def construir_silver_presenca(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o lote de presença (1 linha por (evento, deputado) PRESENTE)."""
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_PRESENCA)
    n = len(df_bronze)
    df = pd.DataFrame(
        {
            "id_evento": df_bronze["id_evento"].astype("Int64"),
            "id_deputado": df_bronze["id_deputado"].astype("Int64"),
            **_metadados(df_bronze, n),
        }
    )
    return df[COLUNAS_SILVER_PRESENCA]


def construir_silver_votacao(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o Bronze de votações (1 linha por votação nominal)."""
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_VOTACAO)
    n = len(df_bronze)
    df = pd.DataFrame(
        {
            "id_votacao": df_bronze["id_votacao"].astype("Int64"),
            "id_evento": df_bronze["id_evento"].astype("Int64"),
            "descricao": df_bronze.get("descricao"),
            "aprovacao": df_bronze.get("aprovacao"),
            "data_registro": pd.to_datetime(
                df_bronze["data_registro"].map(parse_date_multi_format)
            ).astype("datetime64[ns]")
            if "data_registro" in df_bronze.columns
            else pd.Series([None] * n),
            **_metadados(df_bronze, n),
        }
    )
    return df[COLUNAS_SILVER_VOTACAO]


def construir_silver_voto(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o Bronze de votos (1 linha por (votação, deputado))."""
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_VOTO)
    n = len(df_bronze)
    df = pd.DataFrame(
        {
            "id_votacao": df_bronze["id_votacao"].astype("Int64"),
            "id_deputado": df_bronze["id_deputado"].astype("Int64"),
            "tipo_voto_bruto": df_bronze.get("tipo_voto"),
            "voto_normalizado": df_bronze.get("tipo_voto").map(normalizar_tipo_voto)
            if "tipo_voto" in df_bronze.columns
            else pd.Series([NAO_MAPEADO] * n),
            **_metadados(df_bronze, n),
        }
    )
    return df[COLUNAS_SILVER_VOTO]


def construir_silver_orientacao(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o Bronze de orientações (1 linha por (votação, bancada))."""
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_ORIENTACAO)
    n = len(df_bronze)
    df = pd.DataFrame(
        {
            "id_votacao": df_bronze["id_votacao"].astype("Int64"),
            "sigla_bancada": df_bronze.get("sigla_bancada"),
            "orientacao_bruta": df_bronze.get("orientacao_voto"),
            **_metadados(df_bronze, n),
        }
    )
    return df[COLUNAS_SILVER_ORIENTACAO]


def _carregar(
    storage: Storage,
    run_id: str,
    diretorio: Path,
    tabela: str,
    construir,
    chaves_dedup: list[str],
    campos_criticos: list[str] | None,
) -> ResultadoCargaSilver:
    """Lê um diretório Bronze, normaliza e carrega (tabela sempre garantida)."""
    df_bronze = storage.read_dir(diretorio)
    if df_bronze.empty:
        logger.warning("silver_votacao_sem_dados", tabela=tabela, run_id=run_id)
        garantir_tabela_silver(tabela)
    df_silver = construir(df_bronze)
    return carregar_tabela_silver(
        df_silver,
        tabela,
        run_id,
        chaves_dedup=chaves_dedup,
        campos_criticos=campos_criticos,
    )


def carregar_silver_evento(storage: Storage, run_id: str) -> ResultadoCargaSilver:
    """Carrega `silver_evento` (chave: `id_evento`)."""
    return _carregar(
        storage, run_id, DIRETORIO_EVENTOS, "silver_evento",
        construir_silver_evento, ["id_evento"], ["data_inicio", "situacao_normalizada"],
    )


def carregar_silver_presenca(storage: Storage, run_id: str) -> ResultadoCargaSilver:
    """Carrega `silver_presenca` (chave: `id_evento`, `id_deputado`)."""
    return _carregar(
        storage, run_id, DIRETORIO_PRESENCA, "silver_presenca",
        construir_silver_presenca, ["id_evento", "id_deputado"], ["id_evento", "id_deputado"],
    )


def carregar_silver_votacao(storage: Storage, run_id: str) -> ResultadoCargaSilver:
    """Carrega `silver_votacao` (chave: `id_votacao`)."""
    return _carregar(
        storage, run_id, DIRETORIO_VOTACOES, "silver_votacao",
        construir_silver_votacao, ["id_votacao"], ["id_evento"],
    )


def carregar_silver_voto(storage: Storage, run_id: str) -> ResultadoCargaSilver:
    """Carrega `silver_voto` (chave: `id_votacao`, `id_deputado`)."""
    return _carregar(
        storage, run_id, DIRETORIO_VOTOS, "silver_voto",
        construir_silver_voto, ["id_votacao", "id_deputado"], ["voto_normalizado"],
    )


def carregar_silver_orientacao(storage: Storage, run_id: str) -> ResultadoCargaSilver:
    """Carrega `silver_orientacao` (chave: `id_votacao`, `sigla_bancada`)."""
    return _carregar(
        storage, run_id, DIRETORIO_ORIENTACOES, "silver_orientacao",
        construir_silver_orientacao, ["id_votacao", "sigla_bancada"], ["sigla_bancada"],
    )
