"""Fronteiras de segurança da pseudonimização CPF — Sprint 8."""

from types import SimpleNamespace

import pytest

import pipeline.pseudonymize as pseudonymize


def test_cpf_vazio_e_chave_ausente_falham_sem_expor_valor(monkeypatch):
    with pytest.raises(ValueError, match="CPF vazio"):
        pseudonymize.pseudonymize_cpf("  ", b"chave")

    secret = SimpleNamespace(get_secret_value=lambda: "")
    monkeypatch.setattr(pseudonymize, "get_env", lambda: SimpleNamespace(cpf_hmac_secret_key=secret))
    with pytest.raises(RuntimeError, match="CPF_HMAC_SECRET_KEY ausente"):
        pseudonymize.pseudonymize_cpf_column(["12345678901"], ["CPF"])


def test_coluna_sem_cpf_nao_exige_chave_e_preserva_alinhamento(monkeypatch):
    def nao_deveria_ler_chave():
        raise AssertionError("não deve buscar chave em lote sem CPF")

    monkeypatch.setattr(pseudonymize, "_chave_ativa", nao_deveria_ler_chave)
    assert pseudonymize.pseudonymize_cpf_column(
        ["11222333000181", None, "invalido"], ["CNPJ", None, "INVALIDO"]
    ) == ["11222333000181", None, "invalido"]
