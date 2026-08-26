"""api/schemas/agregacoes.py — contratos dos endpoints de agregação (análises).

Agregações de `fact_despesa` para os gráficos do dashboard (gastos por UF,
por partido, top parlamentares e série temporal mensal). Seguem o mesmo selo
de contrato de resposta dos demais schemas (`extra="forbid"`) e usam `Moeda`
(`api/schemas/_common.py`) para emitir número JSON, não string.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.schemas._common import Moeda

_PadroesComuns = ConfigDict(extra="forbid")


class _ContratoResposta(BaseModel):
    model_config = _PadroesComuns


class AgregacaoItem(_ContratoResposta):
    """Uma linha de agregação (UF, partido ou parlamentar)."""

    rotulo: str = Field(..., description="Sigla da UF/partido ou nome do parlamentar")
    total: Moeda = Field(..., description="Soma de valor_liquido no recorte")
    num_despesas: int = Field(..., description="Quantidade de despesas no recorte")


class ListaAgregacao(_ContratoResposta):
    """Envelope de `GET /agregacoes/por-uf`, `/por-partido` e `/top-parlamentares`."""

    limite: int = Field(..., description="Teto de itens aplicado na consulta")
    itens: list[AgregacaoItem]


class SerieTemporalItem(_ContratoResposta):
    """Um mês da série temporal de despesas (AAAAMM)."""

    periodo: str = Field(..., description="Mês de competência no formato AAAAMM")
    total: Moeda
    num_despesas: int


class SerieTemporal(_ContratoResposta):
    """Envelope de `GET /agregacoes/no-tempo`."""

    itens: list[SerieTemporalItem]


class TopFornecedorItem(_ContratoResposta):
    """Um fornecedor no ranking por valor recebido."""

    id_fornecedor: int
    nome_fornecedor: str
    total_recebido: Moeda
    num_parlamentares: int = Field(
        ..., description="Parlamentares distintos que pagaram esse fornecedor"
    )


class ListaTopFornecedores(_ContratoResposta):
    """Envelope de `GET /agregacoes/top-fornecedores`."""

    limite: int = Field(..., description="Teto de itens aplicado na consulta")
    itens: list[TopFornecedorItem]
