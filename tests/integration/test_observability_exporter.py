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
    "pipeline_task_duration_seconds",
    "pipeline_task_last_run_status",
    "pipeline_mttr_seconds",
    "pipeline_mtbf_seconds",
    "pipeline_execucoes_planejadas_total",
    "pipeline_execucoes_nao_realizadas_total",
    "pipeline_cobertura_ratio",
    "pipeline_health_index",
    "pipeline_health_status",
    "pipeline_dq_score_pass_total",
    "pipeline_dq_score_warn_total",
    "pipeline_dq_score_fail_total",
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
    # Mais recentes primeiro. Histórico com 2 falhas recuperadas em 24h
    # cada (MTTR=86400s) separadas por 48h (MTBF=172800s); a mais recente
    # é `partial`+`warning` (status efetivo = detalhado).
    return SimpleNamespace(
        itens=[
            SimpleNamespace(
                run_id=_RUN_IDS[0],
                status="partial",
                # Granular (ADR-056 D1): o efetivo é o detalhado, não o legado.
                status_detalhado="warning",
                execution_timestamp="2026-09-14T03:00:00",
                watermark_camara="2026-09-13",
                watermark_senado="2026-09",
                watermark_cgu_emenda="2026",
                watermark_cgu_cartao=None,
            ),
            SimpleNamespace(
                run_id="run-contrato-ccc",
                status="success",
                status_detalhado="success",
                execution_timestamp="2026-09-13T03:00:00",
                watermark_camara="2026-09-12",
                watermark_senado="2026-09",
                watermark_cgu_emenda="2026",
                watermark_cgu_cartao=None,
            ),
            SimpleNamespace(
                run_id=_RUN_IDS[1],
                status="failed",
                # Execução pré-Sprint 26: sem granular, vale o legado.
                status_detalhado=None,
                execution_timestamp="2026-09-12T03:00:00",
                watermark_camara="2026-09-11",
                watermark_senado="2026-08",
                watermark_cgu_emenda="2025",
                watermark_cgu_cartao=None,
            ),
            SimpleNamespace(
                run_id="run-contrato-ddd",
                status="success",
                status_detalhado=None,
                execution_timestamp="2026-09-11T03:00:00",
                watermark_camara="2026-09-10",
                watermark_senado="2026-08",
                watermark_cgu_emenda="2025",
                watermark_cgu_cartao=None,
            ),
            SimpleNamespace(
                run_id="run-contrato-eee",
                status="failed",
                status_detalhado=None,
                execution_timestamp="2026-09-10T03:00:00",
                watermark_camara="2026-09-09",
                watermark_senado="2026-08",
                watermark_cgu_emenda="2025",
                watermark_cgu_cartao=None,
            ),
        ]
    )


