# tests/pipeline/test_gold_hmac_udf.py
"""Testes do plugin dbt-duckdb `hmac_udf` — pseudonimização de CPF no Gold.

Regressão da Trilha B (Sprint 4): `configure_connection` usava `con`
(NameError) dentro de um `try/except Exception: pass` — o erro real era
mascarado e a UDF nunca chegava à conexão; o dano só aparecia no `dbt build`
na hora de materializar `dim_fornecedor`. Estes testes cobrem o registro
isolado (sem depender do dbt), a idempotência (conexão já registrada),
a ausência de chave e a propagação de erros reais de registro.

Segue PROJECT_CONTEXT.md §15: nenhum `except` silencioso no código sob teste.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_module
import sys
from pathlib import Path

import duckdb
import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD_DIR = _RAIZ / "pipeline" / "gold"

if str(_GOLD_DIR) not in sys.path:
    sys.path.insert(0, str(_GOLD_DIR))

import hmac_udf  # noqa: E402  (sys.path manipulado acima de proposito)

CHAVE = "Contra-de-NVeLHMAC-teste-2026"
CPF = "12345678901"


def _plugin() -> hmac_udf.Plugin:
    return hmac_udf.Plugin(name="hmac_udf", plugin_config={})


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _digest_esperado() -> str:
    return hmac_module.new(CHAVE.encode("utf-8"), CPF.encode("utf-8"), hashlib.sha256).hexdigest()


class TestRegistro:
    def test_chave_registra_funcao_e_computa_hmac(self, monkeypatch):
        monkeypatch.setenv("CPF_HMAC_SECRET_KEY", CHAVE)
        con = _con()
        _plugin().configure_connection(con)

        assert con.execute(
            "select hmac_sha256_cpf('" + CPF + "')"
        ).fetchone()[0] == _digest_esperado()

    def test_nulos_e_vazios_retornam_none(self, monkeypatch):
        monkeypatch.setenv("CPF_HMAC_SECRET_KEY", CHAVE)
        con = _con()
        _plugin().configure_connection(con)

        assert con.execute("select hmac_sha256_cpf(NULL)").fetchone()[0] is None
        assert con.execute("select hmac_sha256_cpf('')").fetchone()[0] is None

    def test_idempotente_quando_ja_registrada(self, monkeypatch):
        # Segunda chamada não pode falhar nem reverter o registro — regressão
        # do anti-padrão "já existe" quebrado (o DuckDB acusa função criada).
        monkeypatch.setenv("CPF_HMAC_SECRET_KEY", CHAVE)
        con = _con()
        plugin = _plugin()
        plugin.configure_connection(con)
        plugin.configure_connection(con)

        assert con.execute(
            "select hmac_sha256_cpf('" + CPF + "')"
        ).fetchone()[0] == _digest_esperado()

    def test_sem_chave_levanta_runtime_error(self, monkeypatch):
        monkeypatch.delenv("CPF_HMAC_SECRET_KEY", raising=False)
        monkeypatch.setattr(hmac_udf, "_segredo", lambda: "")

        with pytest.raises(RuntimeError, match="CPF_HMAC_SECRET_KEY ausente"):
            _plugin().configure_connection(_con())

    def test_erro_real_de_registro_nao_e_engolido(self, monkeypatch):
        # Regressão do holerite: erro do registro (não-duplicado) tem que dar
        # raise, nunca passar batido — §15 proíbe "except: pass".
        monkeypatch.setenv("CPF_HMAC_SECRET_KEY", CHAVE)

        class _CursorVazio:
            def fetchone(self):
                return None

        class _ConexaoFalha:
            def execute(self, _sql):
                return _CursorVazio()

            def create_function(self, *_args, **_kwargs):
                raise duckdb.Error("erro simulado no registro da UDF")

        with pytest.raises(duckdb.Error, match="erro simulado no registro"):
            _plugin().configure_connection(_ConexaoFalha())
