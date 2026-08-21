"""api/routers/fornecedores.py — endpoints de fornecedores (PROJECT_CONTEXT §11).

Onda 2: `GET /fornecedores` (lista paginada com filtros), `GET /fornecedores/
{cnpj_cpf_valor}` (perfil com agregados de gasto) e `GET /fornecedores/
{cnpj_cpf_valor}/parlamentares` (parlamentares que gastaram no fornecedor).

A API expõe o Gold, não recria o pipeline analítico (regra da Onda 2):
perfil/agregados são leitura direta sobre `dim_fornecedor` +
`fact_despesa`/`dim_parlamentar` materializados. CPF está pseudonimizado
(ADR-011) — busca por CPF cru não casa (404 honesto); CNPJ casa exatamente.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.repo import (
    GoldIndisponivel,
    listar_fornecedores,
    listar_parlamentares_fornecedor,
    obter_perfil_fornecedor,
)
from api.schemas.fornecedores import (
    ListaFornecedores,
    ListaParlamentaresFornecedor,
    PerfilFornecedor,
)
from pipeline.config import get_api

logger = structlog.get_logger()

router = APIRouter(prefix="/fornecedores", tags=["fornecedores"])

_config = get_api()


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


@router.get("", response_model=ListaFornecedores)
def get_fornecedores(
    nome: str | None = Query(default=None, max_length=100, description="Filtro parcial sobre o nome do fornecedor"),
    tipo_documento: str | None = Query(default=None, pattern="^(CNPJ|CPF)$", description="Tipo de documento (CNPJ ou CPF)"),
    pagina: int = Query(default=_config.pagina_padrao, ge=1, description="Página corrente (1-based)"),
    limite: int = Query(default=_config.limite_padrao, ge=1, le=_config.limite_maximo, description="Itens por página (máx 100)"),
) -> ListaFornecedores:
    try:
        return listar_fornecedores(
            nome=nome, tipo_documento=tipo_documento, pagina=pagina, limite=limite
        )
    except GoldIndisponivel as exc:
        raise _erro_gold("fornecedores", exc)


@router.get("/{cnpj_cpf_valor}", response_model=PerfilFornecedor)
def get_fornecedor(cnpj_cpf_valor: str) -> PerfilFornecedor:
    try:
        resultado = obter_perfil_fornecedor(cnpj_cpf_valor)
    except GoldIndisponivel as exc:
        raise _erro_gold("fornecedor_perfil", exc)
    if resultado is None:
        raise HTTPException(status_code=404, detail=f"Fornecedor {cnpj_cpf_valor} não encontrado")
    return resultado


@router.get("/{cnpj_cpf_valor}/parlamentares", response_model=ListaParlamentaresFornecedor)
def get_parlamentares_do_fornecedor(
    cnpj_cpf_valor: str,
    pagina: int = Query(default=_config.pagina_padrao, ge=1, description="Página corrente (1-based)"),
    limite: int = Query(default=_config.limite_padrao, ge=1, le=_config.limite_maximo, description="Itens por página (máx 100)"),
) -> ListaParlamentaresFornecedor:
    try:
        resultado = listar_parlamentares_fornecedor(
            cnpj_cpf_valor=cnpj_cpf_valor, pagina=pagina, limite=limite
        )
    except GoldIndisponivel as exc:
        raise _erro_gold("fornecedor_parlamentares", exc)
    if resultado is None:
        raise HTTPException(status_code=404, detail=f"Fornecedor {cnpj_cpf_valor} não encontrado")
    return resultado
