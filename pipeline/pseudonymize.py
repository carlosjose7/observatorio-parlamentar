from __future__ import annotations

import hashlib
import hmac as hmac_module
from typing import Iterable

from pipeline.config import get_env

__all__ = ["pseudonymize_cpf", "pseudonymize_cpf_column"]


def pseudonymize_cpf(cpf: str, secret_key: bytes) -> str:
    """Digest hex HMAC-SHA256 do CPF em dígitos (pseudonimização, ADR-033).

    Fonte única da implementação de hash de CPF, usada pelos `transform.py`
    das três fontes (que preenchem a Silver). Determinístico para a mesma
    chave — joins entre camadas e re-execuções produzem o mesmo valor; a
    chave nunca integra o resultado.

    O CPF deixa de trafegar em dígitos limpos após a Bronze: a Silver persiste
    apenas este digest e o Gold (dbt) apenas o repassa por igualdade direta
    nos JOINs — nunca reaplica hash (evita-se hash-de-hash). CNPJ não é dado
    pessoal na mesma categoria e permanece em texto claro (ADR-011/ADR-033).
    """
    if not cpf or not cpf.strip():
        raise ValueError(
            "CPF vazio não é pseudonimizável (ADR-011: sem identidade fantasma)"
        )
    return hmac_module.new(secret_key, cpf.encode("utf-8"), hashlib.sha256).hexdigest()


def _chave_ativa() -> bytes:
    """Chave HMAC de `EnvSettings.cpf_hmac_secret_key`, com fail-fast.

    Pseudonimização nunca opera com chave vazia: sem a chave, a carga Silver
    falha em vez de persistir CPF em dígitos (ADR-033). `get_env()` é
    cacheado por `functools.lru_cache` — os testes injetam a variável antes e
    limpam o cache de `pipeline.config.load_env_settings` (mesmo padrão de
    `api/conftest.py`).
    """
    valor = get_env().cpf_hmac_secret_key.get_secret_value()
    if not valor:
        raise RuntimeError(
            "CPF_HMAC_SECRET_KEY ausente: defina no ambiente ou .env "
            "(pipeline/config.py EnvSettings.cpf_hmac_secret_key). A Silver não "
            "pseudonimiza CPF sem chave (ADR-033)."
        )
    return valor.encode("utf-8")


def pseudonymize_cpf_column(
    values: Iterable[str | None], types: Iterable[str | None]
) -> list[str | None]:
    """Aplica HMAC aos valores classificados como CPF (ADR-033).

    Valores classificados como CNPJ (14 dígitos), nulos ou de tipo
    indefinido permanecem como estão — a classificação é a do ADR-011
    (`resolve_tipo_documento`). A chave é lida **uma única vez e somente
    quando há ao menos um CPF** na leva — cargas sem CPF (ex.: só CNPJ)
    não dependem de `CPF_HMAC_SECRET_KEY`.
    """
    valores = list(values)
    tipos = list(types)
    if any(t == "CPF" for t in tipos):
        chave = _chave_ativa()
    else:
        chave = b""
    return [
        pseudonymize_cpf(valor, chave) if tipo == "CPF" and valor else valor
        for valor, tipo in zip(valores, tipos)
    ]
