"""pipeline/transparencia/transform.py — Bronze → Silver (CGU: cartões e emendas).

Mesmo contrato dos demais `transform.py` (ADR-023): lê o Parquet Bronze,
  normaliza para o grão Silver canônico e delega a carga ao
  `carregar_tabela_silver`.

Duas entidades com grãos e schemas próprios (ADR-012/ADR-013):
- `silver_cartao` — chave de disponibilidade `["id"]`: a CGU fornece `id`
  nativo de transação (config/sources.yaml declara o campo de dedup da Bronze),
  única chave confiável para a dedup independente da Silver. Ficou marcado
  como "a confirmar" no ADR-023; decisão desta trilha: propagar `id`.
- `silver_emenda` — chave de negócio `["ano", "codigo_emenda"]`; o marcador
  de ausência `"S/I"` é isolado pela regra `codigo_nao_si` do gate Pandera
  (ADR-017); `nome_autor` é normalizado (uppercase sem acento, ADR-016).

Valores monetários pt-BR via `parse_decimal_ptbr`, datas DD/MM/AAAA via
`parse_date_multi_format` e CNPJ/CPF do estabelecimento sanitizado e
classificado (ADR-011). CPF de estabelecimento (11 dígitos) é
pseudonimizado via HMAC-SHA256 na Silver (ADR-033); CNPJ permanece em
texto claro. O `portador_cpf_formatado` já chega mascarado pela CGU e é
persistido como `portador_cpf_mascarado`. Parsers nunca lançam exceção
(ADR-016).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

from pipeline.contracts import resolve_tipo_documento
from pipeline.normalize import (
    normalizar_nome_proprio,
    parse_date_multi_format,
    parse_decimal_ptbr,
)
from pipeline.pseudonymize import pseudonymize_cpf_column
from pipeline.silver import ResultadoCargaSilver, carregar_tabela_silver
from pipeline.storage import Storage

logger = structlog.get_logger()

DIRETORIO_CARTOES = Path("transparencia_cartoes")
DIRETORIO_EMENDAS = Path("transparencia_emendas")

COLUNAS_SILVER_CARTAO = [
    "id",
    "data_transacao",
    "valor_transacao",
    "estabelecimento_cnpj_valor",
    "estabelecimento_tipo_documento",
    "estabelecimento_nome",
    "portador_nome",
    "portador_cpf_mascarado",
    "unidade_gestora_codigo",
    "unidade_gestora_nome",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

COLUNAS_SILVER_EMENDA = [
    "ano",
    "codigo_emenda",
    "tipo_emenda",
    "nome_autor",
    "funcao",
    "subfuncao",
    "localidade_do_gasto",
    "valor_empenhado",
    "valor_liquidado",
    "valor_pago",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]


def _colunas_metadados(df_bronze: pd.DataFrame) -> dict[str, pd.Series]:
    """Colunas RF-12 achatadas na Bronze, transferidas sem transformação."""
    return {
        "run_id": df_bronze["run_id"],
        "pipeline_version": df_bronze["pipeline_version"],
        "execution_timestamp": df_bronze["execution_timestamp"],
        "source_version": df_bronze["source_version"],
    }


def construir_silver_cartao(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o Bronze de cartões CPGF para o formato canônico Silver.

    Args:
        df_bronze: Registros brutos de `transparencia_cartoes/` (metadados
            achatados; objetos aninhados achatados com `_`).

    Returns:
        DataFrame canônico de `silver_cartao` ou vazio com schema fixo.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_CARTAO)

    classificados = [
        resolve_tipo_documento(v)
        for v in df_bronze["estabelecimento_cnpj_formatado"]
    ]
    tipos_documento = [par[1] for par in classificados]
    estabelecimento_cnpj_valor = pseudonymize_cpf_column(
        (par[0] for par in classificados),
        (t.value if t else None for t in tipos_documento),
    )
    estabelecimento_tipo = [t.value if t else None for t in tipos_documento]

    dados = {
        "id": df_bronze["id"].astype("int64"),
        "data_transacao": pd.to_datetime(
            df_bronze["data_transacao"].map(parse_date_multi_format)
        ),
        "valor_transacao": pd.to_numeric(
            df_bronze["valor_transacao"].map(parse_decimal_ptbr)
        ).astype("float64"),
        "estabelecimento_cnpj_valor": estabelecimento_cnpj_valor,
        "estabelecimento_tipo_documento": estabelecimento_tipo,
        "estabelecimento_nome": df_bronze["estabelecimento_nome"],
        "portador_nome": df_bronze["portador_nome"],
        "portador_cpf_mascarado": df_bronze["portador_cpf_formatado"],
        "unidade_gestora_codigo": df_bronze["unidade_gestora_codigo"],
        "unidade_gestora_nome": df_bronze["unidade_gestora_nome"],
        **_colunas_metadados(df_bronze),
    }
    return pd.DataFrame(dados)[COLUNAS_SILVER_CARTAO]


def construir_silver_emenda(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o Bronze de emendas para o formato Silverado.

    Args:
        df_bronze: Registros brutos de `transparencia_emendas/` (metadados
            achatados).

    Returns:
        DataFrame canônico de `silver_emenda` ou vazio com schema fixo.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_EMENDA)

    def _valor(coluna: str) -> pd.Series:
        return pd.to_numeric(df_bronze[coluna].map(parse_decimal_ptbr)).astype(
            "float64"
        )

    dados = {
        "ano": df_bronze["ano"].astype("int64"),
        "codigo_emenda": df_bronze["codigo_emenda"].astype(str),
        "tipo_emenda": df_bronze["tipo_emenda"],
        "nome_autor": df_bronze["nome_autor"].map(normalizar_nome_proprio),
        "funcao": df_bronze["funcao"],
        "subfuncao": df_bronze["subfuncao"],
        "localidade_do_gasto": df_bronze["localidade_do_gasto"],
        "valor_empenhado": _valor("valor_empenhado"),
        "valor_liquidado": _valor("valor_liquidado"),
        "valor_pago": _valor("valor_pago"),
        **_colunas_metadados(df_bronze),
    }
    return pd.DataFrame(dados)[COLUNAS_SILVER_EMENDA]


def carregar_silver_cartao(
    storage: Storage, run_id: str
) -> ResultadoCargaSilver | None:
    """Carrega `silver_cartao` a partir do Bronze de cartões CPGF.

    Args:
        storage: Persistência Parquet do Bronze (injetável) — lê o diretório
            `transparencia_cartoes/` inteiro (todas as partições).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_CARTOES)
    if df_bronze.empty:
        logger.warning("silver_cartao_sem_dados", run_id=run_id)
        return None

    df_silver = construir_silver_cartao(df_bronze)
    return carregar_tabela_silver(
        df_silver,
        "silver_cartao",
        run_id,
        chaves_dedup=["id"],
        campos_criticos=["valor_transacao", "estabelecimento_nome"],
    )


def carregar_silver_emenda(
    storage: Storage, run_id: str
) -> ResultadoCargaSilver | None:
    """Carrega `silver_emenda` a partir do Bronze de emendas.

    Args:
        storage: Persistência Parquet do Bronze (injetável) — lê o diretório
            `transparencia_emendas/` inteiro (todas as partições).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_EMENDAS)
    if df_bronze.empty:
        logger.warning("silver_emenda_sem_dados", run_id=run_id)
        return None

    df_silver = construir_silver_emenda(df_bronze)
    return carregar_tabela_silver(
        df_silver,
        "silver_emenda",
        run_id,
        chaves_dedup=["ano", "codigo_emenda"],
        campos_criticos=["valor_empenhado", "nome_autor"],
    )
