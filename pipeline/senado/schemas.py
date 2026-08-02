"""Contratos Bronze e Silver para despesas do Senado Federal (CEAPS).

Fonte: despesa_ceaps_{ano}.csv (ISO-8859-1, separador ';').
Ver data_dictionary.md §3.2 para a exploração empírica dos campos.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from pipeline.contracts import LoadMetadata, TipoDocumento


class SenadoBronzeDespesa(BaseModel):
    """Registro bruto de despesa do CSV CEAPS do Senado, tipado mas não transformado.

    Valores permanecem no formato bruto pt-BR (vírgula decimal, datas
    DD/MM/AAAA, CNPJ/CPF formatado) — conversão acontece somente na Silver.
    """

    ano: int = Field(..., alias="ANO")
    mes: int = Field(..., alias="MES")
    senador: str = Field(..., alias="SENADOR")
    tipo_despesa: str = Field(..., alias="TIPO_DESPESA")
    cnpj_cpf: str = Field(..., alias="CNPJ_CPF", description="Formatado com pontuação")
    fornecedor: str = Field(..., alias="FORNECEDOR")
    documento: str = Field(..., alias="DOCUMENTO")
    data: str = Field(..., alias="DATA", description="String DD/MM/AAAA bruta, sem parsing na Bronze")
    detalhamento: str | None = Field(default=None, alias="DETALHAMENTO")
    valor_reembolsado: str = Field(
        ..., alias="VALOR_REEMBOLSADO", description="String bruta pt-BR com vírgula decimal"
    )
    cod_documento: int = Field(..., alias="COD_DOCUMENTO", description="Chave natural para deduplicação")

    metadata: LoadMetadata

    class Config:
        populate_by_name = True


class SenadoSilverDespesa(BaseModel):
    """Registro de despesa limpo e tipado, pronto para resolução na Gold.

    Aplica: parsing de data DD/MM/AAAA, conversão de vírgula decimal
    para Decimal, sanitização e classificação CNPJ/CPF (ADR-011).
    """

    ano: int
    mes: int
    senador: str
    tipo_despesa: str
    cnpj_cpf_valor: str | None
    tipo_documento: TipoDocumento | None
    fornecedor: str
    documento: str
    data: date
    detalhamento: str | None
    valor_reembolsado: Decimal
    cod_documento: int = Field(..., description="Chave de deduplicação — única por despesa")

    metadata: LoadMetadata