def _task_runs(*, limite):
    return SimpleNamespace(
        itens=[
            SimpleNamespace(
                task_run_id=f"{_RUN_IDS[0]}__bronze_camara",
                run_id=_RUN_IDS[0],
                task="bronze_camara",
                status="success",
                duration_seconds=12.5,
                pipeline_version="0.1.0",
                execution_timestamp="2026-09-14T03:00:00",
            ),
            SimpleNamespace(
                task_run_id=f"{_RUN_IDS[0]}__silver_camara",
                run_id=_RUN_IDS[0],
                task="silver_camara",
                status="failed",
                duration_seconds=5.25,
                pipeline_version="0.1.0",
                execution_timestamp="2026-09-14T03:00:00",
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
    monkeypatch.setattr(exporter, "listar_task_runs", _task_runs)
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


def test_exporter_mttr_mtbf(_gold_fake):
    """MTTR=24h (2 recuperações) e MTBF=48h sobre o histórico fake (Onda 2)."""
    from prometheus_client import REGISTRY

    exporter.coletar()
    assert REGISTRY.get_sample_value("pipeline_mttr_seconds", {}) == 86400.0
    assert REGISTRY.get_sample_value("pipeline_mtbf_seconds", {}) == 172800.0


def test_calcular_health_composicao_40_30_20_10():
    """Health = 40% cobertura + 30% sucesso + 20% qualidade + 10% performance.

    Com `agora` fixo em 2026-09-14T12:00Z: 5/7 dias cobertos (71.43),
    sucesso (0.5+1+0+1+0)/5 = 50, qualidade 1−0.03/0.05 = 40 (só
    `fact_despesa`, sem cartão), performance 100 (spans únicos) →
    61.57 = classe `alerta`.
    """
    agora = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    valor, classe = exporter.calcular_health(
        _execucoes(limite=100).itens,
        _qualidade(tabela=None, pagina=1, limite=100).itens,
        _task_runs(limite=100).itens,
        agora=agora,
        crit_outras=0.05,
        crit_cartao=0.25,
    )
    assert valor == pytest.approx(61.571, abs=0.01)
    assert classe == "alerta"


def test_exporter_dq_score_agregado(_gold_fake):
    """`fact_despesa` com 3% em quarentena = WARN (entre 2% e 5%, Onda 7)."""
    from prometheus_client import REGISTRY

    exporter.coletar()
    assert REGISTRY.get_sample_value("pipeline_dq_score_pass_total", {}) == 0.0
    assert REGISTRY.get_sample_value("pipeline_dq_score_warn_total", {}) == 1.0
    assert REGISTRY.get_sample_value("pipeline_dq_score_fail_total", {}) == 0.0


def test_exporter_status_efetivo_prefere_detalhado(_gold_fake):
    """Última execução `partial`+`warning`: o 1.0 vai para `warning` (ADR-056 D1)."""
    from prometheus_client import REGISTRY

    exporter.coletar()
    vigente = REGISTRY.get_sample_value(
        "pipeline_last_run_status", {"status": "warning"}
    )
    legado = REGISTRY.get_sample_value(
        "pipeline_last_run_status", {"status": "partial"}
    )
    assert vigente == 1.0
    assert legado == 0.0


def test_exporter_tasks_duracao_e_status(_gold_fake):
    """Spans viram `pipeline_task_duration_seconds` + `task_last_run_status`."""
    from prometheus_client import REGISTRY

    exporter.coletar()
    assert REGISTRY.get_sample_value(
        "pipeline_task_duration_seconds", {"task": "bronze_camara"}
    ) == 12.5
    assert REGISTRY.get_sample_value(
        "pipeline_task_last_run_status",
        {"task": "silver_camara", "status": "failed"},
    ) == 1.0
    assert REGISTRY.get_sample_value(
        "pipeline_task_last_run_status",
        {"task": "silver_camara", "status": "success"},
    ) == 0.0


def test_exporter_sem_tabela_task_preserva_demais_series(monkeypatch, tmp_path):
    """Gold pré-Sprint 26 (sem `pipeline_task_runs`): demais séries publicadas.

    O bloco de tasks é defensivo — `GoldIndisponivel` ali vira log, nunca
    derruba a coleta inteira.
    """
    arquivo = tmp_path / "observatorio.duckdb"
    arquivo.write_bytes(b"\x00" * 1024)
    monkeypatch.setattr(exporter, "listar_execucoes", _execucoes)
    monkeypatch.setattr(exporter, "listar_relatorio_qualidade", _qualidade)

    def _sem_tabela(**kwargs):
        raise GoldIndisponivel("pipeline_task_runs ausente (Gold pré-Sprint 26)")

    monkeypatch.setattr(exporter, "listar_task_runs", _sem_tabela)
    monkeypatch.setattr(exporter, "caminho_do_gold", lambda: arquivo)
    monkeypatch.setattr(exporter, "duckdb", _DuckDBFake())
    monkeypatch.setattr(exporter, "get_pipeline_version", lambda: "0.1.0")

    exporter.coletar()  # não deve lançar
    status, corpo = _corpo_metrics()
    assert status == 200
    assert "pipeline_last_run_status" in corpo
    assert "pipeline_runs_total" in corpo


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
