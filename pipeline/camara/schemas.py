"""Contratos Bronze e Silver para despesas da Câmara dos Deputados.

Fonte: GET /deputados/{id}/despesas (dadosabertos.camara.leg.br)
Ver data_dictionary.md §3.1 para a exploração empírica dos campos.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from pipeline.contracts import LoadMetadata, TipoDocumento


class CamaraBronzeDespesa(BaseModel):
    """Registro bruto de despesa da API da Câmara, tipado mas não transformado.

    A camada Bronze preserva o formato original da fonte exatamente
    como recebido — incluindo campos mortos (`num_ressarcimento`,
    `cod_tipo_documento`), conforme o princípio de "raw exato" da
    arquitetura medalhão (arch_medalhao.md).
    """

    ano: int
    mes: int
    cnpj_cpf_fornecedor: str | None = Field(
        default=None, alias="cnpjCpfFornecedor"
    )
    cod_documento: str = Field(
        ..., alias="codDocumento", description="VARCHAR — formato GUID confirmado para passagens aéreas"
    )
    cod_lote: int = Field(..., alias="codLote")
    cod_tipo_documento: int = Field(
        ..., alias="codTipoDocumento", description="Campo morto — sempre 0"
    )
    data_documento: str = Field(
        ..., alias="dataDocumento", description="String ISO bruta, sem parsing na Bronze"
    )
    nome_fornecedor: str = Field(..., alias="nomeFornecedor")
    num_documento: str = Field(..., alias="numDocumento")
    num_ressarcimento: str | None = Field(
        default=None, alias="numRessarcimento", description="Campo morto — 99.8% nulo"
    )
    parcela: int
    tipo_despesa: str = Field(..., alias="tipoDespesa")
    tipo_documento: str = Field(..., alias="tipoDocumento")
    url_documento: str | None = Field(default=None, alias="urlDocumento")
    valor_documento: float = Field(..., alias="valorDocumento")
    valor_glosa: float = Field(..., alias="valorGlosa")
    valor_liquido: float = Field(..., alias="valorLiquido")

    metadata: LoadMetadata

    class Config:
        populate_by_name = True


class CamaraSilverDespesa(BaseModel):
    """Registro de despesa limpo e tipado, pronto para resolução na Gold.

    Aplica: parsing de data ISO, classificação CNPJ/CPF (ADR-011),
    descarta campos mortos (num_ressarcimento, cod_tipo_documento).
    """

    ano: int
    mes: int
    cnpj_cpf_valor: str | None = Field(
        default=None,
        description="Dígitos sanitizados (CNPJ em claro) ou dígitos pendentes de HMAC (CPF) — hash aplicado na carga Gold",
    )
    tipo_documento: TipoDocumento | None
    cod_documento: str = Field(..., description="VARCHAR, nunca convertido para numérico")
    data_documento: date
    nome_fornecedor: str
    tipo_despesa: str
    tipo_documento_fiscal: str = Field(..., description="tipoDocumento original — Nota Fiscal, Recibo, etc.")
    url_documento: str | None
    valor_documento: Decimal
    valor_glosa: Decimal
    valor_liquido: Decimal

    metadata: LoadMetadata