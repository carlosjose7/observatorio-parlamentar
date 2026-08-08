# tests/pipeline/test_parlamento.py
"""Testes do domínio parlamentar compartilhado (ADR-024).

Cobre o calendário de legislaturas (`legislatura_para_data`) e o de-para de
`situacao` (`normalizar_situacao`) — a base da paridade Câmara×Senado de
`silver_parlamentar`.
"""

from __future__ import annotations

from datetime import date

from pipeline.parlamento import (
    SituacaoParlamentar,
    legislatura_para_data,
    normalizar_situacao,
)


class TestLegislaturaParaData:
    def test_legislatura_57_vigente_em_2026(self):
        assert legislatura_para_data(date(2026, 8, 7)) == 57

    def test_fronteira_inicio_inclusiva(self):
        assert legislatura_para_data(date(2023, 2, 1)) == 57

    def test_fronteira_fim_exclusiva(self):
        assert legislatura_para_data(date(2027, 1, 31)) == 57
        assert legislatura_para_data(date(2027, 2, 1)) == 58

    def test_antes_do_calendario_retorna_none(self):
        assert legislatura_para_data(date(2000, 1, 1)) is None

    def test_depois_do_calendario_retorna_none(self):
        assert legislatura_para_data(date(2031, 2, 1)) is None


class TestNormalizarSituacao:
    def test_mapeia_exercicio_camara_para_ativo(self):
        assert normalizar_situacao("camara", "Exercício") == "ativo"

    def test_mapeia_titular_senado_para_ativo(self):
        assert normalizar_situacao("senado", "Titular") == "ativo"

    def test_acentos_e_maiusculas_sao_normalizados(self):
        assert normalizar_situacao("camara", "LICENÇA") == "licenca"

    def test_valor_desconhecido_vira_sentinela(self):
        assert normalizar_situacao("camara", "Carimbo") == "nao_mapeado"

    def test_vazio_retorna_sentinela(self):
        assert normalizar_situacao("camara", None) == "nao_mapeado"
        assert normalizar_situacao("senado", "") == "nao_mapeado"

    def test_todos_os_enum_sao_strings_validas(self):
        valores = [situacao.value for situacao in SituacaoParlamentar]
        assert valores == ["ativo", "licenca", "afastado", "fim_mandato", "nao_mapeado"]