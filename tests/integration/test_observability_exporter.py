"""Integração do exporter Prometheus (Sprint 22, ADR-051, Onda 5).

Prova o contrato da Fase 0: o exporter responde HTTP 200 com as séries
do contrato e nenhum `run_id` como label (cardinalidade, ADR-051 §5).
Não toca no DuckDB real: as fronteiras de leitura (`api.repo`), o
acesso ao fato e a versão são substituídos por fakes via monkeypatch.
"""

from __future__ import annotations

import socket
import urllib.request
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from prometheus_client import start_http_server

import observability.pipeline_exporter as exporter
from api.repo import GoldIndisponivel

_RUN_IDS = ("run-contrato-aaa", "run-contrato-bbb")

_SERIES_EXPORTER = (
    "pipeline_last_run_status",
    "pipeline_last_run_timestamp_seconds",
    "pipeline_runs_total",
    "pipeline_watermark_lag_hours",
    "dq_total",
    "dq_validos",
    "dq_quarentena",
    "dq_dedup",
    "dq_nulos_ratio",
    "dq_regras_violadas",
    "gold_fact_despesa_total",
    "gold_file_bytes",
    "gold_pipeline_version_info",
)


def _execucoes(*, limite):
    return SimpleNamespace(
        itens=[
            SimpleNamespace(
                run_id=_RUN_IDS[0],
                status="success",
                execution_timestamp="2026-09-14T03:00:00",
                watermark_camara="2026-09-13",
                watermark_senado="2026-09",
                watermark_cgu_emenda="2026",
                watermark_cgu_cartao=None,
            ),
            SimpleNamespace(
                run_id=_RUN_IDS[1],
                status="failed",
                execution_timestamp="2026-09-13T03:00:00",
                watermark_camara="2026-09-12",
                watermark_senado="2026-08",
                watermark_cgu_emenda="2025",
                watermark_cgu_cartao=None,
            ),
        ]
    )


def _qualidade(*, tabela, pagina, limite):
    return SimpleNamespace(
        itens=[
            SimpleNamespace(
                run_id=_RUN_IDS[0],
                tabela="fact_despesa",
                total_registros=100,
                registros_validos=95,
                registros_quarentena=3,
                registros_deduplicados=2,
                regras_violadas=["fk_orfa"],
                percentual_nulos_criticos=0.01,
                execution_timestamp="2026-09-14T03:00:00",
            ),
        ]
    )


class _ConexaoFake:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return [10.0]


class _DuckDBFake:
    def connect(self, *args, **kwargs):
        assert kwargs.get("read_only") is True
        return _ConexaoFake()


@pytest.fixture()
def _gold_fake(monkeypatch, tmp_path):
    """Fronteiras de leitura do exporter apontadas para fakes determinísticos."""
    arquivo = tmp_path / "observatorio.duckdb"
    arquivo.write_bytes(b"\x00" * 1024)
    monkeypatch.setattr(exporter, "listar_execucoes", _execucoes)
    monkeypatch.setattr(exporter, "listar_relatorio_qualidade", _qualidade)
    monkeypatch.setattr(exporter, "caminho_do_gold", lambda: arquivo)
    monkeypatch.setattr(exporter, "duckdb", _DuckDBFake())
    monkeypatch.setattr(exporter, "get_pipeline_version", lambda: "0.1.0")


def _corpo_metrics():
    """Sobe o HTTP do exporter em porta efêmera e devolve (status, corpo)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    start_http_server(porta, addr="127.0.0.1")
    with urllib.request.urlopen(f"http://127.0.0.1:{porta}/metrics") as resp:
        return resp.status, resp.read().decode("utf-8")


def test_exporter_responde_200_com_series_do_contrato(_gold_fake):
    exporter.coletar()
    status, corpo = _corpo_metrics()
    assert status == 200
    for serie in _SERIES_EXPORTER:
        assert serie in corpo, f"série ausente: {serie}"


def test_exporter_sem_run_id_como_label(_gold_fake):
    exporter.coletar()
    _, corpo = _corpo_metrics()
    assert "run_id" not in corpo
    for run_id in _RUN_IDS:
        assert run_id not in corpo


def test_exporter_gold_indisponivel_nao_quebra_o_http(monkeypatch):
    def _falhar(**kwargs):
        raise GoldIndisponivel("Gold ausente")

    monkeypatch.setattr(exporter, "listar_execucoes", _falhar)
    exporter.coletar()  # não deve lançar
    status, _ = _corpo_metrics()
    assert status == 200


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        # Formatos reais das fontes (Sprint 25, ADR-055 — regressão do
        # ponto cego: %m/%Y de camara/cartão nunca foi exercitado).
        ("09/2026", datetime(2026, 9, 1, tzinfo=UTC)),
        ("06/2014", datetime(2014, 6, 1, tzinfo=UTC)),
        ("2026", datetime(2026, 1, 1, tzinfo=UTC)),
        ("2026-09-15", datetime(2026, 9, 15, tzinfo=UTC)),
        ("15/09/2026", datetime(2026, 9, 15, tzinfo=UTC)),
        ("Sem informação", None),
        ("n/a", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_watermark_formatos_reais(bruto, esperado):
    assert exporter._parse_watermark(bruto) == esperado
