"""Casos de borda das Ondas 2/3/4/7 (Sprint 26, Onda 8 — ADR-056).

Funções puras do exporter (`observability/pipeline_exporter.py`): 0 runs,
100% sucesso, falha sem recuperação, janela parcial, fronteiras de classe
e de régua. Sem HTTP, sem Gold — só os helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import observability.pipeline_exporter as exporter


def _run(status: str, ts: str, detalhado=None):
    return SimpleNamespace(
        status=status, status_detalhado=detalhado, execution_timestamp=ts
    )


def _dq(tabela: str, total: int, quarentena: int):
    return SimpleNamespace(
        tabela=tabela,
        total_registros=total,
        registros_validos=total - quarentena,
        registros_quarentena=quarentena,
        registros_deduplicados=0,
        regras_violadas=[],
        percentual_nulos_criticos=0.0,
    )


def _span(task: str, duracao, ts="2026-09-14T03:00:00"):
    return SimpleNamespace(
        task_run_id=f"r__{task}", run_id="r", task=task, status="success",
        duration_seconds=duracao, pipeline_version="0.1.0",
        execution_timestamp=ts,
    )


# ── MTTR ────────────────────────────────────────────────────────


def test_mttr_sem_runs_omitido():
    assert exporter.calcular_mttr([]) is None


def test_mttr_100_sucesso_omitido():
    itens = [_run("success", f"2026-09-{d:02d}T03:00:00") for d in (10, 11, 12)]
    assert exporter.calcular_mttr(itens) is None


def test_mttr_falha_sem_recuperacao_omitida():
    itens = [
        _run("failed", "2026-09-12T03:00:00"),
        _run("success", "2026-09-11T03:00:00"),  # anterior à falha: não conta
    ]
    assert exporter.calcular_mttr(itens) is None


def test_mttr_ignora_partial_nos_dois_papeis():
    itens = [
        _run("success", "2026-09-13T03:00:00"),
        _run("partial", "2026-09-12T12:00:00"),  # nem falha nem recupera
        _run("failed", "2026-09-12T03:00:00"),
    ]
    assert exporter.calcular_mttr(itens) == 86400.0


def test_mttr_ts_ilegivel_ignorado():
    itens = [
        _run("success", "2026-09-13T03:00:00"),
        _run("failed", "Sem informação"),
        _run("failed", "2026-09-12T03:00:00"),
    ]
    assert exporter.calcular_mttr(itens) == 86400.0


# ── MTBF ────────────────────────────────────────────────────────


def test_mtbf_zero_ou_uma_falha_omitido():
    assert exporter.calcular_mtbf([]) is None
    assert exporter.calcular_mtbf([_run("failed", "2026-09-12T03:00:00")]) is None
    assert exporter.calcular_mtbf(
        [_run("success", "2026-09-12T03:00:00")]
    ) is None


def test_mtbf_duas_falhas_intervalo():
    itens = [
        _run("failed", "2026-09-12T03:00:00"),
        _run("failed", "2026-09-10T03:00:00"),
    ]
    assert exporter.calcular_mtbf(itens) == 172800.0


# ── Cobertura ───────────────────────────────────────────────────


def test_cobertura_sem_runs_planeja_sete_falta_sete():
    agora = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    assert exporter.calcular_cobertura([], agora=agora) == (7.0, 7.0, 0.0)


def test_cobertura_janela_parcial_e_ts_ilegivel():
    agora = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    itens = [
        _run("success", "2026-09-14T03:00:00"),
        _run("success", "2026-09-01T03:00:00"),  # fora da janela
        _run("success", "Sem informação"),  # ignorado
    ]
    planejadas, faltas, ratio = exporter.calcular_cobertura(itens, agora=agora)
    assert (planejadas, faltas) == (7.0, 6.0)
    assert ratio == pytest.approx(1 / 7)


# ── Taxa de sucesso ─────────────────────────────────────────────


def test_sucesso_sem_runs_omitido():
    assert exporter.calcular_taxa_sucesso([]) is None


def test_sucesso_tudo_partial_meio_credito():
    itens = [_run("partial", "2026-09-12T03:00:00")]
    assert exporter.calcular_taxa_sucesso(itens) == 50.0


# ── Qualidade ───────────────────────────────────────────────────


def test_qualidade_sem_dq_omitida():
    assert exporter.calcular_qualidade([], crit_outras=0.05, crit_cartao=0.25) is None


def test_qualidade_normaliza_cada_grupo_pelo_proprio_critical():
    # Outras a 50% do critical (0.025/0.05=0.5), cartão a 20% do próprio
    # critical (0.05/0.25=0.2): o pior vence → (1−0.5)·100 = 50.
    dq = [_dq("silver_despesa", 1000, 25), _dq("silver_cartao", 1000, 50)]
    valor = exporter.calcular_qualidade(dq, crit_outras=0.05, crit_cartao=0.25)
    assert valor == pytest.approx(50.0)


def test_qualidade_clampa_em_zero_quando_estoura_critical():
    dq = [_dq("silver_despesa", 100, 30)]  # 30% >> 5%: 1−6 → clamp 0
    assert exporter.calcular_qualidade(dq, crit_outras=0.05, crit_cartao=0.25) == 0.0


def test_qualidade_ignora_tabela_sem_total():
    dq = [_dq("silver_despesa", 0, 0)]
    assert exporter.calcular_qualidade(dq, crit_outras=0.05, crit_cartao=0.25) is None


# ── Performance ─────────────────────────────────────────────────


def test_performance_sem_spans_omitida():
    assert exporter.calcular_performance([]) is None


def test_performance_amostra_unica_nota_maxima():
    assert exporter.calcular_performance([_span("bronze_camara", 10.0)]) == 100.0


def test_performance_degradacao_derruba_e_melhora_clampa():
    # Mediana [10, 10, 30]=10, última 30 → 100·10/30; melhora 5 → clamp 100.
    spans = [
        _span("t", 30.0, "2026-09-14T03:00:00"),
        _span("t", 10.0, "2026-09-13T03:00:00"),
        _span("t", 10.0, "2026-09-12T03:00:00"),
    ]
    assert exporter.calcular_performance(spans) == pytest.approx(100 / 3)
    spans[0] = _span("t", 5.0, "2026-09-14T03:00:00")
    assert exporter.calcular_performance(spans) == 100.0


def test_performance_ignora_duracao_nula():
    assert exporter.calcular_performance([_span("t", None)]) is None


# ── Health ──────────────────────────────────────────────────────


def test_health_sem_runs_omitido_nunca_zero():
    agora = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    assert exporter.calcular_health([], [], [], agora=agora,
                                    crit_outras=0.05, crit_cartao=0.25) is None


def test_health_sem_dq_ou_spans_omitido():
    agora = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    runs = [_run("success", "2026-09-14T03:00:00")]
    assert exporter.calcular_health(runs, [], [_span("t", 1.0)], agora=agora,
                                    crit_outras=0.05, crit_cartao=0.25) is None
    assert exporter.calcular_health(runs, [_dq("a", 10, 0)], [], agora=agora,
                                    crit_outras=0.05, crit_cartao=0.25) is None


@pytest.mark.parametrize(
    ("valor", "classe"),
    [(100.0, "saudavel"), (90.0, "saudavel"), (89.99, "atencao"),
     (70.0, "atencao"), (69.99, "alerta"), (50.0, "alerta"),
     (49.99, "critico"), (0.0, "critico")],
)
def test_classe_health_fronteiras(valor, classe):
    assert exporter.classe_health(valor) == classe


# ── Score DQ ────────────────────────────────────────────────────


def test_score_dq_vazio_zeros():
    assert exporter.classificar_dq(
        [], warn_outras=0.02, crit_outras=0.05, warn_cartao=0.20, crit_cartao=0.25
    ) == {"pass": 0, "warn": 0, "fail": 0}


def test_score_dq_fronteiras_estritas():
    # Na régua exata (==) NÃO sobe de classe: só `>` promove.
    dq = [
        _dq("a", 1000, 20),  # 2% == warn → pass
        _dq("b", 1000, 50),  # 5% == critical → warn
        _dq("c", 1000, 51),  # >5% → fail
        _dq("silver_cartao", 1000, 200),  # 20% == warn cartão → pass
        _dq("silver_cartao", 1000, 200),  # duplicada: primeira vence (pass)
    ]
    assert exporter.classificar_dq(
        dq, warn_outras=0.02, crit_outras=0.05, warn_cartao=0.20, crit_cartao=0.25
    ) == {"pass": 2, "warn": 1, "fail": 1}


def test_score_dq_cartao_fail_acima_de_25():
    dq = [_dq("silver_cartao", 1000, 251)]
    resultado = exporter.classificar_dq(
        dq, warn_outras=0.02, crit_outras=0.05, warn_cartao=0.20, crit_cartao=0.25
    )
    assert resultado["fail"] == 1
