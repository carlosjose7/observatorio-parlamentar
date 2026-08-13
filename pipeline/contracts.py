"""Contratos compartilhados entre todas as camadas e fontes do pipeline.

Define metadados de carga (reprodutibilidade RF-12) e enums
reutilizados pelos schemas de Bronze, Silver e Gold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class LoadMetadata(BaseModel):
    """Metadados de reprodutibilidade exigidos em toda carga (RF-12).

    Attributes:
        run_id: Identificador único da execução do pipeline.
        pipeline_version: Versão semântica do código que gerou a carga.
        execution_timestamp: Timestamp UTC do momento lógico da execução.
        source_version: Identificador de versão/snapshot da fonte de
            dados (ex: data da resposta da API, data de publicação do CSV).
    """

    run_id: UUID
    pipeline_version: str
    execution_timestamp: datetime
    source_version: str


@dataclass
class ExtractResult:
    """Resultado de uma extração de fonte (Sprint 2 — Pipeline Bronze).

    Attributes:
        records: Registros Bronze tipados, prontos para persistência.
        new_watermark: Novo valor de watermark consolidado (maior
            `dataDocumento`, ano do CSV, mês de extrato etc.), conforme
            versionamento.md §2.
        source_version: Versão da fonte no momento da extração
            (versionamento.md §3).
    """

    records: list[BaseModel] = field(default_factory=list)
    new_watermark: str | None = None
    source_version: str = ""


class TipoDocumento(str, Enum):
    """Tipo de documento resolvido pela regra de comprimento (ADR-011)."""

    CNPJ = "CNPJ"
    CPF = "CPF"
    INVALIDO = "INVALIDO"


class Poder(str, Enum):
    """Poder de governo, usado em dim_orgao (ADR-010)."""

    LEGISLATIVO = "Legislativo"
    EXECUTIVO = "Executivo"
    JUDICIARIO = "Judiciário"


class FonteOrigemUnidadeGestora(str, Enum):
    """Sistema de origem da unidade gestora, dim_unidade_gestora (ADR-010)."""

    SIAFI = "SIAFI"
    CGU = "CGU"
    TESOURO_NACIONAL = "Tesouro Nacional"
    OUTRO = "outro"


def resolve_tipo_documento(cnpj_cpf_raw: str | None) -> tuple[str | None, TipoDocumento | None]:
    """Sanitiza e classifica um campo CNPJ/CPF conforme ADR-011.

    Remove formatação não numérica e classifica por quantidade de
    dígitos. Valor vazio ou nulo nunca é hasheado nem classificado —
    permanece como (None, None), evitando a criação de uma identidade
    de fornecedor fantasma (ADR-011, item 1).

    Args:
        cnpj_cpf_raw: Valor bruto extraído da fonte (formatado ou não,
            possivelmente vazio ou None).

    Returns:
        Uma tupla (dígitos_sanitizados_ou_entrada_para_hash, tipo_documento).
        O chamador é responsável por aplicar HMAC-SHA256 sobre valores
        de CPF antes de persistir — esta função apenas classifica, não
        realiza o hash.
    """
    if not cnpj_cpf_raw or not cnpj_cpf_raw.strip():
        return None, None

    digits = "".join(char for char in cnpj_cpf_raw if char.isdigit())

    if len(digits) == 14:
        return digits, TipoDocumento.CNPJ
    if len(digits) == 11:
        return digits, TipoDocumento.CPF
    return digits, TipoDocumento.INVALIDO