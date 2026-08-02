"""Contratos Bronze e Silver para o Portal da Transparência (CGU).

Fontes: GET /cartoes, GET /emendas (api.portaldatransparencia.gov.br)
Ver data_dictionary.md §3.3 para a exploração empírica dos campos.

NOTA (Sprint 1): o mapeamento Gold para as entidades da CGU está
definido em ADR-012 — fact_emenda e fact_cartao_cpgf, ambas com grão
próprio, sem convergência forçada em fact_despesa.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from pipeline.contracts import LoadMetadata, TipoDocumento


class CguBronzeEstabelecimento(BaseModel):
    """Objeto aninhado de estabelecimento dentro dos registros de cartão CPGF."""

    id: int
    cnpj_formatado: str | None = Field(default=None, alias="cnpjFormatado")
    cpf_formatado: str | None = Field(
        default=None, alias="cpfFormatado", description="Campo morto — 100% vazio"
    )
    nome: str
    razao_social_receita: str = Field(..., alias="razaoSocialReceita")
    tipo: str
    numero_inscricao_social: str | None = Field(
        default=None, alias="numeroInscricaoSocial", description="Campo morto — 100% vazio"
    )

    class Config:
        populate_by_name = True


class CguBronzePortador(BaseModel):
    """Objeto aninhado do portador (titular do cartão) nos registros de cartão CPGF."""

    nome: str
    cpf_formatado: str = Field(..., alias="cpfFormatado", description="Já mascarado pela fonte, ex: ***.122.497-**")
    nis: str | None = Field(default=None, description="Campo morto — 100% vazio")

    class Config:
        populate_by_name = True


class CguBronzeUnidadeGestora(BaseModel):
    """Objeto aninhado unidadeGestora — mapeia para dim_unidade_gestora (ADR-010)."""

    codigo: str
    nome: str

    class Config:
        populate_by_name = True


class CguBronzeCartao(BaseModel):
    """Registro bruto de transação de cartão CPGF da API da CGU."""

    id: int
    mes_extrato: str = Field(..., alias="mesExtrato")
    data_transacao: str = Field(..., alias="dataTransacao", description="DD/MM/AAAA bruto, sem parsing na Bronze")
    valor_transacao: str = Field(..., alias="valorTransacao", description="String bruta pt-BR, pode conter separador de milhar")
    tipo_cartao_codigo: str = Field(..., alias="tipoCartao")
    estabelecimento: CguBronzeEstabelecimento
    portador: CguBronzePortador
    unidade_gestora: CguBronzeUnidadeGestora = Field(..., alias="unidadeGestora")

    metadata: LoadMetadata

    class Config:
        populate_by_name = True


class CguBronzeEmenda(BaseModel):
    """Registro bruto de emenda parlamentar da API da CGU."""

    ano: int
    codigo_emenda: str = Field(..., alias="codigoEmenda")
    tipo_emenda: str = Field(..., alias="tipoEmenda")
    nome_autor: str = Field(..., alias="nomeAutor")
    numero_emenda: str = Field(..., alias="numeroEmenda")
    funcao: str
    subfuncao: str
    localidade_do_gasto: str = Field(..., alias="localidadeDoGasto")
    valor_empenhado: str = Field(..., alias="valorEmpenhado", description="String bruta pt-BR com milhar e decimal")
    valor_liquidado: str = Field(..., alias="valorLiquidado")
    valor_pago: str = Field(..., alias="valorPago")
    valor_resto_inscrito: str = Field(..., alias="valorRestoInscrito")
    valor_resto_cancelado: str = Field(..., alias="valorRestoCancelado")
    valor_resto_pago: str = Field(..., alias="valorRestoPago")

    metadata: LoadMetadata

    class Config:
        populate_by_name = True


class CguSilverCartao(BaseModel):
    """Registro de cartão CPGF limpo.

    cnpj_cpf_valor aqui resolve o CNPJ do ESTABELECIMENTO (comerciante),
    não o CPF do portador — o CPF do portador chega pré-mascarado pela
    fonte e não é re-identificável, portanto é armazenado como está
    (já compatível com a LGPD por construção, sem necessidade de HMAC).
    """

    data_transacao: date
    valor_transacao: Decimal
    estabelecimento_cnpj_valor: str | None
    estabelecimento_tipo_documento: TipoDocumento | None
    estabelecimento_nome: str
    portador_nome: str
    portador_cpf_mascarado: str = Field(..., description="Pré-mascarado pela fonte CGU, armazenado como está")
    unidade_gestora_codigo: str
    unidade_gestora_nome: str

    metadata: LoadMetadata


class CguSilverEmenda(BaseModel):
    """Registro de emenda parlamentar limpo."""

    ano: int
    codigo_emenda: str
    tipo_emenda: str
    nome_autor: str
    funcao: str
    subfuncao: str
    localidade_do_gasto: str
    valor_empenhado: Decimal
    valor_liquidado: Decimal
    valor_pago: Decimal

    metadata: LoadMetadata