"""pipeline/utils.py — utilidades compartilhadas entre as camadas do pipeline.

Concentra a política de retry (tenacity, ADR-009), a serialização de
registros Pydantic para DataFrame e a normalização das colunas de metadados
de carga (RF-12).
"""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd
import structlog
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from pipeline.config import RetryDefaultSettings, get_pipeline

logger = structlog.get_logger()


def _is_retriable(exc: BaseException) -> bool:
    """Somente erros transitórios são reexecutados (5xx, 429, transporte).

    Erros 4xx (ex: 401 sem chave da CGU) não são retriáveis — propagam
    imediatamente para que a falha seja reportada como tal.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


def _tentativa(settings: RetryDefaultSettings) -> Retrying:
    """Monta um objeto `Retrying` do tenacity a partir da config (ADR-009)."""
    return Retrying(
        reraise=True,
        stop=stop_after_attempt(settings.max_tentativas),
        wait=wait_exponential(
            multiplier=settings.espera_exponencial_min_segundos,
            min=settings.espera_exponencial_min_segundos,
            max=settings.espera_exponencial_max_segundos,
        ),
        retry=retry_if_exception(_is_retriable),
    )


def _resolver_settings(retry_settings: RetryDefaultSettings | None) -> RetryDefaultSettings:
    return retry_settings or get_pipeline().retry_default


def _get_json(client: httpx.Client, url: str, params: dict[str, Any] | None) -> Any:
    resp = client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def request_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    retry_settings: RetryDefaultSettings | None = None,
) -> Any:
    """GET com retry automático (tenacity, ADR-009) e validação de status.

    Args:
        client: Cliente HTTP (httpx) compartilhado e injetável.
        url: URL do endpoint.
        params: Query params opcionais.
        retry_settings: Política de retry; se ausente, usa `retry_default`
            de config/pipeline.yaml.

    Returns:
        JSON da resposta (dict ou list, conforme o endpoint).

    Raises:
        httpx.HTTPStatusError: para status >= 400 não retriável.
        httpx.TransportError: se a rede falhar após as tentativas.
    """
    return _tentativa(_resolver_settings(retry_settings))(_get_json, client, url, params)


def _get_text(client: httpx.Client, url: str, encoding: str) -> str:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.content.decode(encoding)


def request_text(
    client: httpx.Client,
    url: str,
    encoding: str = "utf-8",
    retry_settings: RetryDefaultSettings | None = None,
) -> str:
    """GET com retry automático retornando texto decodificado (ex: CSV do Senado)."""
    return _tentativa(_resolver_settings(retry_settings))(_get_text, client, url, encoding)


def records_to_dataframe(records: list) -> pd.DataFrame:
    """Converte registros Pydantic em DataFrame plano (valores JSON-native).

    Os metadados de carga (RF-12) são achatados para o nível superior:
    `metadata.*` vira colunas (ex: `metadata_run_id` → `run_id`). Objetos
    aninhados (ex: `estabelecimento`, `portador` na CGU) são achatados com
    separador `_` (ex: `estabelecimento_nome`).

    Args:
        records: Lista de modelos Pydantic da camada Bronze.

    Returns:
        DataFrame com uma linha por registro, pronto para Parquet.
    """
    if not records:
        return pd.DataFrame()
    linhas = [r.model_dump(mode="json") for r in records]
    df = pd.json_normalize(linhas, sep="_")
    df.columns = [
        col.removeprefix("metadata_") if col.startswith("metadata_") else col
        for col in df.columns
    ]
    return df
