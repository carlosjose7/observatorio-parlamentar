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

    id_deputado: int = Field(
        ...,
        description="Identidade do deputado na fonte (GET /deputados/{id}/despesas). "
        "NÃO vem no corpo do item — o id do deputado é injetado pela iteração "
        "do endpoint; sem ele a linhagem Silver→Gold de fact_despesa.id_parlamentar "
        "seria perdida na Bronze.",
    )
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
    id_parlamentar: int | None = Field(
        default=None,
        description="Identidade parlamentar provinda da Bronze (`id_deputado`). "
        "NOT NULL por contrato no Gold (FactDespesa); a Silver preserva o valor "
        "da fonte sem resolver vigência (o SCD2 é resolvido no dbt, ADR-020).",
    )
    cnpj_cpf_valor: str | None = Field(
        default=None,
        description="Dígitos sanitizados (CNPJ em claro) ou dígitos pendentes de HMAC (CPF) — hash aplicado no transform Silver (ADR-033)",
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


class CamaraBronzeDeputado(BaseModel):
    """Registro bruto do snapshot de um deputado (dados mestres, Onda 2).

    Fonte: GET /deputados/{id} (dadosabertos.camara.leg.br). O detalhe retorna
    `dados` como objeto; os atributos rastreados para SCD2 (ADR-020) vivem em
    `ultimoStatus` (partido, UF, situação, legislatura). Bronze preserva o
    formato bruto achatado, sem parsing — `data_status` fica como string ISO.
    """

    id_deputado: int = Field(..., alias="id")
    nome_civil: str = Field(default="", alias="nomeCivil")
    nome_eleitoral: str | None = Field(
        default=None, alias="nomeEleitoral"
    )
    sigla_partido: str | None = Field(..., alias="siglaPartido")
    sigla_uf: str | None = Field(..., alias="siglaUf")
    id_legislatura: int = Field(..., alias="idLegislatura")
    situacao: str | None = Field(default=None, alias="situacao")
    condicao_eleitoral: str | None = Field(
        default=None, alias="condicaoEleitoral"
    )
    data_status: str = Field(
        ..., alias="data", description="Data de vigência do status (ISO)"
    )

    metadata: LoadMetadata

    class Config:
        populate_by_name = True