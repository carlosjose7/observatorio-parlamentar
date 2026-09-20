# tests/pipeline/test_votacao_extract.py
"""Extração Bronze do domínio votação da Câmara (Sprint 27 — Onda 1, ADR-058).

Cobre, com HTTP mockado (`httpx.MockTransport`) e config real
(`get_sources().camara` — valida que `sources.yaml` declara os endpoints):
descoberta de eventos por intervalo, arquivo anual de presença (chaves
flexíveis), cascata votação → votos/orientações e o achatamento de
`deputado_.id`. Sem rede, sem segredo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from pipeline.camara import votacao_extract as vx
from pipeline.config import get_sources

EVENTO_ENCERRADO = {
    "id": 10,
    "dataHoraInicio": "2024-05-15T14:00",
    "dataHoraFim": "2024-05-15T18:00",
    "descricaoTipo": "Sessão Deliberativa",
    "situacao": "Encerrada",
}
EVENTO_ANDAMENTO = {
    "id": 11,
    "dataHoraInicio": "2024-05-16T14:00",
    "descricaoTipo": "Sessão Deliberativa",
    "situacao": "Em Andamento",
}
VOTACAO = {"id": 100, "descricao": "PL 1/2024", "aprovacao": "Aprovada"}
VOTO_SIM = {
    "tipoVoto": "Sim",
    "dataRegistroVoto": "2024-05-15T15:00",
    "deputado_": {"id": 1, "nome": "JOSE SILVA"},
}
VOTO_NAO = {
    "tipoVoto": "Não",
    "dataRegistroVoto": "2024-05-15T15:01",
    "deputado_": {"id": 2, "nome": "PEDRO ALVES"},
}
VOTO_SEM_DEPUTADO = {"tipoVoto": "Sim"}
ORIENTACAO = {"siglaPartidoBloco": "PARTIDO B", "orientacaoVoto": "Sim", "codTipoLideranca": "P"}
PRESENCA_LINHA = {"idEvento": 10, "idDeputado": 1, "dataHoraInicio": "2024-05-15T14:00"}


def _meta():
    from pipeline.contracts import LoadMetadata

    return LoadMetadata(
        run_id=uuid4(),
        pipeline_version="teste",
        execution_timestamp=datetime.now(UTC),
        source_version="",
    )


def _cliente():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        pagina = int(params.get("pagina", 1))
        if path.endswith("/eventos"):
            return httpx.Response(
                200, json={"dados": [EVENTO_ENCERRADO, EVENTO_ANDAMENTO] if pagina == 1 else []}
            )
        if path.endswith("/eventos/10/votacoes"):
            return httpx.Response(200, json={"dados": [VOTACAO] if pagina == 1 else []})
        if path.endswith("/votacoes/100/votos"):
            return httpx.Response(
                200,
                json={"dados": [VOTO_SIM, VOTO_NAO, VOTO_SEM_DEPUTADO] if pagina == 1 else []},
            )
        if path.endswith("/votacoes/100/orientacoes"):
            return httpx.Response(200, json={"dados": [ORIENTACAO] if pagina == 1 else []})
        if path.endswith(".json"):
            return httpx.Response(200, json={"dados": [PRESENCA_LINHA]})
        return httpx.Response(404, json={"erro": "rota não encontrada"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def cfg():
    return get_sources().camara


def test_eventos_por_intervalo_com_watermark(cfg):
    client = _cliente()
    res = vx.extract_eventos(cfg, client, _meta(), None, "2024-05-15", "2024-05-16")
    assert [r.id_evento for r in res.records] == [10, 11]
    assert res.records[0].situacao == "Encerrada"
    assert res.new_watermark == "2024-05-16"


def test_votos_achatam_deputado_e_pulam_sem_id(cfg):
    client = _cliente()
    res = vx.extract_votos(cfg, client, 100, _meta(), None)
    assert [(v.id_deputado, v.tipo_voto) for v in res.records] == [(1, "Sim"), (2, "Não")]


def test_orientacoes(cfg):
    client = _cliente()
    res = vx.extract_orientacoes(cfg, client, 100, _meta(), None)
    assert len(res.records) == 1
    assert res.records[0].sigla_bancada == "PARTIDO B"


def test_presenca_lote_chaves_flexiveis(cfg):
    client = _cliente()
    res = vx.extract_presenca_ano(cfg, client, 2024, _meta(), None)
    assert [(p.id_evento, p.id_deputado) for p in res.records] == [(10, 1)]
    assert res.source_version == "2024"


def test_extrair_janela_agrega_cascata(cfg):
    client = _cliente()
    res = vx.extract_votacoes_evento(cfg, client, 10, _meta(), None)
    assert [v.id_votacao for v in res.records] == [100]
    assert res.records[0].id_evento == 10


def test_extrair_janela_isola_evento_sem_votacao(cfg):
    client = _cliente()
    janela = vx.extrair_janela(
        cfg, client, _meta(), None, "2024-05-15", "2024-05-16", anos_presenca=[2024]
    )
    assert [e.id_evento for e in janela["eventos"].records] == [10, 11]
    # Evento 11 retorna 404 em /votacoes → isolado com log, sem derrubar.
    assert [v.id_votacao for v in janela["votacoes"].records] == [100]
    assert len(janela["votos"].records) == 2
    assert len(janela["orientacoes"].records) == 1
    assert len(janela["presenca"].records) == 1
