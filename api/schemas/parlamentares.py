"""api/schemas/parlamentares.py — contratos de resposta da API (Sprint 6, Onda 1).

Contratos de saída dos endpoints de negócio do PROJECT_CONTEXT §11 sobre a
camada Gold. Refletem as colunas REALMENTE emitidas pelos modelos dbt do Gold
(ex.: `dim_parlamentar` emite `sigla_partido`/`sigla_uf`/`situacao_normalizada`
— `dim_parlamentar.sql`), não as classes de `pipeline/gold.py`, que são o
contrato estrutural do schema.

`extra="forbid"` é o selo de contrato de resposta (mesmo espírito do
`_StrictModel` do ADR-008): qualquer campo não declarado aqui é rejeitado no
parse, impedindo vazamento de metadados internos do Gold para o cliente.

Moeda é `Decimal`, preservando a leitura de `fact_despesa.valor_liquido`
(contrato `pipeline/gold.py:FactDespesa`) até o encoder JSON da API.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.contracts import TipoDocumento

_PadroesComuns = ConfigDict(extra="forbid")


class _ContratoResposta(BaseModel):
    model_config = _PadroesComuns


class ParlamentarResumo(_ContratoResposta):
    """Item da listagem de parlamentares (versão vigente do SCD2 — ADR-020)."""

    id_parlamentar: int
    nome: str
    sigla_partido: str
    sigla_uf: str
    situacao_normalizada: str
    fonte: str


class ListaParlamentares(_ContratoResposta):
    """Envelope paginado de `GET /parlamentares`."""

    pagina: int = Field(..., description="Página corrente (1-based)")
    limite: int = Field(..., description="Tamanho da página aplicado")
    total: int = Field(..., description="Total de parlamentares vigentes sob os filtros")
    itens: list[ParlamentarResumo]


class ParlamentarContexto(_ContratoResposta):
    """Cabeçalho do parlamentar no envelope de gastos."""

    id_parlamentar: int
    nome: str
    sigla_partido: str
    sigla_uf: str
    situacao_normalizada: str


class GastoItem(_ContratoResposta):
    """Uma despesa parlamentar, com dimensões resolvidas (fornecedor/categoria)."""

    id_despesa: int
    data: date = Field(..., description="Data do documento (via dim_data)")
    ano: int
    mes: int
    tipo_despesa: str | None = Field(
        default=None, description="Descrição da categoria resolvida via dim_categoria_despesa"
    )
    nome_fornecedor: str
    tipo_documento: TipoDocumento
    valor_liquido: Decimal
    valor_glosa: Decimal


class GastosParlamentar(_ContratoResposta):
    """Envelope paginado de `GET /parlamentares/{id}/gastos`."""

    parlamentar: ParlamentarContexto
    pagina: int
    limite: int
    total: int = Field(..., description="Total de despesas do parlamentar sob os filtros")
    itens: list[GastoItem]