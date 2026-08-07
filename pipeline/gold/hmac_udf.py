"""Plugin dbt-duckdb — registra a UDF escalar `hmac_sha256_cpf`.

O Gold pseudonimiza CPF na dimensão `dim_fornecedor` (ADR-011/ADR-004); o
DuckDB não expõe HMAC nativamente, então este plugin registra a função na
conexão aberta pelo dbt. A chave é lida de `CPF_HMAC_SECRET_KEY` (ambient
ou `.env` na raiz do repo, via python-dotenv) — nunca aparece no SQL
compilado nem em arquivos de target.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_module
import os
from pathlib import Path

import duckdb

from dbt.adapters.duckdb.plugins import BasePlugin

_RAIZ = Path(__file__).resolve().parents[2]


def _segredo() -> str:
    """Chave HMAC de `os.environ`, com fallback para `.env` da raiz."""
    valor = os.environ.get("CPF_HMAC_SECRET_KEY") or ""
    if not valor:
        try:
            from dotenv import load_dotenv

            load_dotenv(_RAIZ / ".env", override=False)
        except ImportError:
            pass
        valor = os.environ.get("CPF_HMAC_SECRET_KEY") or ""
    return valor


class Plugin(BasePlugin):
    """Registra `hmac_sha256_cpf(mensagem)` na conexão do dbt-duckdb.

    A função devolve o digest hex HMAC-SHA256 da mensagem (CPF em dígitos),
    ou None para valor nulo. Levanta `RuntimeError` se a chave estiver
    ausente — pseudonimização nunca opera com chave vazia.
    """

    def configure_connection(self, conn):
        chave = _segredo()
        if not chave:
            raise RuntimeError(
                "CPF_HMAC_SECRET_KEY ausente: defina em .env ou no ambiente "
                "(config.py EnvSettings.cpf_hmac_secret_key). O Gold não "
                "pseudonimiza CPF sem chave."
            )

        def hmac_sha256_cpf(mensagem: str | None) -> str | None:
            if mensagem is None or str(mensagem) == "":
                return None
            return hmac_module.new(
                chave.encode("utf-8"),
                str(mensagem).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

        try:
            conn.create_function(
                "hmac_sha256_cpf", hmac_sha256_cpf, return_type="VARCHAR"
            )
        except duckdb.Error as erro:
            if "already exists" not in str(erro).lower():
                raise