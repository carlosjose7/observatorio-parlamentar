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
    listar_task_runs,
)
from pipeline.config import get_observability, get_pipeline_version

logger = structlog.get_logger()

# Execuções são buscadas mais recentes primeiro; 1000 cobre ~3 anos de
# runs diárias para o total por status sem reescrever SQL de contagem.
_JANELA_EXECUCOES = 1000
_JANELA_QUALIDADE = 1000
# Spans de task (ADR-056 D1): janela ampla para o histórico por task
# (a Onda 4 deriva a mediana de duração desta mesma janela); nos gauges
# vale o span mais recente por task (primeiro vence, ordem desc).
_JANELA_TASKS = 5000
# Janela de confiabilidade (ADR-056 D2, Onda 2): últimos 30 runs ≈ 30 dias
# @daily. MTTR/MTBF são médias sobre eventos nessa janela — janela curta
# demais vira ruído (1 falha domina), longa demais mascara degradação.
_JANELA_CONFIABILIDADE = 30
# Janela de cobertura operacional (ADR-056 D3, Onda 3): 7 dias móveis.
# Janela curta = sinal operacional (falta de ontem pesa); a janela de
# confiabilidade (30 runs) segue própria para MTTR/MTBF/Sucesso.
_JANELA_COBERTURA_DIAS = 7

# (label fonte, atributo watermark em ExecucaoPipeline) — as 4 fontes.
_FONTES = (
    ("camara", "watermark_camara"),
    ("senado", "watermark_senado"),
    ("cgu_emenda", "watermark_cgu_emenda"),
    ("cgu_cartao", "watermark_cgu_cartao"),
)

