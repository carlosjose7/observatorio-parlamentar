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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipeline.contracts import LoadMetadata, TipoDocumento


class CguBronzeEstabelecimento(BaseModel):
    """Objeto aninhado de estabelecimento dentro dos registros de cartão CPGF."""

    id: int = Field(..., description="Identificador do estabelecimento.")
    cnpj_formatado: str | None = Field(default=None, alias="cnpjFormatado", description="CNPJ formatado.")
    cpf_formatado: str | None = Field(
        default=None, alias="cpfFormatado", description="Campo morto — 100% vazio"
    )
    nome: str = Field(..., description="Nome do estabelecimento.")
    razao_social_receita: str = Field(..., alias="razaoSocialReceita", description="Razão social na Receita.")
    tipo: str = Field(..., description="Tipo do estabelecimento.")
    numero_inscricao_social: str | None = Field(
        default=None, alias="numeroInscricaoSocial", description="Campo morto — 100% vazio"
    )

    model_config = ConfigDict(populate_by_name=True)


class CguBronzePortador(BaseModel):
    """Objeto aninhado do portador (titular do cartão) nos registros de cartão CPGF."""

    nome: str = Field(..., description="Nome do portador.")
    cpf_formatado: str = Field(..., alias="cpfFormatado", description="Já mascarado pela fonte, ex: ***.122.497-**")
    nis: str | None = Field(default=None, description="Campo morto — 100% vazio")

    model_config = ConfigDict(populate_by_name=True)


class CguBronzeUnidadeGestora(BaseModel):
    """Objeto aninhado unidadeGestora — mapeia para dim_unidade_gestora (ADR-010)."""

    codigo: str
    nome: str

    model_config = ConfigDict(populate_by_name=True)


class CguBronzeTipoCartao(BaseModel):
    """Objeto aninhado tipoCartao — a CGU expõe o tipo como objeto desde 2026.

    O data_dictionary.md §3.3 documenta `tipoCartao.codigo` como o campo de
    valor (ex: `1` = CPGF). Antes a API retornava a string direta; o modelo
    aceita ambos (ver `CguBronzeCartao`).
    """

    codigo: str

    model_config = ConfigDict(populate_by_name=True)


class CguBronzeCartao(BaseModel):
    """Registro bruto de transação de cartão CPGF da API da CGU."""

    id: int = Field(..., description="Identificador nativo da transação.")
    mes_extrato: str = Field(..., alias="mesExtrato", description="Mês do extrato (MM/AAAA).")
    data_transacao: str = Field(..., alias="dataTransacao", description="DD/MM/AAAA bruto, sem parsing na Bronze")
    valor_transacao: str = Field(..., alias="valorTransacao", description="String bruta pt-BR, pode conter separador de milhar")
    tipo_cartao_codigo: str = Field(..., alias="tipoCartao", description="Código do tipo de cartão (ex: 1 = CPGF).")
    estabelecimento: CguBronzeEstabelecimento = Field(..., description="Estabelecimento onde a transação ocorreu.")
    portador: CguBronzePortador = Field(..., description="Portador/titular do cartão.")
    unidade_gestora: CguBronzeUnidadeGestora = Field(..., alias="unidadeGestora", description="Unidade gestora responsável.")

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("tipo_cartao_codigo", mode="before")
    @classmethod
    def _tipo_cartao_da_fonte(cls, v: object) -> str:
        """Aceita `tipoCartao` como string legada ou objeto `{codigo: ...}`.

        A CGU passou a retornar o objeto (2026); o modelo é resiliente a
        ambos os formatos sem reprocessar o lote anterior.
        """
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and "codigo" in v:
            return str(v["codigo"])
        raise ValueError(f"tipoCartao inválido: {v!r}")


class CguBronzeEmenda(BaseModel):
    """Registro bruto de emenda parlamentar da API da CGU."""

    ano: int = Field(..., description="Ano de competência da emenda.")
    codigo_emenda: str = Field(..., alias="codigoEmenda", description="Código da emenda (chave de negócio).")
    tipo_emenda: str = Field(..., alias="tipoEmenda", description="Tipo da emenda.")
    nome_autor: str = Field(..., alias="nomeAutor", description="Autor da emenda.")
    numero_emenda: str = Field(..., alias="numeroEmenda", description="Número da emenda.")
    funcao: str = Field(..., description="Função orçamentária.")
    subfuncao: str = Field(..., description="Subfunção orçamentária.")
    localidade_do_gasto: str = Field(..., alias="localidadeDoGasto", description="Localidade do gasto.")
    valor_empenhado: str = Field(..., alias="valorEmpenhado", description="String bruta pt-BR com milhar e decimal")
    valor_liquidado: str = Field(..., alias="valorLiquidado", description="String bruta pt-BR.")
    valor_pago: str = Field(..., alias="valorPago", description="String bruta pt-BR.")
    valor_resto_inscrito: str = Field(..., alias="valorRestoInscrito", description="Restos a pagar inscritos (bruto).")
    valor_resto_cancelado: str = Field(..., alias="valorRestoCancelado", description="Restos a pagar cancelados (bruto).")
    valor_resto_pago: str = Field(..., alias="valorRestoPago", description="Restos a pagar pagos (bruto).")

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)


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
