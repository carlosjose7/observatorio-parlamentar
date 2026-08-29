"""dashboard/pages/09_qualidade.py — Data Quality Report do Gold.

Consome `GET /qualidade/relatorio` (ADR-033/Sprint 7 reserva desta página):
linhas do DQ report por tabela, com total/válidos/quarentena/deduplicados,
regras violadas e % nulos. Exportação (RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import (
    aplicar_identidade,
    botao_voltar,
    carregar_com_feedback,
    tabela_exportavel,
)

st.set_page_config(page_title="Qualidade", page_icon="✅", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("✅ Data Quality Report")

client = ApiClient()


def main() -> None:
    payload = carregar_com_feedback(
        lambda: client.relatorio_qualidade(limite=100),
        spinner="Carregando relatório de qualidade...",
    )
    if payload is None:
        return
    itens = payload.get("itens", [])
    if not itens:
        st.info("Nenhuma linha de Data Quality Report registrada.")
        return

    df = pd.DataFrame(itens)
    df["regras_violadas"] = df["regras_violadas"].map(lambda r: ", ".join(r) if r else "—")
    df = df[
        ["tabela", "run_id", "total_registros", "registros_validos",
         "registros_quarentena", "registros_deduplicados",
         "percentual_nulos_criticos", "regras_violadas", "execution_timestamp"]
    ].rename(
        columns={
            "tabela": "Tabela",
            "run_id": "Run",
            "total_registros": "Total",
            "registros_validos": "Válidos",
            "registros_quarentena": "Quarentena",
            "registros_deduplicados": "Dedup",
            "percentual_nulos_criticos": "% Nulos críticos",
            "regras_violadas": "Regras violadas",
            "execution_timestamp": "Execução",
        }
    )

    # Resumo por tabela (última execução)
    st.markdown("### Resumo por tabela")
    resumo = (
        df.groupby("Tabela")
        .last()[["Total", "Válidos", "Quarentena", "Dedup"]]
        .sort_values("Total", ascending=False)
    )
    resumo["% Válidos"] = (resumo["Válidos"] / resumo["Total"] * 100).round(1)
    st.dataframe(resumo)

    st.markdown(f"### Detalhe ({len(df)} linhas)")
    tabela_exportavel(df, nome_arquivo="data_quality_report")


main()
