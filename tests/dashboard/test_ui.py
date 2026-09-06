# tests/dashboard/test_ui.py
"""Testes dos utilitários de UI do dashboard (dashboard/ui.py, Sprint 7).

Cobre o formatador de moeda pt-BR e o comportamento de `tabela_exportavel`
quando o DataFrame está vazio (estado amigável, RF-08).
"""

from __future__ import annotations

import pandas as pd

from dashboard.ui import anos_de_janela, formatar_moeda, formatar_moeda_compacto, num_seguro


class TestFormatarMoeda:
    def test_valor_nulo_vira_travessao(self):
        assert formatar_moeda(None) == "—"

    def test_valor_zero(self):
        assert formatar_moeda(0.0) == "R$ 0,00"

    def test_valor_com_centavos_ptbr(self):
        assert formatar_moeda(1234.56) == "R$ 1.234,56"

    def test_valor_inteiro(self):
        assert formatar_moeda(1000) == "R$ 1.000,00"

    def test_valor_pequeno(self):
        assert formatar_moeda(0.5) == "R$ 0,50"


class TestExportacaoVazia:
    def test_tabela_vazia_nao_quebra(self, monkeypatch):
        """`tabela_exportavel` com DataFrame vazio exibe info, sem erro."""
        import streamlit as st

        chamadas = []
        monkeypatch.setattr(st, "info", lambda *a, **k: chamadas.append("info"))
        monkeypatch.setattr(st, "dataframe", lambda *a, **k: chamadas.append("df"))
        monkeypatch.setattr(st, "download_button", lambda *a, **k: chamadas.append("dl"))

        from dashboard.ui import tabela_exportavel

        tabela_exportavel(pd.DataFrame(), nome_arquivo="vazio")
        assert "info" in chamadas
        assert "df" not in chamadas

    def test_tabela_com_dados_gera_csv(self, monkeypatch):
        """Com dados, `tabela_exportavel` renderiza dataframe e botões."""
        import streamlit as st

        chamadas = []
        monkeypatch.setattr(st, "info", lambda *a, **k: chamadas.append("info"))
        monkeypatch.setattr(st, "dataframe", lambda *a, **k: chamadas.append("df"))
        monkeypatch.setattr(
            st, "download_button",
            lambda *a, **k: chamadas.append("download"),
        )

        from dashboard.ui import tabela_exportavel

        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        tabela_exportavel(df, nome_arquivo="dados")
        assert "df" in chamadas
        # Default: CSV + Excel + PDF (RF-08, formatos de config/dashboard.yaml)
        assert chamadas.count("download") == 3


class TestFormatarMoedaCompacto:
    """Sprint 19: faixas tri/bi/mi/mil (10^9 = bilhão em pt-BR)."""

    def test_nulo_vira_travessao(self):
        assert formatar_moeda_compacto(None) == "—"

    def test_bilhao(self):
        assert formatar_moeda_compacto(1038541771.85) == "R$ 1,04 bi"

    def test_trilhao(self):
        assert formatar_moeda_compacto(2_500_000_000_000) == "R$ 2,50 tri"

    def test_milhao(self):
        assert formatar_moeda_compacto(531600) == "R$ 531,6 mil"

    def test_abaixo_de_mil(self):
        assert formatar_moeda_compacto(900) == "R$ 900,00"


class TestNumSeguro:
    """Sprint 19: scores/métricas None viram 0.0 (sem TypeError)."""

    def test_none_vira_zero(self):
        assert num_seguro(None) == 0.0

    def test_numero_passa(self):
        assert num_seguro(1.5) == 1.5

    def test_texto_invalido_vira_zero(self):
        assert num_seguro("abc") == 0.0


class TestAnosDeJanela:
    """Sprint 19.5: base da média anual da Batalha."""

    def test_janela_completa(self):
        assert anos_de_janela("2015-02", "2026-08") == 12

    def test_mesmo_ano(self):
        assert anos_de_janela("2019-01", "2019-12") == 1

    def test_janela_parcial(self):
        assert anos_de_janela("2020-01", "2022-12") == 3

    def test_none_vira_um(self):
        assert anos_de_janela(None, None) == 1
        assert anos_de_janela("abc", None) == 1
