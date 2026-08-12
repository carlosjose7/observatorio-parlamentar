# tests/dashboard/test_ui.py
"""Testes dos utilitários de UI do dashboard (dashboard/ui.py, Sprint 7).

Cobre o formatador de moeda pt-BR e o comportamento de `tabela_exportavel`
quando o DataFrame está vazio (estado amigável, RF-08).
"""

from __future__ import annotations

import pandas as pd

from dashboard.ui import formatar_moeda


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
