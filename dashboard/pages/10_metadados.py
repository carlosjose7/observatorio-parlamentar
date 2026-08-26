"""dashboard/pages/10_metadados.py — catálogo, versões e execuções.

Consome `GET /pipeline/status` (RF-12) e `GET /qualidade/relatorio`
(metadados de qualidade). Documenta as fontes e o versionamento das
execuções. Exportação (RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import aplicar_identidade, carregar_com_feedback, tabela_exportavel

st.set_page_config(page_title="Metadados", page_icon="📚", layout="wide")
aplicar_identidade()
st.title("📚 Metadados e Versionamento")

client = ApiClient()

_FONTES = [
    ("Câmara dos Deputados", "Despesas de deputados federais (CEAP)", "incremental por mês de competência"),
    ("Senado Federal", "Despesas de senadores (CEAPS)", "CSV anual completo"),
    ("Portal da Transparência (CGU)", "Emendas parlamentares", "incremental por ano"),
    ("Portal da Transparência (CGU)", "Cartões CPGF", "incremental por mês de extrato"),
]


def _fontes() -> None:
    st.subheader("Catálogo de fontes")
    st.table(
        pd.DataFrame(_FONTES, columns=["Fonte", "Dado", "Estratégia de extração"])
    )


def _execucoes() -> None:
    st.subheader("Execuções do pipeline (RF-12)")
    payload = carregar_com_feedback(
        lambda: client.status_pipeline(limite=100),
        spinner="Carregando execuções...",
    )
    if payload is None:
        return
    itens = payload.get("itens", [])
    if not itens:
        st.info("Nenhuma execução registrada.")
        return
    df = pd.DataFrame(itens)
    df["fontes_com_erro"] = df["fontes_com_erro"].map(
        lambda f: ", ".join(f) if f else "—"
    )
    df = df[
        ["run_id", "pipeline_version", "execution_timestamp", "status",
         "fontes_com_erro", "watermark_camara", "watermark_senado",
         "watermark_cgu_emenda", "watermark_cgu_cartao"]
    ].rename(
        columns={
            "run_id": "Run",
            "pipeline_version": "Versão",
            "execution_timestamp": "Execução",
            "status": "Status",
            "fontes_com_erro": "Fontes com erro",
            "watermark_camara": "Watermark Câmara",
            "watermark_senado": "Watermark Senado",
            "watermark_cgu_emenda": "Watermark Emendas",
            "watermark_cgu_cartao": "Watermark Cartões",
        }
    )
    tabela_exportavel(df, nome_arquivo="pipeline_runs")


def main() -> None:
    _fontes()
    st.divider()
    _execucoes()


main()
