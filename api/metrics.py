"""api/metrics.py — séries Prometheus da API (Sprint 22, ADR-051, Onda 3).

Quatro séries, nomes exatos do contrato (ADR-051 §5):
- `http_requests_total{rota,status}` — contador por template de rota
  (ex.: `/agent/parlamentar/{id}`, nunca o path com ID — cardinalidade
  limitada) e código de status.
- `http_latency_seconds` — histograma global de latência (base do SLO
  `api_p95_ms=500` de `config/observability.yaml`).
- `gold_indisponivel_total` — contador incrementado no único choke
  point (`api/repo.py:_tratar_erro_gold`); todo 503 de Gold passa ali.
- `gold_tabelas_ok` — 1 após o smoke check das 12 tabelas
  (`_verificar_tabelas_gold`), 0 quando ele falha.

Sem autenticação interna: `/metrics` é servido na porta da API dentro
da rede do compose — o Nginx nunca publica essa porta (Onda 4 mantém o
bind interno; Prometheus scraepa via rede `observatorio-net`).

Nota de processo: NÃO importar `observability.pipeline_exporter` no
mesmo processo da API (e vice-versa) — ambos registram séries no
registry default do `prometheus_client` e o segundo import falharia
com série duplicada. São processos separados (API ↔ exporter).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "Requisições HTTP servidas pela API, por rota e status.",
    ["rota", "status"],
)
http_latency_seconds = Histogram(
    "http_latency_seconds",
    "Latência das respostas HTTP da API, em segundos.",
)
gold_indisponivel_total = Counter(
    "gold_indisponivel_total",
    "Falhas de acesso à camada Gold (degradadas como 503).",
)
gold_tabelas_ok = Gauge(
    "gold_tabelas_ok",
    "Smoke check das tabelas Gold (1 = 12 tabelas presentes).",
)
