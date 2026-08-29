"""dashboard/pages/07_anomalias.py — anomalias de despesa.

Consome `GET /anomalias` (lista paginada de despesas anômalas, ADR-002) e
`GET /agent/anomalias` (agregados). Permite filtrar por threshold de zscore
e exportar (RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.charts import barras_vert
from dashboard.client import ApiClient
from dashboard.ui import (
    aplicar_identidade,
    botao_voltar,
    carregar_com_feedback,
    formatar_moeda,
    tabela_exportavel,
)

st.set_page_config(page_title="Anomalias", page_icon="🚨", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("🚨 Anomalias de Despesa")

client = ApiClient()

_CRITERIOS = [
    "criterio_zscore",
    "criterio_if",
    "criterio_fornecedor_poucos_clientes",
    "criterio_empresa_nova",
    "criterio_valores_identicos",
    "criterio_dia_sem_sessao",
]


def _agregados() -> None:
    """Agregados de anomalias (por ano e por critério)."""
    payload = carregar_com_feedback(
        client.agent_anomalias,
        spinner="Carregando agregados...",
    )
    if payload is None:
        return
    st.markdown(f"**{payload.get('total', 0)} despesas anômalas**")

    por_ano = payload.get("por_ano", [])
    if por_ano:
        st.session_state["anomalias_anos"] = sorted(
            int(a["ano"]) for a in por_ano
        )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Por ano**")
        por_ano = payload.get("por_ano", [])
        if por_ano:
            df_ano = pd.DataFrame(por_ano).rename(
                columns={"ano": "Ano", "quantidade": "Quantidade"}
            )
            barras_vert(df_ano, "Ano", "Quantidade", "Por ano")
        else:
            st.info("Sem dados por ano.")
    with c2:
        st.markdown("**Por critério**")
        por_criterio = payload.get("por_criterio", [])
        if por_criterio:
            df_crit = pd.DataFrame(por_criterio).rename(
                columns={"criterio": "Critério", "quantidade": "Quantidade"}
            )
            barras_vert(df_crit, "Critério", "Quantidade", "Por critério")
        else:
            st.info("Sem dados por critério.")


def _lista(threshold: float | None, ano: int | None) -> None:
    payload = carregar_com_feedback(
        lambda: client.listar_anomalias(
            threshold=threshold, ano=ano, limite=100
        ),
        spinner="Carregando anomalias...",
    )
    if payload is None:
        return
    itens = payload.get("itens", [])
    if not itens:
        st.info("Nenhuma anomalia para os filtros atuais.")
        return

    df = pd.DataFrame(itens)
    df["data_sk"] = pd.to_datetime(df["data_sk"].astype(str), format="%Y%m%d").dt.strftime("%d/%m/%Y")
    df["valor_liquido"] = df["valor_liquido"].map(formatar_moeda)
    df["num_criterios_atendidos"] = df[_CRITERIOS].sum(axis=1)
    df["nome"] = df["nome"].fillna("—")
    df["sigla_partido"] = df["sigla_partido"].fillna("—")
    df["sigla_uf"] = df["sigla_uf"].fillna("—")
    colunas = [
        "nome", "sigla_partido", "sigla_uf", "data_sk",
        "valor_liquido", "zscore", "num_criterios_atendidos",
    ]
    df = df[colunas].rename(
        columns={
            "nome": "Parlamentar",
            "sigla_partido": "Partido",
            "sigla_uf": "UF",
            "data_sk": "Data",
            "valor_liquido": "Valor",
            "zscore": "Z-score",
            "num_criterios_atendidos": "Critérios",
        }
    )
    tabela_exportavel(df, nome_arquivo="anomalias")


def main() -> None:
    _agregados()
    st.divider()
    st.subheader("Lista de anomalias")

    anos = st.session_state.get("anomalias_anos", [])
    col_ano, col_threshold = st.columns(2)
    with col_ano:
        escolha_ano = st.selectbox(
            "Ano do documento",
            ["Todos"] + [str(a) for a in anos],
        )
    with col_threshold:
        threshold = st.slider(
            "Threshold de z-score",
            min_value=0.0, max_value=10.0, value=0.0, step=0.1,
        )
    _lista(
        threshold if threshold > 0 else None,
        int(escolha_ano) if escolha_ano != "Todos" else None,
    )


main()
