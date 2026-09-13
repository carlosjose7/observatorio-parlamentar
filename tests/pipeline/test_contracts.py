"""tests/pipeline/test_contracts.py — resolve_tipo_documento (ADR-011).

Regressão 10/09/2026: Bronze com `cnpj_cpf_fornecedor` nulo chega ao
transform como NaN (float) e derrubava `executar_silver` com
`AttributeError: 'float' object has no attribute 'strip'` — 3 runs
diários falhos seguidos, site 5 dias sem atualizar. NaN = ausência =
(None, None), nunca identidade fantasma.
"""

from __future__ import annotations

import math

from pipeline.contracts import TipoDocumento, resolve_tipo_documento


def test_nulo_e_vazio_retornam_none_none():
    assert resolve_tipo_documento(None) == (None, None)
    assert resolve_tipo_documento("") == (None, None)
    assert resolve_tipo_documento("   ") == (None, None)


def test_nan_do_pandas_e_nulo():
    assert resolve_tipo_documento(float("nan")) == (None, None)
    assert resolve_tipo_documento(math.nan) == (None, None)


def test_bool_e_float_nao_documento_sao_nulos():
    assert resolve_tipo_documento(True) == (None, None)
    assert resolve_tipo_documento(12.5) == (None, None)


def test_int_vira_digitos():
    digitos, tipo = resolve_tipo_documento(12345678000190)
    assert (digitos, tipo) == ("12345678000190", TipoDocumento.CNPJ)


def test_classificacao_por_comprimento():
    assert resolve_tipo_documento("12.345.678/0001-90")[1] is TipoDocumento.CNPJ
    assert resolve_tipo_documento("123.456.789-01")[1] is TipoDocumento.CPF
    assert resolve_tipo_documento("12345")[1] is TipoDocumento.INVALIDO
