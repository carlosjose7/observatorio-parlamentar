"""Contratos Bronze e Silver para dados do Senado Federal (CEAPS + Onda 2).

- Despesas: despesa_ceaps_{ano}.csv (ISO-8859-1, separador ';').
- Dados mestre de senadores (Onda 2, dim_parlamentar / ADR-020): API de
  Dados Abertos do Senado (legis.senado.leg.br/dadosabertos); o endpoint
  `/senador/lista/atual.json` já retorna, no aninhamento
  `ListaParlamentarEmExercicio.Parlamentares.Parlamentar[]`, os atributos
  rastreados pelo SCD2 — partido, UF e legislatura — sem request por id.

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


class SenadoBronzeParlamentar(BaseModel):
    """Registro bruto do snapshot de um senador (dados mestres, Onda 2).

    Fonte: GET /senador/lista/atual.json (legis.senado.leg.br/dadosabertos).
    O endpoint já entrega, no aninhamento `Parlamentar[]`, os atributos de
    vigência rastreados para SCD2 (ADR-020): partido, UF e legislatura —
    sem request por id (diferente do detalhe da Câmara). Bronze preserva o
    formato achatado; `data_status` = data de execução (as-of do snapshot).

    Attributes:
        id_senador: Código parlamentar da API (identidade na fonte).
        nome_parlamentar: Nome de urna/parlamentar (preferido na resolução).
        nome_completo: Nome completo — fallback quando `nome_parlamentar`
            está vazio.
        sigla_partido: Partido vigente no snapshot (`SiglaPartidoParlamentar`).
        sigla_uf: UF do mandato vigente.
        id_legislatura: Legislatura do mandato (primeira do mandato; 0
            quando a fonte não informa — cai no gate da Silver).
        situacao: Descrição de participação no mandato (ex: Titular).
        data_status: Data de vigência do snapshot (ISO, data de execução).
    """

    id_senador: int
    nome_parlamentar: str
    nome_completo: str | None
    sigla_partido: str | None
    sigla_uf: str | None
    id_legislatura: int
    situacao: str | None
    data_status: str = Field(
        ..., description="Data de vigência do snapshot (ISO, data de execução)"
    )

    metadata: LoadMetadata

    class Config:
        populate_by_name = True