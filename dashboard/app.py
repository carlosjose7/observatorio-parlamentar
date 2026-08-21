"""dashboard/app.py — página inicial (Visão Geral) do Observatório Parlamentar.

Página 01 do Sprint 7: KPIs globais (parlamentares, fornecedores, despesas,
cartões), períodos com dados e status dos serviços. Todos os dados vêm da
API REST via `dashboard/client.py` (RF-05, ADR-026) — o dashboard nunca abre
o DuckDB diretamente.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import (
    carregar_com_feedback,
    formatar_moeda,
    metricas_seguras,
)

st.set_page_config(
    page_title="Observatório Parlamentar",
    page_icon="🏛️",
    layout="wide",
)

st.title("🏛️ Observatório Parlamentar")
st.caption("Plataforma de Inteligência Parlamentar Brasileira")

client = ApiClient()


def _render_status_servicos(contexto: dict) -> None:
    """Linha de métricas com o estado dos serviços."""
    st.markdown("### Status dos Serviços")
    col1, col2, col3 = st.columns(3)
    pipeline = (contexto.get("pipeline") or {})
    col1.metric("API", "🟢 Online")
    if pipeline.get("run_id"):
        col2.metric("Pipeline", f"{pipeline.get('status', '—')} · {pipeline.get('run_id', '')[:8]}")
    else:
        col2.metric("Pipeline", "⏳ Sem execução")
    qualidade = contexto.get("qualidade") or {}
    col3.metric("DQ Report", f"{qualidade.get('tabelas_reportadas', 0)} tabelas")


def _render_kpis(contexto: dict) -> None:
    """KPIs globais de gastos, parlamentares, fornecedores e anomalias."""
    metricas = contexto.get("metricas_globais") or {}
    st.markdown("### Panorama")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        metricas_seguras("Total Gasto", formatar_moeda(metricas.get("total_gasto")))
    with c2:
        metricas_seguras("Transações", metricas.get("num_transacoes"))
    with c3:
        metricas_seguras("Fornecedores", metricas.get("num_fornecedores"))
    with c4:
        metricas_seguras("Parlamentares", metricas.get("num_parlamentares"))
    with c5:
        metricas_seguras("Anomalias", metricas.get("num_anomalias"))


def _render_periodos(contexto: dict) -> None:
    """Períodos com dados disponíveis."""
    periodos = contexto.get("periodos_com_dados") or []
    if periodos:
        st.markdown("### Períodos com dados")
        st.write(" ".join(str(p) for p in sorted(periodos)))
    else:
        st.info("Nenhum período com dados ainda — rode o pipeline (Sprint 6.5).")


def _render_execucoes_recentes(client: ApiClient) -> None:
    """Tabela das execuções recentes do pipeline (RF-12)."""
    st.markdown("### Execuções recentes do pipeline")
    payload = client.status_pipeline(limite=10)
    itens = payload.get("itens", [])
    if not itens:
        st.info("Nenhuma execução registrada.")
        return
    df = pd.DataFrame(itens)[
        ["run_id", "status", "execution_timestamp", "pipeline_version"]
    ]
    df = df.rename(
        columns={
            "run_id": "Run",
            "status": "Status",
            "execution_timestamp": "Execução",
            "pipeline_version": "Versão",
        }
    )
    st.dataframe(df)


def main() -> None:
    contexto = st.session_state.get("contexto")
    if contexto is None:
        contexto = st.session_state["contexto"] = carregar_com_feedback(
            client.agent_context, spinner="Carregando panorama..."
        )
    if contexto is None:
        st.stop()
    _render_status_servicos(contexto)
    _render_kpis(contexto)
    _render_periodos(contexto)
    _render_execucoes_recentes(client)

    st.markdown("---")
    st.info("Navegue pelas páginas no menu lateral para explorar os dados.")


main()
