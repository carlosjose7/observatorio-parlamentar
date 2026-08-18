"""pipeline/utils.py — utilidades compartilhadas entre as camadas do pipeline.

Concentra a política de retry (tenacity, ADR-009), o throttling proativo
(token bucket, ADR-009 §rate limiting), a serialização de registros Pydantic
para DataFrame e a normalização das colunas de metadados de carga (RF-12).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
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


class RateLimiter:
    """Token bucket proativo (throttling, ADR-009 §rate limiting).

    Consulta o token **antes** de cada requisição HTTP (`request_json`/
    `request_text`) para que a taxa de saída nunca ultrapasse o limite da
    fonte. Necessário para a CGU: exceder o limite suspende a **chave inteira**
    por 8h — não é um 429 pontual que retry reativo resolve. Corretivo 6.5.

    A taxa pode ser fixa (Câmara) ou variar com a hora do dia (CGU diurno/
    noturno, via `taxa_por_minuto` como callable, reavaliada a cada
    `aguardar()`). `fator_seguranca` aplica ~80-90% do limite documentado
    como alvo (margem contra o custo de 8h).

    **Capacidade (decisão explícita):** o bucket inicia com ~1 segundo de
    tokens (`taxa × fator / 60`), NÃO com a janela inteira (ex: 340 tokens).
    Consequência deliberada: o burst máximo é de ~6 requisições, e a taxa
    sustentada converge para o alvo por minuto — nunca se "dispara" o limite
    inteiro de uma vez (para a CGU, melhor mais lento que chave suspensa).
    Thread-safe (lock + reserva do token).
    """

    def __init__(
        self,
        taxa_por_minuto: int | float | Callable[[], float],
        fator_seguranca: float = 0.85,
        monotonic: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._taxa = (
            taxa_por_minuto
            if callable(taxa_por_minuto)
            else (lambda: float(taxa_por_minuto))
        )
        self._fator = fator_seguranca
        self._monotonic = monotonic
        self._dormir = dormir
        self._capacidade = max(1.0, self._taxa() * self._fator / 60.0)
        self._tokens = self._capacidade
        self._ts = self._monotonic()
        self._lock = threading.Lock()

    def aguardar(self) -> None:
        """Bloqueia até haver token disponível (uma requisição por token)."""
        with self._lock:
            agora = self._monotonic()
            taxa_seg = self._taxa() * self._fator / 60.0
            self._tokens = min(
                self._capacidade, self._tokens + (agora - self._ts) * taxa_seg
            )
            self._ts = agora
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            espera = (1.0 - self._tokens) / taxa_seg
            self._ts += espera  # reserva o token para as demais threads
            self._tokens = 0.0
        if espera > 0:
            self._dormir(espera)


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


def _get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None,
    headers: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
) -> Any:
    if limiter is not None:
        limiter.aguardar()
    resp = client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


def request_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    retry_settings: RetryDefaultSettings | None = None,
    headers: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
) -> Any:
    """GET com retry automático (tenacity, ADR-009) e validação de status.

    Args:
        client: Cliente HTTP (httpx) compartilhado e injetável.
        url: URL do endpoint.
        params: Query params opcionais.
        retry_settings: Política de retry; se ausente, usa `retry_default`
            de config/pipeline.yaml.
        headers: Headers HTTP opcionais (ex: `chave-api-dados` da CGU —
            `AuthTransparenciaSettings`, sources.yaml).
        limiter: Throttling proativo (token bucket, ADR-009 §rate limiting).
            Consulta o token ANTES de cada requisição (e de cada retry) —
            nunca deixa a taxa de saída ultrapassar o limite da fonte.

    Returns:
        JSON da resposta (dict ou list, conforme o endpoint).

    Raises:
        httpx.HTTPStatusError: para status >= 400 não retriável.
        httpx.TransportError: se a rede falhar após as tentativas.
    """
    return _tentativa(_resolver_settings(retry_settings))(
        _get_json, client, url, params, headers, limiter
    )


def _get_text(
    client: httpx.Client,
    url: str,
    encoding: str,
    limiter: RateLimiter | None = None,
) -> str:
    if limiter is not None:
        limiter.aguardar()
    resp = client.get(url)
    resp.raise_for_status()
    return resp.content.decode(encoding)


def request_text(
    client: httpx.Client,
    url: str,
    encoding: str = "utf-8",
    retry_settings: RetryDefaultSettings | None = None,
    limiter: RateLimiter | None = None,
) -> str:
    """GET com retry automático retornando texto decodificado (ex: CSV do Senado)."""
    return _tentativa(_resolver_settings(retry_settings))(
        _get_text, client, url, encoding, limiter
    )


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
