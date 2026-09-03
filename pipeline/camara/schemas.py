"""Contratos Bronze e Silver para despesas da Câmara dos Deputados.

Fonte: GET /deputados/{id}/despesas (dadosabertos.camara.leg.br)
Ver data_dictionary.md §3.1 para a exploração empírica dos campos.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

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
    cod_lote: int = Field(..., alias="codLote", description="Código do lote do documento.")
    cod_tipo_documento: int = Field(
        ..., alias="codTipoDocumento", description="Campo morto — sempre 0"
    )
    data_documento: str = Field(
        ..., alias="dataDocumento", description="String ISO bruta, sem parsing na Bronze"
    )
    nome_fornecedor: str = Field(..., alias="nomeFornecedor", description="Nome do fornecedor/beneficiário.")
    num_documento: str = Field(..., alias="numDocumento", description="Número do documento fiscal.")
    num_ressarcimento: str | None = Field(
        default=None, alias="numRessarcimento", description="Campo morto — 99.8% nulo"
    )
    parcela: int = Field(..., description="Número da parcela do documento.")
    tipo_despesa: str = Field(..., alias="tipoDespesa", description="Natureza da despesa.")
    tipo_documento: str = Field(..., alias="tipoDocumento", description="Tipo do documento fiscal.")
    url_documento: str | None = Field(default=None, alias="urlDocumento", description="URL do documento original.")
    valor_documento: float = Field(..., alias="valorDocumento", description="Valor do documento em reais.")
    valor_glosa: float = Field(..., alias="valorGlosa", description="Valor de glosa em reais.")
    valor_liquido: float = Field(..., alias="valorLiquido", description="Valor líquido em reais.")

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)


class CamaraSilverDespesa(BaseModel):
    """Registro de despesa limpo e tipado, pronto para resolução na Gold.

    Aplica: parsing de data ISO, classificação CNPJ/CPF (ADR-011),
    descarta campos mortos (num_ressarcimento, cod_tipo_documento).
    """

    ano: int = Field(..., description="Ano de competência da despesa.")
    mes: int = Field(..., description="Mês de competência da despesa.")
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
    tipo_documento: TipoDocumento | None = Field(default=None, description="Tipo do documento: CNPJ ou CPF.")
    cod_documento: str = Field(..., description="VARCHAR, nunca convertido para numérico")
    data_documento: date = Field(..., description="Data de emissão do documento.")
    nome_fornecedor: str = Field(..., description="Nome do fornecedor/beneficiário.")
    tipo_despesa: str = Field(..., description="Natureza da despesa.")
    tipo_documento_fiscal: str = Field(..., description="tipoDocumento original — Nota Fiscal, Recibo, etc.")
    url_documento: str | None = Field(default=None, description="URL do documento original.")
    valor_documento: Decimal = Field(..., description="Valor do documento em reais.")
    valor_glosa: Decimal = Field(..., description="Valor de glosa em reais.")
    valor_liquido: Decimal = Field(..., description="Valor líquido em reais.")

    metadata: LoadMetadata


class CamaraBronzeDeputado(BaseModel):
    """Registro bruto do snapshot de um deputado (dados mestres, Onda 2).

    Fonte: GET /deputados/{id} (dadosabertos.camara.leg.br). O detalhe retorna
    `dados` como objeto; os atributos rastreados para SCD2 (ADR-020) vivem em
    `ultimoStatus` (partido, UF, situação, legislatura). Bronze preserva o
    formato bruto achatado, sem parsing — `data_status` fica como string ISO.
    """

    id_deputado: int = Field(..., alias="id", description="Identificador do deputado na fonte.")
    nome_civil: str = Field(default="", alias="nomeCivil", description="Nome civil completo.")
    nome_eleitoral: str | None = Field(
        default=None, alias="nomeEleitoral", description="Nome eleitoral/parlamentar."
    )
    sigla_partido: str | None = Field(..., alias="siglaPartido", description="Sigla do partido na vigência.")
    sigla_uf: str | None = Field(..., alias="siglaUf", description="UF do deputado.")
    id_legislatura: int = Field(..., alias="idLegislatura", description="Legislatura vigente (bruta).")
    situacao: str | None = Field(default=None, alias="situacao", description="Situação do mandato.")
    condicao_eleitoral: str | None = Field(
        default=None, alias="condicaoEleitoral", description="Condição eleitoral (titular/suplente)."
    )
    data_status: str = Field(
        ..., alias="data", description="Data de vigência do status (ISO)"
    )
    url_foto: str | None = Field(
        default=None, alias="urlFoto", description="URL da foto do deputado na fonte."
    )

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)


class CamaraFiliacaoPartidaria(BaseModel):
    """Registro de filiação partidária extraído do webservice SOAP legado.

    Fonte: Deputados.asmx → ObterDetalhesDeputado?ideCadastro=X&numLegislatura=Y.
    Dado real (não aproximado) — ADR-043 item 3.
    """

    id_deputado: int = Field(
        ...,
        description="Identificador do deputado na fonte (ideCadastro do SOAP).",
    )
    sigla_partido: str = Field(
        ...,
        alias="siglaPartido",
        description="Sigla do partido na data de filiação.",
    )
    data_filiacao: str = Field(
        ...,
        alias="dataFiliacaoPartidoPosterior",
        description="Data da filiação partidária (timestamp exato da fonte SOAP).",
    )
    id_legislatura: int = Field(
        ...,
        alias="numLegislatura",
        description="Legislatura consultada na requisição SOAP.",
    )
    uf: str | None = Field(
        default=None,
        alias="siglaUf",
        description="UF do deputado (nunca muda, ADR-043 — confirmado: zero mudanças em 3.089 linhas).",
    )
    partido_uf_aproximado: bool = Field(
        default=False,
        description=" false = dado real via SOAP (ADR-043 item 3); true = aproximação (Senado).",
    )

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)
