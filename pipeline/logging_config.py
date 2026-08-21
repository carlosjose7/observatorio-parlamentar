"""pipeline/logging_config.py — configuração do logging estruturado (structlog).

Aplica a seção `logging:` de `config/pipeline.yaml` (ADR-008): o formato
(`json` por padrão) e o nivel (via env var declarada em `nivel_env_var`).
Centraliza o `structlog.configure` que antes ficava implícito (a config
declarava `formato: "json"` mas nenhum módulo configurava structlog).

Chamado pelos entrypoints reais do pipeline (Airflow DAG e `run_pipeline`)
antes da primeira emissão de log.

NOMEADO `logging_config` (não `logging`) de propósito: em produção o
docker-compose monta `./pipeline:/opt/airflow/dags` com
`PYTHONPATH=/opt/airflow/dags`, e um módulo chamado `logging` sombrearia o
stdlib do Python, quebrando o próprio Airflow em import circular.
"""

from __future__ import annotations

import logging
import os

import structlog

from pipeline.config import get_env, get_pipeline


def configure_logging() -> None:
    """Configura o structlog a partir de `config/pipeline.yaml`.

    Define o nível de log a partir de `EnvSettings.log_level` (carregado do
    `.env` / ambiente) e o formato conforme a config (default `json`). Deve ser
    chamado antes de emitir logs em execução real. Em testes/dev não é
    obrigatório (structlog opera com defaults), mas garante o formato
    declarado quando o pipeline roda de verdade.
    """
    cfg = get_pipeline().logging
    env = get_env()
    nivel_raw = os.getenv(cfg.nivel_env_var, env.log_level)
    nivel = getattr(logging, nivel_raw.upper(), logging.INFO)

    shared = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if cfg.formato == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(nivel),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
