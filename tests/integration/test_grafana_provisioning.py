"""Provisioning Grafana + alertas (Sprint 23, ADR-053, Onda 4).

Prova o contrato da Fase 2 sem subir containers: datasource aponta para
o Prometheus interno, dashboard tem os 4 painéis com réguas dos SLOs de
`config/observability.yaml`, alertas referenciam só séries Fase 0+1
(ADR-051 §5) e o compose expõe Grafana só em 127.0.0.1:3000.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_PROV = _REPO / "infra" / "observability" / "grafana" / "provisioning"

_SERIES_CONTRATO = {
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
    "http_requests_total",
    "http_latency_seconds",
    "gold_indisponivel_total",
    "gold_tabelas_ok",
}

_METRIC_RE = re.compile(r"[a-z_][a-z0-9_]*")


def _metricas(expr: str) -> set[str]:
    sem_strings = re.sub(r'"[^"]*"', "", expr)
    sem_ranges = re.sub(r"\[[^\]]*\]", "", sem_strings)
    tokens = set(_METRIC_RE.findall(sem_ranges))
    norm = {t[:-7] if t.endswith("_bucket") else t for t in tokens}
    return {
        t
        for t in norm
        if t not in {"sum", "rate", "max", "time", "increase", "histogram_quantile"}
        and len(t) > 1
    }


def test_datasource_aponta_prometheus_interno():
    ds = yaml.safe_load(
        (_PROV / "datasources" / "prometheus.yml").read_text(encoding="utf-8")
    )["datasources"][0]
    assert ds["url"] == "http://prometheus:9090"
    assert ds["isDefault"] is True
    assert ds["editable"] is False


def test_dashboard_tem_4_paineis_com_regras_dos_slos():
    slos = yaml.safe_load(
        (_REPO / "config" / "observability.yaml").read_text(encoding="utf-8")
    )["observability"]["slos"]
    dash = json.loads(
        (_PROV / "dashboards" / "observatorio.json").read_text(encoding="utf-8")
    )
    assert len(dash["panels"]) == 4
    exprs = [
        t["expr"] for p in dash["panels"] for t in p.get("targets", [])
    ]
    assert exprs, "dashboard sem targets"
    for expr in exprs:
        desconhecidas = _metricas(expr) - _SERIES_CONTRATO - {"status", "rota", "tabela", "fonte", "regra", "versao", "bucket"}
        assert not desconhecidas, f"série fora do contrato: {desconhecidas}"
    texto = json.dumps(dash)
    assert str(slos["api_p95_ms"] / 1000) in texto  # 0.5s
    assert str(slos["freshness_horas"]) in texto  # 24
    assert str(slos["freshness_alerta_horas"]) in texto  # 26


def test_alertas_somente_series_do_contrato():
    alerts = yaml.safe_load(
        (_REPO / "infra" / "observability" / "alerts.yml").read_text(
            encoding="utf-8"
        )
    )
    rules = alerts["groups"][0]["rules"]
    assert len(rules) >= 8
    nomes = set()
    for rule in rules:
        nomes.add(rule["alert"])
        assert rule["labels"]["severity"] in {"warn", "critical"}
        desconhecidas = (
            _metricas(rule["expr"]) - _SERIES_CONTRATO
            - {"tabela", "fonte", "status", "regra", "rota", "versao"}
        )
        assert not desconhecidas, f"{rule['alert']}: {desconhecidas}"
    # ADR-054: régua própria do cartão (20%/25%), demais tabelas no 2%/5%.
    assert {"QuarentenaCartaoWarn", "QuarentenaCartaoCritical"} <= nomes


def test_compose_grafana_somente_localhost_sem_nginx():
    compose = (_REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:3000:3000"' in compose
    assert "grafana/grafana:" in compose
    assert "GF_SECURITY_ADMIN_PASSWORD" in compose
    assert "./infra/observability/alerts.yml" in compose
    doc = yaml.safe_load(compose)
    nginx = doc["services"].get("nginx", {})
    nginx_txt = json.dumps(nginx.get("ports", []))
    assert "3000" not in nginx_txt