# Status conhecidos do controle (pipeline/runs.py — legado + granular
# ADR-056 D1). O status efetivo da última execução é sempre incluído mesmo
# que seja um valor novo (união dinâmica, nunca quebra com evolução).
_STATUS_CONHECIDOS = (
    "success",
    "failed",
    "partial",
    "warning",
    "running",
    "cancelled",
    "timeout",
)

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
g_task_duration = Gauge(
    "pipeline_task_duration_seconds",
    "Duração do span mais recente por task do DAG (ADR-056 D1).",
    ["task"],
)
g_task_status = Gauge(
    "pipeline_task_last_run_status",
    "Status do span mais recente por task (1 no vigente, 0 nos demais).",
    ["task", "status"],
)
g_mttr = Gauge(
    "pipeline_mttr_seconds",
    "Tempo médio entre uma falha e a próxima execução bem-sucedida"
    " (janela: últimos 30 runs, ADR-056 D2). Omitida quando indefinida.",
)
g_mtbf = Gauge(
    "pipeline_mtbf_seconds",
    "Tempo médio entre falhas consecutivas (janela: últimos 30 runs,"
    " ADR-056 D2). Omitida quando indefinida.",
)
g_planejadas = Gauge(
    "pipeline_execucoes_planejadas_total",
    "Execuções esperadas na janela de cobertura (1/dia de calendário,"
    " ADR-056 D3).",
)
g_nao_realizadas = Gauge(
    "pipeline_execucoes_nao_realizadas_total",
    "Execuções esperadas sem run na janela de cobertura (ADR-056 D3).",
)
g_cobertura = Gauge(
    "pipeline_cobertura_ratio",
    "Cobertura 0-1 (realizadas/planejadas na janela de 7 dias, ADR-056 D3)."
    " Conveniência — as séries persistidas são os dois totais.",
)
g_health_index = Gauge(
    "pipeline_health_index",
    "Índice de saúde 0-100 (40% cobertura + 30% sucesso + 20% qualidade"
    " + 10% performance, ADR-056 D4). Omitido sem dado, nunca zerado.",
)
g_health_status = Gauge(
    "pipeline_health_status",
    "Classe vigente do Health Index (1 na classe, 0 nas demais).",
    ["classe"],
)
g_dq_pass = Gauge(
    "pipeline_dq_score_pass_total",
    "Tabelas com DQ PASS no snapshot mais recente (abaixo do warn, ADR-056 D7).",
)
g_dq_warn = Gauge(
    "pipeline_dq_score_warn_total",
    "Tabelas com DQ WARN no snapshot mais recente (ADR-056 D7).",
)
g_dq_fail = Gauge(
    "pipeline_dq_score_fail_total",
    "Tabelas com DQ FAIL no snapshot mais recente (acima do critical, ADR-056 D7).",
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


def _status_efetivo(item) -> str:
    """Status granular quando presente, legado caso contrário (ADR-056 D1).

    Execuções pré-Sprint 26 têm `status_detalhado` nulo — o legado vale.
    Nunca assume presença da coluna nova.
    """
    return getattr(item, "status_detalhado", None) or item.status


def _timestamps_ordenados(itens) -> list[tuple[float, str]]:
    """`(epoch, status legado)` crescente por tempo; sem ts parseável, fora."""
    pares = []
    for item in itens:
        ts = _parse_ts(item.execution_timestamp)
        if ts is not None:
            pares.append((ts, item.status))
    return sorted(pares)


def calcular_mttr(itens, *, janela: int = _JANELA_CONFIABILIDADE) -> float | None:
    """MTTR em segundos sobre os últimos `janela` runs (ADR-056 D2, Onda 2).

    Média de (`ts` do primeiro `success` após cada `failed` − `ts` do
    `failed`). `partial` não é falha nem recuperação (decisão do ADR) —
    é ignorado nos dois papéis. Sem par `failed→success`: None (série
    omitida, nunca zerada — zero significaria recuperação instantânea).
    Usa o `status` LEGADO (estável pré/pós-Sprint 26; o granular futuro
    não reescreve a matemática de confiabilidade).
    """
    eventos = _timestamps_ordenados(itens[:janela])
    sucessos = [ts for ts, status in eventos if status == "success"]
    if not sucessos:
        return None
    recuperacoes = []
    for ts_falha, status in eventos:
        if status != "failed":
            continue
        proximo = next((ts for ts in sucessos if ts > ts_falha), None)
        if proximo is not None:
            recuperacoes.append(proximo - ts_falha)
    if not recuperacoes:
        return None
    return sum(recuperacoes) / len(recuperacoes)


def calcular_mtbf(itens, *, janela: int = _JANELA_CONFIABILIDADE) -> float | None:
    """MTBF em segundos: média dos intervalos entre `failed` consecutivos.

    Menos de 2 falhas na janela: None (omitida, nunca zerada).
    """
    eventos = _timestamps_ordenados(itens[:janela])
    falhas = [ts for ts, status in eventos if status == "failed"]
    if len(falhas) < 2:
        return None
    intervalos = [b - a for a, b in zip(falhas, falhas[1:])]
    return sum(intervalos) / len(intervalos)


def calcular_cobertura(
    itens,
    *,
    agora: datetime | None = None,
    dias: int = _JANELA_COBERTURA_DIAS,
) -> tuple[float, float, float]:
    """Cobertura da janela móvel (ADR-056 D3, Onda 3).

    Planejado = 1 execução por dia de calendário (`@daily` lógico — o
    agendamento físico é o timer systemd, ADR-034). Retorna
    `(planejadas, nao_realizadas, ratio)`: realizadas = runs com ts na
    janela `(agora − dias, agora]`; `nao_realizadas = max(0, planejadas −
    realizadas)` (backfill parado conta como falta — é o sinal, não ruído).
    """
    momento = agora or datetime.now(UTC)
    corte = momento.timestamp() - dias * 86400.0
    planejadas = float(dias)
    realizadas = sum(
        1
        for item in itens
        if (ts := _parse_ts(item.execution_timestamp)) is not None and ts > corte
    )
    nao_realizadas = max(0.0, planejadas - float(realizadas))
    ratio = float(realizadas) / planejadas if planejadas > 0 else 0.0
    return planejadas, nao_realizadas, min(max(ratio, 0.0), 1.0)


# Classes do Health Index (ADR-056 D4): labels ASCII (sem acento) por
# segurança de label; mesma ordem dos intervalos 90/70/50.
_CLASSES_HEALTH = ("saudavel", "atencao", "alerta", "critico")


def classe_health(valor: float) -> str:
    """90–100 Saudável, 70–89 Atenção, 50–69 Alerta, 0–49 Crítico."""
    if valor >= 90.0:
        return "saudavel"
    if valor >= 70.0:
        return "atencao"
    if valor >= 50.0:
        return "alerta"
    return "critico"


def calcular_taxa_sucesso(itens, *, janela: int = _JANELA_CONFIABILIDADE) -> float | None:
    """Sucesso 0–100 nos últimos `janela` runs: `success`=1, `partial`=0.5.

    `partial` vale meio-crédito (coerente com o D2, onde não é falha nem
    recuperação). Sem runs na janela: None.
    """
    pontos = [
        {"success": 1.0, "partial": 0.5}.get(item.status, 0.0)
        for item in itens[:janela]
    ]
    if not pontos:
        return None
    return sum(pontos) / len(pontos) * 100.0


def _ratios_por_grupo(dq_itens) -> tuple[float | None, float | None]:
    """`(ratio_outras, ratio_cartao)` do snapshot DQ mais recente por tabela.

    Primeira ocorrência por tabela vence (ordem desc). Tabela sem total
    positivo é ignorada (nunca divide por zero).
    """
    vistos: set[str] = set()
    quar_outras = total_outras = 0.0
    quar_cartao = total_cartao = 0.0
    for linha in dq_itens:
        if linha.tabela in vistos:
            continue
        vistos.add(linha.tabela)
        total = float(linha.total_registros)
        if total <= 0:
            continue
        if linha.tabela == "silver_cartao":
            quar_cartao += float(linha.registros_quarentena)
            total_cartao += total
        else:
            quar_outras += float(linha.registros_quarentena)
            total_outras += total
    r_outras = quar_outras / total_outras if total_outras > 0 else None
    r_cartao = quar_cartao / total_cartao if total_cartao > 0 else None
    return r_outras, r_cartao


def calcular_qualidade(
    dq_itens, *, crit_outras: float, crit_cartao: float
) -> float | None:
    """Qualidade 0–100 (ADR-056 D4): cada grupo normalizado pelo próprio
    critical (5% demais tabelas, 25% cartão — ADR-054); o pior vence.

    `crit_*` vêm de `config/observability.yaml` (fonte única, nunca
    hardcoded). Sem nenhuma tabela com total positivo: None.
    """
    r_outras, r_cartao = _ratios_por_grupo(dq_itens)
    normalizados = [
        r / c
        for r, c in ((r_outras, crit_outras), (r_cartao, crit_cartao))
        if r is not None and c > 0
    ]
    if not normalizados:
        return None
    return min(max(1.0 - max(normalizados), 0.0), 1.0) * 100.0


def calcular_performance(spans, *, janela: int = _JANELA_CONFIABILIDADE) -> float | None:
    """Performance 0–100: média entre tasks de `100·clamp(mediana_30/ultima)`.

    Baseline = mediana das últimas `janela` durações da task; `ultima` = a
    mais recente. Degradação (última acima da mediana) derruba o score;
    melhora nunca passa de 100. Task sem duração válida é ignorada; sem
    nenhuma task: None.
    """
    from statistics import median

    por_task: dict[str, list[float]] = {}
    for span in spans:
        duracao = getattr(span, "duration_seconds", None)
        if duracao is None:
            continue
        por_task.setdefault(span.task, []).append(float(duracao))
    notas = []
    for duracoes in por_task.values():
        historico = duracoes[:janela]
        baseline = median(historico)
        ultima = historico[0]
        if baseline <= 0 or ultima is None:
            continue
        notas.append(min(max(baseline / ultima if ultima > 0 else 1.0, 0.0), 1.0) * 100.0)
    if not notas:
        return None
    return sum(notas) / len(notas)


def calcular_health(
    exec_itens,
    dq_itens,
    spans,
    *,
    agora: datetime | None = None,
    crit_outras: float,
    crit_cartao: float,
) -> tuple[float, str] | None:
    """Health Index (ADR-056 D4): 40% cobertura + 30% sucesso + 20% qualidade
    + 10% performance. Qualquer componente ausente (0 runs, sem DQ, sem
    spans) → None: omitido, nunca 0 (0 = Crítico falso). Retorna
    `(valor_0_100, classe)`.
    """
    _, _, ratio = calcular_cobertura(exec_itens, agora=agora)
    cobertura = ratio * 100.0
    sucesso = calcular_taxa_sucesso(exec_itens)
    qualidade = calcular_qualidade(dq_itens, crit_outras=crit_outras, crit_cartao=crit_cartao)
    performance = calcular_performance(spans)
    if sucesso is None or qualidade is None or performance is None:
        return None
    valor = 0.4 * cobertura + 0.3 * sucesso + 0.2 * qualidade + 0.1 * performance
    valor = min(max(valor, 0.0), 100.0)
    return valor, classe_health(valor)


def classificar_dq(
    dq_itens, *, warn_outras: float, crit_outras: float, warn_cartao: float, crit_cartao: float
) -> dict[str, int]:
    """PASS/FAIL/WARN por tabela do snapshot DQ mais recente (ADR-056 D7).

    Agrega o `dq_regras_violadas`/`dq_quarentena` EXISTENTE — nada recriado:
    FAIL se ratio de quarentena > critical da tabela (5% demais, 25%
    cartão — ADR-054); WARN se > warn (2%/20%); senão PASS. Réguas vêm de
    `config/observability.yaml` (fonte única). Retorna contagens
    `{"pass": n, "warn": n, "fail": n}` (primeira ocorrência por tabela
    vence; tabela sem total positivo é ignorada).
    """
    contagem = {"pass": 0, "warn": 0, "fail": 0}
    vistos: set[str] = set()
    for linha in dq_itens:
        if linha.tabela in vistos:
            continue
        vistos.add(linha.tabela)
        total = float(linha.total_registros)
        if total <= 0:
            continue
        ratio = float(linha.registros_quarentena) / total
        if linha.tabela == "silver_cartao":
            warn, crit = warn_cartao, crit_cartao
        else:
            warn, crit = warn_outras, crit_outras
        if ratio > crit:
            contagem["fail"] += 1
        elif ratio > warn:
            contagem["warn"] += 1
        else:
            contagem["pass"] += 1
    return contagem


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
        vigente = _status_efetivo(atual)
        for status in dict.fromkeys([*list(_STATUS_CONHECIDOS), vigente]):
            g_last_run_status.labels(status=status).set(1.0 if status == vigente else 0.0)
        ts = _parse_ts(atual.execution_timestamp)
        if ts is not None:
            g_last_run_timestamp.set(ts)

        totais: dict[str, float] = {}
        for item in execucoes.itens:
            efetivo = _status_efetivo(item)
            totais[efetivo] = totais.get(efetivo, 0.0) + 1.0
        for status, total in totais.items():
            g_runs_total.labels(status=status).set(total)

        for fonte, atributo in _FONTES:
            wm = _parse_watermark(getattr(atual, atributo, None))
            if wm is None:
                continue
            lag_h = (momento - wm).total_seconds() / 3600.0
            if lag_h >= 0:
                g_watermark_lag.labels(fonte=fonte).set(lag_h)

    # Tasks (ADR-056 D1): span mais recente por task (ordem desc = primeiro
    # vence). Tabela de controle nova na Sprint 26 — Gold pré-Onda 1 não a
    # tem: bloco defensivo próprio (log + segue), as demais séries seguem
    # publicadas (`run_id` nunca é label; `task` segue o vocabulário
    # `TASKS_CONHECIDAS` de `pipeline/runs.py` + valor vigente).
    try:
        spans = listar_task_runs(limite=_JANELA_TASKS)
    except GoldIndisponivel as exc:
        logger.warning("exporter_task_runs_indisponiveis", erro=str(exc))
        spans = None
    if spans is not None:
        vistas: set[str] = set()
        for span in spans.itens:
            if span.task in vistas:
                continue
            vistas.add(span.task)
            if span.duration_seconds is not None:
                g_task_duration.labels(task=span.task).set(float(span.duration_seconds))
            for status in dict.fromkeys([*list(_STATUS_CONHECIDOS), span.status]):
                g_task_status.labels(task=span.task, status=status).set(
                    1.0 if status == span.status else 0.0
                )

    # Thresholds do config (fonte única, ADR-008) — reutilizados no score
    # DQ (Onda 7) e no Health (Onda 4) abaixo.
    slos = get_observability().slos

    # Confiabilidade (ADR-056 D2, Onda 2): indefinido vira NaN — o
    # prometheus_client expõe Gauge nunca-atualizado como 0.0, o que
    # derrotaria o "omitido, nunca zerado". NaN propaga como ausência
    # no PromQL/Grafana (painel "sem dado", alerta não dispara).
    mttr = calcular_mttr(execucoes.itens)
    g_mttr.set(mttr if mttr is not None else float("nan"))
    mtbf = calcular_mtbf(execucoes.itens)
    g_mtbf.set(mtbf if mtbf is not None else float("nan"))

    # Cobertura operacional (ADR-056 D3, Onda 3).
    planejadas, nao_realizadas, ratio = calcular_cobertura(execucoes.itens, agora=momento)
    g_planejadas.set(planejadas)
    g_nao_realizadas.set(nao_realizadas)
    g_cobertura.set(ratio)

    # Health Index (ADR-056 D4, Onda 4): thresholds `slos` (fonte única,
    # lidos acima).
    health = calcular_health(
        execucoes.itens,
        qualidade.itens,
        spans.itens if spans is not None else [],
        agora=momento,
        crit_outras=slos.quarentena_critical_pct / 100.0,
        crit_cartao=slos.quarentena_cartao_critical_pct / 100.0,
    )
    if health is not None:
        valor, classe = health
        g_health_index.set(valor)
        for candidata in dict.fromkeys([*list(_CLASSES_HEALTH), classe]):
            g_health_status.labels(classe=candidata).set(
                1.0 if candidata == classe else 0.0
            )
    else:
        # Mesmo motivo do NaN acima: sem componentes, o índice exporia
        # 0.0 (= Crítico falso). As classes vigentes anteriores são
        # removidas para não vazar estado obsoleto.
        g_health_index.set(float("nan"))
        for candidata in _CLASSES_HEALTH:
            try:
                g_health_status.remove(candidata)
            except KeyError:
                pass

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

    # Score agregado (ADR-056 D7, Onda 7).
    score = classificar_dq(
        qualidade.itens,
        warn_outras=slos.quarentena_warn_pct / 100.0,
        crit_outras=slos.quarentena_critical_pct / 100.0,
        warn_cartao=slos.quarentena_cartao_warn_pct / 100.0,
        crit_cartao=slos.quarentena_cartao_critical_pct / 100.0,
    )
    g_dq_pass.set(float(score["pass"]))
    g_dq_warn.set(float(score["warn"]))
    g_dq_fail.set(float(score["fail"]))

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
