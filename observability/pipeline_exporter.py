"""observability/pipeline_exporter.py — exporter Prometheus do pipeline (ADR-051).

O pipeline é batch efêmero (`@daily`): o Prometheus não consegue
scrapeá-lo diretamente, e o Pushgateway foi descartado (ADR-051 §2).
Este processo longa-vida coleta a cada `intervalo_segundos`
(`config/observability.yaml:exporter`, default 60s) e serve as métricas
para scrape.

Fronteira de leitura (ADR-026): DuckDB Gold SEMPRE em `read_only=True`
— nunca escreve. Reaproveita `api/repo.py:listar_execucoes`
(`pipeline_runs`) e `listar_relatorio_qualidade`
(`data_quality_report`) em vez de reescrever SQL; só o agregado do fato
(`sum(valor_liquido)`) e o tamanho do arquivo usam acesso próprio,
ainda assim read-only via `caminho_do_gold()`.

Cardinalidade: `run_id` NUNCA aparece como label de série — só
`tabela`, `fonte`, `status`, `regra` (e `versao`, de baixíssima
cardinalidade, no info de build).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import duckdb
import structlog
from prometheus_client import Gauge, Info, start_http_server

from api.repo import (
    GoldIndisponivel,
    caminho_do_gold,
    listar_execucoes,
    listar_relatorio_qualidade,
)
from pipeline.config import get_observability, get_pipeline_version

logger = structlog.get_logger()

# Execuções são buscadas mais recentes primeiro; 1000 cobre ~3 anos de
# runs diárias para o total por status sem reescrever SQL de contagem.
_JANELA_EXECUCOES = 1000
_JANELA_QUALIDADE = 1000

# (label fonte, atributo watermark em ExecucaoPipeline) — as 4 fontes.
_FONTES = (
    ("camara", "watermark_camara"),
    ("senado", "watermark_senado"),
    ("cgu_emenda", "watermark_cgu_emenda"),
    ("cgu_cartao", "watermark_cgu_cartao"),
)

# Status conhecidos do controle (pipeline/runs.py); o status da última
# execução é sempre incluído mesmo que seja um valor novo.
_STATUS_CONHECIDOS = ("success", "failed", "partial")

_FORMATOS_WATERMARK = ("%Y-%m-%d", "%Y-%m", "%Y", "%d/%m/%Y", "%m/%Y")

g_last_run_status = Gauge(
    "pipeline_last_run_status",
    "Status da última execução (1 no status vigente, 0 nos demais).",
    ["status"],
)
g_last_run_timestamp = Gauge(
    "pipeline_last_run_timestamp_seconds",
    "Timestamp Unix da última execução do pipeline.",
)
g_runs_total = Gauge(
    "pipeline_runs_total",
    "Total de execuções observadas por status (snapshot da janela).",
    ["status"],
)
g_watermark_lag = Gauge(
    "pipeline_watermark_lag_hours",
    "Defasagem do watermark por fonte, em horas (agora - watermark).",
    ["fonte"],
)
g_dq_total = Gauge("dq_total", "Total de registros avaliados no DQ Report.", ["tabela"])
g_dq_validos = Gauge("dq_validos", "Registros válidos no DQ Report.", ["tabela"])
g_dq_quarentena = Gauge("dq_quarentena", "Registros em quarentena no DQ Report.", ["tabela"])
g_dq_dedup = Gauge("dq_dedup", "Registros deduplicados no DQ Report.", ["tabela"])
g_dq_nulos = Gauge(
    "dq_nulos_ratio",
    "Fração de nulos críticos no DQ Report (0-1).",
    ["tabela"],
)
g_dq_regras = Gauge(
    "dq_regras_violadas",
    "Regra violada presente no DQ Report (1 = violada).",
    ["tabela", "regra"],
)
g_fact_total = Gauge(
    "gold_fact_despesa_total",
    "Soma de valor_liquido em gold.fact_despesa.",
)
g_file_bytes = Gauge("gold_file_bytes", "Tamanho do arquivo DuckDB Gold, em bytes.")
i_build = Info(
    "gold_pipeline_version",
    "Versão do pipeline que gerou o Gold (fonte única: pyproject.toml).",
)


def _parse_ts(valor: str | None) -> float | None:
    """`execution_timestamp` (ISO) → epoch; None se ausente/inválido."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _parse_watermark(valor: str | None) -> datetime | None:
    """Watermark (data, ano ou mês) → datetime UTC; None se ilegível."""
    if not valor:
        return None
    texto = valor.strip()
    try:
        dt = datetime.fromisoformat(texto)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    for formato in _FORMATOS_WATERMARK:
        try:
            return datetime.strptime(texto, formato).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def coletar(agora: datetime | None = None) -> None:
    """Um ciclo de coleta: lê o Gold (read-only) e atualiza as séries."""
    momento = agora or datetime.now(UTC)

    try:
        execucoes = listar_execucoes(limite=_JANELA_EXECUCOES)
        qualidade = listar_relatorio_qualidade(tabela=None, pagina=1, limite=_JANELA_QUALIDADE)
    except GoldIndisponivel as exc:
        logger.error("exporter_gold_indisponivel", erro=str(exc))
        return

    if execucoes.itens:
        atual = execucoes.itens[0]
        for status in dict.fromkeys([*list(_STATUS_CONHECIDOS), atual.status]):
            g_last_run_status.labels(status=status).set(1.0 if status == atual.status else 0.0)
        ts = _parse_ts(atual.execution_timestamp)
        if ts is not None:
            g_last_run_timestamp.set(ts)

        totais: dict[str, float] = {}
        for item in execucoes.itens:
            totais[item.status] = totais.get(item.status, 0.0) + 1.0
        for status, total in totais.items():
            g_runs_total.labels(status=status).set(total)

        for fonte, atributo in _FONTES:
            wm = _parse_watermark(getattr(atual, atributo, None))
            if wm is None:
                continue
            lag_h = (momento - wm).total_seconds() / 3600.0
            if lag_h >= 0:
                g_watermark_lag.labels(fonte=fonte).set(lag_h)

    # DQ: primeira ocorrência por tabela vence (ordem desc = mais recente).
    vistos: set[str] = set()
    g_dq_regras.clear()
    for linha in qualidade.itens:
        if linha.tabela in vistos:
            continue
        vistos.add(linha.tabela)
        g_dq_total.labels(tabela=linha.tabela).set(float(linha.total_registros))
        g_dq_validos.labels(tabela=linha.tabela).set(float(linha.registros_validos))
        g_dq_quarentena.labels(tabela=linha.tabela).set(float(linha.registros_quarentena))
        g_dq_dedup.labels(tabela=linha.tabela).set(float(linha.registros_deduplicados))
        g_dq_nulos.labels(tabela=linha.tabela).set(float(linha.percentual_nulos_criticos))
        for regra in linha.regras_violadas:
            g_dq_regras.labels(tabela=linha.tabela, regra=regra).set(1.0)

    try:
        caminho = caminho_do_gold()
        g_file_bytes.set(float(caminho.stat().st_size))
        with duckdb.connect(str(caminho), read_only=True) as con:
            con.execute("SET search_path = 'gold'")
            total = con.execute("select sum(valor_liquido) from fact_despesa").fetchone()[0]
        if total is not None:
            g_fact_total.set(float(total))
    except (duckdb.Error, OSError) as exc:
        logger.error("exporter_fact_indisponivel", erro=str(exc))

    i_build.info({"versao": get_pipeline_version() or "desconhecida"})


def main() -> None:
    """Sobe o HTTP do exporter e coleta em loop até o processo morrer."""
    config = get_observability().exporter
    start_http_server(int(config.porta))
    logger.info(
        "exporter_iniciado",
        porta=int(config.porta),
        intervalo_s=float(config.intervalo_segundos),
    )
    while True:
        coletar()
        time.sleep(float(config.intervalo_segundos))


if __name__ == "__main__":
    main()
