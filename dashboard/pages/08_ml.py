"""dashboard/pages/08_ml.py — scores de risco e anomalias ML (agent-ready).

Consome `GET /parlamentares` (busca por nome/UF/partido) e
`GET /agent/parlamentar/{id}` (ADR-032): métricas, scores de risco
(ADR-029) e anomalias de um parlamentar, com top fornecedores. Exportação
(RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.charts import radar_risco
from dashboard.client import ApiClient
from dashboard.ui import (
    aplicar_identidade,
    botao_voltar,
    carregar_com_feedback,
    formatar_moeda,
    tabela_exportavel,
)

st.set_page_config(page_title="ML / Risco", page_icon="🧠", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("🧠 Scores de Risco (agent-ready)")

client = ApiClient()


def _selecionar_parlamentar() -> dict | None:
    """Filtros de busca + seletor de parlamentar (side effect: session_state)."""
    with st.sidebar:
        st.subheader("Buscar parlamentar")
        nome = st.text_input("Nome", key="ml_nome")
        uf = st.text_input("UF (2 letras)", max_chars=2, key="ml_uf")
        partido = st.text_input("Partido (sigla)", key="ml_partido")
        buscar = st.button("Buscar", key="ml_buscar")

    if not buscar and "ml_lista" not in st.session_state:
        st.info("Use a busca na barra lateral para localizar um parlamentar.")
        return None

    if buscar:
        payload = carregar_com_feedback(
            lambda: client.listar_parlamentares(
                nome=nome or None, uf=uf or None, partido=partido or None,
                limite=100,
            ),
            spinner="Buscando parlamentares...",
        )
        st.session_state["ml_lista"] = payload
        st.session_state["ml_sel"] = None

    payload = st.session_state.get("ml_lista")
    if not payload:
        return None

    itens = payload.get("itens", [])
    if not itens:
        st.warning("Nenhum parlamentar encontrado com os filtros informados.")
        return None

    opcoes = {
        f"{i['nome']} ({i['sigla_partido']}-{i['sigla_uf']})": i["id_parlamentar"]
        for i in itens
    }
    sel = st.selectbox("Parlamentar", list(opcoes.keys()), key="ml_sel")
    if sel is None:
        return None
    return next(i for i in itens if i["id_parlamentar"] == opcoes[sel])


def _radar(risco: dict) -> None:
    """Gráfico de radar com os 5 scores de risco (ADR-029/038)."""
    dimensoes = [
        "supplier_concentration_score",
        "political_exposure_score",
        "supplier_dependency_score",
        "expense_anomaly_score",
        "network_influence_score",
    ]
    scores = {d: risco.get(d, 0) for d in dimensoes}
    radar_risco(scores)


def _render(id_parlamentar: int) -> None:
    payload = carregar_com_feedback(
        lambda: client.agent_parlamentar(id_parlamentar),
        spinner="Carregando perfil de risco...",
    )
    if payload is None:
        return

    st.markdown(f"## {payload.get('nome')} ({payload.get('sigla_partido')}-{payload.get('sigla_uf')})")

    janela_ini, janela_fim = payload.get("janela_inicio"), payload.get("janela_fim")
    if janela_ini and janela_fim:
        st.caption(
            f"Janela analisada (camada Gold): **{janela_ini} a {janela_fim}** — as "
            "métricas refletem apenas as despesas carregadas nesse período; "
            "podem divergir do CEAP completo do exercício."
        )

    metricas = payload.get("metricas", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total gasto", formatar_moeda(metricas.get("total_gasto")))
    c2.metric("Transações", metricas.get("num_transacoes"))
    c3.metric("Fornecedores", metricas.get("num_fornecedores"))
    c4.metric("HHI recente", f"{metricas.get('hhi_recente', 0):.3f}")

    risco = payload.get("risco")
    if risco:
        st.markdown("### Scores de risco")
        c1, c2 = st.columns(2)
        with c1:
            _radar(risco)
        with c2:
            st.metric("Risk Index", f"{risco.get('risk_index', 0):.3f}")
            for d, nome in [
                ("supplier_concentration_score", "Concentração de fornecedores"),
                ("political_exposure_score", "Exposição política"),
                ("supplier_dependency_score", "Dependência de fornecedor"),
                ("expense_anomaly_score", "Anomalia de despesa"),
                ("network_influence_score", "Influência na rede"),
            ]:
                st.progress(min(1.0, risco.get(d, 0)), text=f"{nome}: {risco.get(d, 0):.2f}")

    anomalias = payload.get("anomalias", {})
    st.markdown(
        f"**Anomalias:** {anomalias.get('num_despesas_anomalas', 0)} despesas "
        f"({anomalias.get('proporcao', 0):.1%})"
    )

    top = payload.get("top_fornecedores", [])
    if top:
        st.markdown("### Top fornecedores")
        df = pd.DataFrame(top)[
            ["nome_fornecedor", "total_gasto", "num_transacoes"]
        ].rename(
            columns={
                "nome_fornecedor": "Fornecedor",
                "total_gasto": "Total",
                "num_transacoes": "Transações",
            }
        )
        df["Total"] = df["Total"].map(formatar_moeda)
        tabela_exportavel(df, nome_arquivo=f"risco_{id_parlamentar}")


def main() -> None:
    parlamentar = _selecionar_parlamentar()
    if parlamentar is None:
        return
    st.divider()
    _render(parlamentar["id_parlamentar"])


main()
