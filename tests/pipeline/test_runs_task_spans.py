"""Spans de task + status granular (Sprint 26, Onda 1 — ADR-056 D1).

Cobre `pipeline/runs.py` (status_detalhado aditivo, PipelineTaskRun,
write_pipeline_task_run, medir_task) e a instrumentação do
`run_pipeline` (spans por fonte + status_detalhado espelhado), sem rede:
`_extrair_e_persistir` é substituído por fake.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import duckdb
import pytest
from pydantic import ValidationError

from pipeline.bronze import FONTES, _span_bronze, run_pipeline
from pipeline.runs import (
    DIRETORIO_TASK_RUNS,
    PipelineRun,
    PipelineTaskRun,
    medir_task,
    write_pipeline_task_run,
)
from pipeline.storage import LocalParquetStorage
from pipeline.watermark import WatermarkState, WatermarkStore


def _run_base(**extras):
    base = {
        "run_id": uuid.uuid4(),
        "pipeline_version": "0.1.0",
        "execution_timestamp": datetime(2026, 9, 19, 3, 0, tzinfo=UTC),
        "status": "success",
    }
    base.update(extras)
    return base


# ── status_detalhado: coluna nova aditiva, legado intocado ──────────


def test_status_detalhado_default_none_preserva_legado():
    run = PipelineRun(**_run_base())
    assert run.status == "success"
    assert run.status_detalhado is None


def test_status_detalhado_aceita_vocabulario_granular():
    for detalhado in ("warning", "running", "cancelled", "timeout"):
        run = PipelineRun(**_run_base(status="partial", status_detalhado=detalhado))
        assert run.status_detalhado == detalhado
        assert run.status == "partial"


def test_status_legado_rejeita_valor_novo():
    with pytest.raises(ValidationError):
        PipelineRun(**_run_base(status="warning"))


def test_status_detalhado_rejeita_valor_fora_do_vocabulario():
    with pytest.raises(ValidationError):
        PipelineRun(**_run_base(status_detalhado="explodiu"))


# ── PipelineTaskRun + writer ────────────────────────────────────────


def test_task_run_exige_duracao_nao_negativa():
    with pytest.raises(ValidationError):
        PipelineTaskRun(
            run_id=uuid.uuid4(),
            task="bronze_camara",
            status="success",
            duration_seconds=-1.0,
            pipeline_version="0.1.0",
            execution_timestamp=datetime(2026, 9, 19, 3, 0, tzinfo=UTC),
        )


def test_write_task_run_grava_parquet_por_span(tmp_path):
    storage = LocalParquetStorage(tmp_path / "bronze")
    run_id = uuid.uuid4()
    write_pipeline_task_run(
        storage,
        PipelineTaskRun(
            run_id=run_id,
            task="bronze_camara",
            status="success",
            duration_seconds=1.25,
            pipeline_version="0.1.0",
            execution_timestamp=datetime(2026, 9, 19, 3, 0, tzinfo=UTC),
        ),
    )
    arquivo = tmp_path / "bronze" / str(DIRETORIO_TASK_RUNS) / f"{run_id}__bronze_camara.parquet"
    assert arquivo.exists()
    linha = duckdb.connect().execute(
        "select task, status, duration_seconds from read_parquet(?)", [str(arquivo)]
    ).fetchone()
    assert linha == ("bronze_camara", "success", 1.25)


def test_medir_task_success_grava_span_com_duracao(tmp_path):
    storage = LocalParquetStorage(tmp_path / "bronze")
    run_id = uuid.uuid4()
    with medir_task(
        storage,
        run_id=run_id,
        task="silver_camara",
        pipeline_version="0.1.0",
    ):
        pass
    arquivo = tmp_path / "bronze" / str(DIRETORIO_TASK_RUNS) / f"{run_id}__silver_camara.parquet"
    duracao = duckdb.connect().execute(
        "select duration_seconds from read_parquet(?)", [str(arquivo)]
    ).fetchone()[0]
    assert duracao >= 0.0


def test_medir_task_falha_grava_failed_e_relanca(tmp_path):
    storage = LocalParquetStorage(tmp_path / "bronze")
    run_id = uuid.uuid4()
    with pytest.raises(RuntimeError, match="quebrou"):
        with medir_task(
            storage, run_id=run_id, task="gold_core", pipeline_version="0.1.0"
        ):
            raise RuntimeError("quebrou")
    arquivo = tmp_path / "bronze" / str(DIRETORIO_TASK_RUNS) / f"{run_id}__gold_core.parquet"
    status = duckdb.connect().execute(
        "select status from read_parquet(?)", [str(arquivo)]
    ).fetchone()[0]
    assert status == "failed"


def test_medir_task_falha_de_escrita_nao_derruba_o_observado(tmp_path):
    class _StorageQuebrado:
        def write_file(self, *args, **kwargs):
            raise OSError("disco cheio")

    with medir_task(
        _StorageQuebrado(),
        run_id=uuid.uuid4(),
        task="analytics",
        pipeline_version="0.1.0",
    ):
        pass  # observabilidade falhou, execução segue sem exceção


# ── mapeamento fonte → span ─────────────────────────────────────────


def test_span_bronze_cobre_as_quatro_fontes():
    assert {f: _span_bronze(f) for f in FONTES} == {
        "camara": "bronze_camara",
        "senado": "bronze_senado",
        "transparencia_emendas": "bronze_cgu_emenda",
        "transparencia_cartoes": "bronze_cgu_cartao",
    }


# ── run_pipeline instrumentado (extratores fakeados, sem rede) ──────


class _StoreMemoria(WatermarkStore):
    def __init__(self):
        self.estado: dict[str, WatermarkState] = {}

    def get(self, chave: str):
        return self.estado.get(chave, WatermarkState(last_watermark=None))

    def set(self, chave: str, estado: WatermarkState) -> None:
        self.estado[chave] = estado


def _fake_extrair_ok(fonte, *args, **kwargs):
    return f"wm-{fonte}", None


def test_run_pipeline_emite_spans_e_espelha_status_detalhado(tmp_path, monkeypatch):
    import pipeline.bronze as bronze

    monkeypatch.setattr(bronze, "_extrair_e_persistir", _fake_extrair_ok)
    monkeypatch.setattr(
        bronze, "_extrair_e_persistir_parlamentares", lambda *a, **k: (None, None)
    )
    monkeypatch.setattr(
        bronze, "_extrair_e_persistir_votacao", lambda *a, **k: (None, None)
    )
    storage = LocalParquetStorage(tmp_path / "bronze")
    run = run_pipeline(storage=storage, store=_StoreMemoria(), client=None)

    assert run.status == "success"
    assert run.status_detalhado == "success"
    spans = sorted(
        p.name for p in (tmp_path / "bronze" / str(DIRETORIO_TASK_RUNS)).glob("*.parquet")
    )
    assert spans == sorted(
        f"{run.run_id}__{task}.parquet"
        for task in (
            "bronze_camara",
            "bronze_senado",
            "bronze_cgu_emenda",
            "bronze_cgu_cartao",
            "bronze_parlamentares",
            "bronze_votacao",
        )
    )


def test_run_pipeline_parcial_mantem_spans_success(tmp_path, monkeypatch):
    """Falha isolada de fonte (§5) vira `partial` no run; o span executou."""
    import pipeline.bronze as bronze

    def _fake_uma_falha(fonte, *args, **kwargs):
        if fonte == "senado":
            return None, "fonte fora do ar"
        return f"wm-{fonte}", None

    monkeypatch.setattr(bronze, "_extrair_e_persistir", _fake_uma_falha)
    monkeypatch.setattr(
        bronze, "_extrair_e_persistir_parlamentares", lambda *a, **k: (None, None)
    )
    storage = LocalParquetStorage(tmp_path / "bronze")
    run = run_pipeline(storage=storage, store=_StoreMemoria(), client=None)

    assert run.status == "partial"
    assert run.status_detalhado == "partial"
    assert run.fontes_com_erro == ["senado"]


# ── Bronze votação (Onda 1, ADR-058): isolamento fora de FONTES ──────


def _fontes_sem_votacao():
    """Cópia das fontes reais sem os endpoints do domínio votação."""
    from pipeline.config import get_sources

    fontes = get_sources().model_copy(deep=True)
    for nome in (
        "eventos",
        "votacoes_por_evento",
        "votos_por_votacao",
        "orientacoes_por_votacao",
        "presenca_arquivo_ano",
    ):
        fontes.camara.endpoints.pop(nome, None)
    return fontes


def test_votacao_sem_endpoints_degrada_sem_erro(tmp_path, monkeypatch):
    """Sem endpoints configurados (ex: fontes sintéticas): skip log-only."""
    import pipeline.bronze as bronze

    monkeypatch.setattr(bronze, "get_sources", _fontes_sem_votacao)
    storage = LocalParquetStorage(tmp_path / "bronze")
    run_meta = bronze._novo_run_meta(datetime(2026, 9, 20, 3, 0, tzinfo=UTC))

    novo, erro = bronze._extrair_e_persistir_votacao(
        None, _StoreMemoria(), storage, run_meta, None
    )
    assert (novo, erro) == (None, None)
    assert list((tmp_path / "bronze").rglob("*.parquet")) == []


def test_votacao_persiste_janela_e_avanca_watermark(tmp_path, monkeypatch):
    """Caminho feliz com extração mockada: persiste por domínio + watermark."""
    import pipeline.bronze as bronze
    from pipeline.camara.votacao_schemas import CamaraBronzeEvento
    from pipeline.contracts import ExtractResult, LoadMetadata

    meta = LoadMetadata(
        run_id=uuid.uuid4(),
        pipeline_version="teste",
        execution_timestamp=datetime(2026, 9, 20, 3, 0, tzinfo=UTC),
        source_version="",
    )
    evento = CamaraBronzeEvento.model_validate(
        {"id": 10, "dataHoraInicio": "2024-05-15T14:00", "metadata": meta.model_dump()}
    )
    janela = {
        "eventos": ExtractResult(records=[evento], new_watermark="2024-05-15"),
        "presenca": ExtractResult(),
        "votacoes": ExtractResult(),
        "votos": ExtractResult(),
        "orientacoes": ExtractResult(),
    }
    monkeypatch.setattr(
        bronze.camara_votacao_extract, "extrair_janela", lambda *a, **k: janela
    )
    storage = LocalParquetStorage(tmp_path / "bronze")
    store = _StoreMemoria()
    run_meta = bronze._novo_run_meta(datetime(2026, 9, 20, 3, 0, tzinfo=UTC))

    novo, erro = bronze._extrair_e_persistir_votacao(
        None, store, storage, run_meta, None
    )
    assert erro is None
    assert novo == "2026-09-20"
    assert store.estado[bronze.CHAVE_WATERMARK_VOTACAO].last_watermark == "2026-09-20"
    df = storage.read_dir(bronze.DIRETORIOS_VOTACAO["eventos"])
    assert len(df) == 1
    assert int(df["id_evento"].iloc[0]) == 10
