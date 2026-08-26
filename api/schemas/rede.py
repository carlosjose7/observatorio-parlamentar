"""api/schemas/rede.py — contratos de resposta da API (Sprint 6, Onda 3).

`GET /rede/comunidades` agrupa os nós do grafo bipartido já materializado
(Gold `network_nodes`, ADR-030) por `comunidade_id`. Endpoint de LEITURA de
resultado — não recalcula particionamento/comunidades (regra da Onda 2/3,
mesma fronteira do `/parlamentares/{id}/rede`). O nome do nó é resolvido por
join com as dimensões (identidade vigente do SCD2, ADR-020 + fornecedor).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NoComunidade(BaseModel):
    """Um nó da comunidade, com métricas materializadas e nome resolvido."""

    model_config = ConfigDict(extra="forbid")

    id_no: int
    tipo_no: str
    nome: str | None
    pagerank: float
    degree_centrality: float


class ComunidadeItem(BaseModel):
    """Comunidade num período — agrupamento por `comunidade_id` do ADR-030."""

    model_config = ConfigDict(extra="forbid")

    comunidade_id: int
    periodo: int
    tamanho: int
    nos: list[NoComunidade]


class ListaComunidades(BaseModel):
    """Todas as comunidades materializadas (sem paginação — grão pequeno)."""

    model_config = ConfigDict(extra="forbid")

    total: int
    itens: list[ComunidadeItem]


class ArestaFornecedor(BaseModel):
    """Uma interação fornecedor→parlamentar no grafo materializado."""

    model_config = ConfigDict(extra="forbid")

    id_parlamentar: int
    nome: str | None
    sigla_partido: str | None
    sigla_uf: str | None
    periodo: int
    valor_total: float


class RedeFornecedor(BaseModel):
    """`GET /rede/fornecedores/{id}` — a rede INVERSA da do parlamentar.

    Mesma fronteira do `/parlamentares/{id}/rede`: leitura das arestas já
    materializadas (`network_edges`, ADR-030) com nomes resolvidos pelas
    dimensões — a API não recalcula grafo.
    """

    model_config = ConfigDict(extra="forbid")

    id_fornecedor: int
    nome_fornecedor: str
    total_recebido: float
    num_parlamentares: int
    arestas: list[ArestaFornecedor]
