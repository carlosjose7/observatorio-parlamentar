"""Contratos Bronze para presença e votação da Câmara dos Deputados.

Fontes (dadosabertos.camara.leg.br, ADR-058):
- GET /eventos — descoberta e metadados de sessão (gate "só Encerrada conta").
- Arquivo anual em lote `eventosPresencaDeputados-{ano}.json` — presença com
  semântica só-presença (cada linha = PRESENTE; sem linha de falta na fonte).
- GET /eventos/{id}/votacoes — descoberta de votações por evento.
- GET /votacoes/{id}/votos — voto nominal (`tipoVoto`, `deputado_.id`).
- GET /votacoes/{id}/orientacoes — orientação de bancada (`orientacaoVoto`).

Bronze preserva o formato bruto achatado, sem parsing — normalização e
de-para vivem no transform Silver (padrão ADR-024, ADR-058 Decisão 3–4).
Ver data_dictionary.md para a exploração empírica dos campos.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pipeline.contracts import LoadMetadata


class CamaraBronzeEvento(BaseModel):
    """Registro bruto de um evento/sessão da Câmara (metadados + situacao)."""

    id_evento: int = Field(..., alias="id", description="Identificador do evento na fonte.")
    data_inicio: str = Field(
        ..., alias="dataHoraInicio", description="Início do evento (string bruta, sem parsing na Bronze)."
    )
    data_fim: str | None = Field(
        default=None, alias="dataHoraFim", description="Fim do evento (string bruta, pode ausentar)."
    )
    descricao_tipo: str | None = Field(
        default=None, alias="descricaoTipo", description="Tipo do evento (ex: Sessão Deliberativa)."
    )
    situacao: str | None = Field(
        default=None, description="Situação do evento (ex: Encerrada, Em Andamento, Convocada)."
    )

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)


class CamaraBronzePresenca(BaseModel):
    """Linha do arquivo anual de presença — significa PRESENTE (só-presença)."""

    id_evento: int = Field(..., description="Evento da presença (chave do arquivo em lote).")
    id_deputado: int = Field(..., description="Deputado presente (chave do arquivo em lote).")
    data_hora_inicio: str | None = Field(
        default=None, description="Data/hora de início (string bruta do lote, auditoria)."
    )

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)


class CamaraBronzeVotacao(BaseModel):
    """Registro bruto de uma votação nominal (descoberta por evento)."""

    id_votacao: int = Field(..., alias="id", description="Identificador da votação na fonte.")
    id_evento: int = Field(
        ..., description="Evento de origem — injetado pela iteração do endpoint (não vem no corpo)."
    )
    descricao: str | None = Field(default=None, description="Descrição/resultado registrado da votação.")
    aprovacao: str | None = Field(default=None, description="Resultado de aprovação registrado.")
    data_registro: str | None = Field(
        default=None, alias="dataHoraRegistro", description="Registro da votação (string bruta)."
    )

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)


class CamaraBronzeVoto(BaseModel):
    """Voto nominal de um deputado em uma votação."""

    id_votacao: int = Field(
        ..., description="Votação de origem — injetada pela iteração (não vem no corpo do voto)."
    )
    id_deputado: int = Field(
        ..., description="Deputado votante — extraído de `deputado_.id` na extração (aninhado na fonte)."
    )
    tipo_voto: str | None = Field(
        default=None, alias="tipoVoto", description="Voto bruto (ex: Sim, Não, Abstenção, Artigo 17)."
    )
    data_registro_voto: str | None = Field(
        default=None, alias="dataRegistroVoto", description="Registro do voto (string bruta)."
    )

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)


class CamaraBronzeOrientacao(BaseModel):
    """Orientação de bancada em uma votação (insumo do `seguiu_partido`)."""

    id_votacao: int = Field(
        ..., description="Votação de origem — injetada pela iteração (não vem no corpo)."
    )
    sigla_bancada: str | None = Field(
        default=None, alias="siglaPartidoBloco", description="Bancada orientadora (partido, bloco, Governo...)."
    )
    orientacao_voto: str | None = Field(
        default=None, alias="orientacaoVoto", description="Orientação bruta (ex: Sim, Não, Liberado, vazio)."
    )
    cod_tipo_lideranca: str | None = Field(
        default=None, alias="codTipoLideranca", description="Tipo de liderança (P/B) — auditoria."
    )

    metadata: LoadMetadata

    model_config = ConfigDict(populate_by_name=True)
