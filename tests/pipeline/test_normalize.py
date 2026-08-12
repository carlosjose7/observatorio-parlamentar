# tests/pipeline/test_normalize.py
"""Testes unitários do pipeline/normalize.py (ADR-016).

Cobre parsing multi-formato de datas (Câmara ISO 8601, Senado/CGU DD/MM/AAAA),
valores monetários pt-BR (vírgula decimal, separador de milhar, ponto decimal) e
sanitização de CNPJ/CPF. Garante a regra central do ADR-016: valores não
parseáveis retornam `None` + log, nunca lançam.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pipeline.normalize import (
    clean_document_number,
    parse_date_multi_format,
    parse_decimal_ptbr,
)


class TestParseDateMultiFormat:
    def test_iso_8601_camara(self):
        assert parse_date_multi_format("2024-07-03T00:00:00") == date(2024, 7, 3)

    def test_iso_8601_com_microssegundos(self):
        assert parse_date_multi_format("2024-07-03T00:00:00.123") == date(2024, 7, 3)

    def test_iso_data_simples(self):
        assert parse_date_multi_format("2024-07-03") == date(2024, 7, 3)

    def test_ptbr_senado_cgu(self):
        assert parse_date_multi_format("03/07/2024") == date(2024, 7, 3)

    def test_formato_explicito_prioriza_sobre_padroes(self):
        assert (
            parse_date_multi_format("03/07/2024", formatos=("%d/%m/%Y",)) == date(2024, 7, 3)
        )

    def test_valor_invalido_retorna_none(self):
        assert parse_date_multi_format("abc") is None

    def test_vazio_e_nulo_retornam_none(self):
        assert parse_date_multi_format("") is None
        assert parse_date_multi_format("   ") is None
        assert parse_date_multi_format(None) is None

    def test_ano_absurdo_retorna_none_nao_estoura_pandas(self):
        """Corretivo 6.5: CSV real do Senado traz `06/10/2915`; um ano assim
        estoura o `datetime64[ns]` do pandas (máx. 2262) antes do gate
        Pandera. O parser rejeita e devolve `None` (→ quarentena, ADR-016)."""
        assert parse_date_multi_format("06/10/2915") is None
        assert parse_date_multi_format("2915-10-06") is None

    def test_ano_limite_inferior_aceito(self):
        assert parse_date_multi_format("01/01/2015") == date(2015, 1, 1)

    def test_ano_inicial_cgu_2012_aceito(self):
        """Corretivo QA (E2E Sprint 6.5): a CGU publica cartões CPGF desde
        2012 (mes_inicio "01/2013", transações de dez/2012 nos extratos) —
        o parser rejeitava anos < 2015 e nublava a fonte inteira de cartões."""
        assert parse_date_multi_format("05/12/2012") == date(2012, 12, 5)
        assert parse_date_multi_format("03/01/2013") == date(2013, 1, 3)


class TestParseDecimalPtbr:
    def test_virgula_decimal_senado(self):
        assert parse_decimal_ptbr("120,50") == Decimal("120.50")

    def test_milhar_e_decimal_cgu(self):
        assert parse_decimal_ptbr("1.234,56") == Decimal("1234.56")

    def test_ponto_decimal(self):
        assert parse_decimal_ptbr("1234.56") == Decimal("1234.56")

    def test_milhar_sem_decimal(self):
        assert parse_decimal_ptbr("1234") == Decimal("1234")

    def test_zero(self):
        assert parse_decimal_ptbr("0") == Decimal("0")

    def test_invalido_retorna_none(self):
        assert parse_decimal_ptbr("abc,de") is None

    def test_vazio_e_nulo_retornam_none(self):
        assert parse_decimal_ptbr("") is None
        assert parse_decimal_ptbr(None) is None


class TestCleanDocumentNumber:
    def test_cnpj_formatado(self):
        assert clean_document_number("00.000.000/0001-91") == "00000000000191"

    def test_cpf_formatado(self):
        assert clean_document_number("123.456.789-00") == "12345678900"

    def test_spacos_internos(self):
        assert clean_document_number(" 11.222.333/0001-81 ") == "11222333000181"

    def test_sem_formatacao_nao_altera(self):
        assert clean_document_number("11222333000181") == "11222333000181"

    def test_vazio_e_nulo_retornam_none(self):
        assert clean_document_number("") is None
        assert clean_document_number(None) is None

    def test_somente_simbolos_retorna_none(self):
        assert clean_document_number("---/...") is None