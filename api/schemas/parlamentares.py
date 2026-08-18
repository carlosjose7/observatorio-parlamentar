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


class PerfilParlamentar(_ContratoResposta):
    """Perfil completo (`GET /parlamentares/{id}`) — versão vigente do SCD2.

    Todas as colunas emitidas por `dim_parlamentar.sql` para a versão
    `is_current`, incluindo os metadados temporais da versão (ADR-020).
    """

    id_parlamentar: int
    surrogate_key: int
    fonte: str
    nome: str
    nome_normalizado: str
    sigla_partido: str
    sigla_uf: str
    situacao_normalizada: str
    id_legislatura: int | None = Field(default=None, description="Última legislatura observada na versão")
    effective_date: date = Field(..., description="Início da vigência da versão")
    end_date: date | None = Field(default=None, description="Fim da vigência — None na versão corrente")
    is_current: bool


class NoRede(_ContratoResposta):
    """Perfil de rede do próprio parlamentar (`network_nodes`, ADR-030)."""

    periodo: int
    pagerank: float
    degree_centrality: float
    comunidade_id: int | None


class ArestaRede(_ContratoResposta):
    """Aresta parlamentar↔fornecedor materializada (`network_edges`, ADR-030)."""

    id_fornecedor: int
    nome_fornecedor: str
    periodo: int
    valor_total: float = Field(..., description="Peso da aresta v_{p,f} no período (valor agregado)")


class RedeParlamentar(_ContratoResposta):
    """Rede do parlamentar (`GET /parlamentares/{id}/rede`).

    Consulta APENAS os resultados materializados pela Sprint 5 no Gold
    (`network_nodes`/`network_edges`) — a API NÃO recalcula PageRank/
    comunidades (regra da Onda 2: expõe o Gold, não recria o pipeline).
    """

    parlamentar: ParlamentarContexto
    nos: list[NoRede]
    arestas: list[ArestaRede]
