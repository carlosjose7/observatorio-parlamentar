"""api/schemas/fornecedores.py — contratos de resposta de fornecedores (Onda 2).

Endpoints `GET /fornecedores` (lista), `GET /fornecedores/{cnpj_cpf_valor}`
(perfil) e `GET /fornecedores/{cnpj_cpf_valor}/parlamentares`.

`cnpj_cpf_valor` é o valor como armazenado na Gold (ADR-011): CNPJ em texto
claro, **CPF pseudonimizado com HMAC-SHA256** (nunca o número cru) — a API
expõe o Gold sem derreferenciar a pseudonimização. `tipo_documento` (contrato
`pipeline/contracts.py:TipoDocumento`) é obrigatório para interpretar o valor.
Busca por CPF cru nos endpoints `{cnpj_cpf_valor}` não casa (retorna 404); a
busca por CNPJ casa exatamente.

Regra de arquitetura da Onda 2: a API apenas expõe o que está materializado
no Gold — nenhum agregado é (re)calculado em runtime com lógica nova; quando
existe, é leitura direta sobre `fact_despesa`/dimensões.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.schemas._common import Moeda
from pipeline.contracts import TipoDocumento

_PadroesComuns = ConfigDict(extra="forbid")


class _ContratoResposta(BaseModel):
    model_config = _PadroesComuns


class FornecedorResumo(_ContratoResposta):
    """Item da listagem de fornecedores (`dim_fornecedor`, ADR-011)."""

    id_fornecedor: int
    cnpj_cpf_valor: str | None = Field(
        default=None, description="CNPJ em texto claro; CPF como hash HMAC (pseudonimizado)"
    )
    tipo_documento: TipoDocumento | None
    nome_fornecedor: str


class ListaFornecedores(_ContratoResposta):
    """Envelope paginado de `GET /fornecedores`."""

    pagina: int
    limite: int
    total: int = Field(..., description="Total de fornecedores sob os filtros")
    itens: list[FornecedorResumo]


class PerfilFornecedor(_ContratoResposta):
    """Perfil de um fornecedor (`GET /fornecedores/{cnpj_cpf_valor}`).

    A dimensão mais agregados de gasto sobre `fact_despesa` promovido
    (ADR-018) — leitura sobre o Gold, sem recálculo de análise.
    """

    id_fornecedor: int
    cnpj_cpf_valor: str | None
    tipo_documento: TipoDocumento | None
    nome_fornecedor: str
    id_municipio: int | None = None
    num_despesas: int = Field(..., description="Nº de despesas promovidas do fornecedor")
    valor_liquido_total: Moeda = Field(..., description="Soma de valor_liquido das despesas")


class FornecedorContexto(_ContratoResposta):
    """Cabeçalho do fornecedor no envelope de parlamentares."""

    id_fornecedor: int
    cnpj_cpf_valor: str | None
    tipo_documento: TipoDocumento | None
    nome_fornecedor: str


class ParlamentarFornecedor(_ContratoResposta):
    """Parlamentar que gastou com um fornecedor + agregado de gasto."""

    id_parlamentar: int
    nome: str
    sigla_partido: str
    sigla_uf: str
    total_gasto: Moeda = Field(..., description="Soma de valor_liquido do parlamentar no fornecedor")
    num_despesas: int


class ListaParlamentaresFornecedor(_ContratoResposta):
    """Envelope paginado de `GET /fornecedores/{cnpj_cpf_valor}/parlamentares`."""

    fornecedor: FornecedorContexto
    pagina: int
    limite: int
    total: int = Field(..., description="Nº de parlamentares distintos que gastaram no fornecedor")
    itens: list[ParlamentarFornecedor]
