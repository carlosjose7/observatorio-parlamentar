"""dashboard/pages/12_batalha.py — comparativo entre dois parlamentares.

Feature estilo 'tudocelular compare' (Sprint 12): dois parlamentares
lado a lado com métricas comparativas, radar de risco duplo e
comparabilidade de período (ADR-040).

Consome `GET /parlamentares` (busca) e `GET /agent/parlamentar/{id}`
(ADR-032) para cada parlamentar selecionado.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.charts import radar_risco
from dashboard.client import ApiClient
from dashboard.comparacao import calcular_sobreposicao
from dashboard.ui import (
    aplicar_identidade,
    avatar_parlamentar,
    botao_voltar,
    carregar_com_feedback,
    formatar_moeda,
    tabela_exportavel,
)

st.set_page_config(page_title="Batalha Parlamentar", page_icon="⚔️", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("⚔️ Batalha Parlamentar")
st.caption("Comparativo lado a lado de dois parlamentares — métricas, risco e despesas.")

client = ApiClient()


def _buscar_parlamentar(posicao: str) -> dict | None:
    """Sidebar de busca + seletor para um lado da batalha."""
    with st.sidebar:
        st.subheader(f"Parlamentar {posicao}")
        nome = st.text_input("Nome", key=f"bat_{posicao}_nome")
        uf = st.text_input("UF (2 letras)", max_chars=2, key=f"bat_{posicao}_uf")
        partido = st.text_input("Partido (sigla)", key=f"bat_{posicao}_partido")
        buscar = st.button("Buscar", key=f"bat_{posicao}_buscar")

    chave_lista = f"bat_{posicao}_lista"
    chave_sel = f"bat_{posicao}_sel"

    if buscar:
        payload = carregar_com_feedback(
            lambda: client.listar_parlamentares(
                nome=nome or None, uf=uf or None, partido=partido or None,
                limite=100,
            ),
            spinner=f"Buscando parlamentares ({posicao})...",
        )
        st.session_state[chave_lista] = payload
        st.session_state[chave_sel] = None

    payload = st.session_state.get(chave_lista)
    if not payload:
        return None

    itens = payload.get("itens", [])
    if not itens:
        st.warning(f"Nenhum parlamentar encontrado para {posicao}.")
        return None

    opcoes = {
        f"{i['nome']} ({i['sigla_partido']}-{i['sigla_uf']})": i["id_parlamentar"]
        for i in itens
    }
    sel = st.selectbox(f"Parlamentar {posicao}", list(opcoes.keys()), key=chave_sel)
    if sel is None:
        return None
    return next(i for i in itens if i["id_parlamentar"] == opcoes[sel])


def _carregar_agente(id_parlamentar: int) -> dict | None:
    """Carrega o payload agent de um parlamentar."""
    return carregar_com_feedback(
        lambda: client.agent_parlamentar(id_parlamentar),
        spinner="Carregando dados...",
    )


def _render_perfil_lateral(label: str, agente: dict) -> None:
    """Perfil compacto de um parlamentar (coluna)."""
    avatar_parlamentar(agente.get("url_foto"), nome=agente.get("nome", ""), tamanho="sm")
    st.markdown(f"### {label}")
    c1, c2 = st.columns(2)
    c1.metric("Partido", agente.get("sigla_partido"))
    c2.metric("UF", agente.get("sigla_uf"))
    st.caption(
        f"Fonte: {agente.get('fonte')} · "
        f"Desde: {agente.get('periodo_vigente_desde', '—')}"
    )


def _render_metricasComparativas(
    metricas_a: dict, metricas_b: dict, nome_a: str, nome_b: str
) -> None:
    """Métricas lado a lado em colunas."""
    st.markdown("### Métricas")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown(f"**{nome_a}**")
        st.metric("Total gasto", formatar_moeda(metricas_a.get("total_gasto")))
        st.metric("Transações", metricas_a.get("num_transacoes"))
        st.metric("Fornecedores", metricas_a.get("num_fornecedores"))
        hhi_a = metricas_a.get("hhi_recente")
        st.metric("HHI recente", f"{hhi_a:.3f}" if hhi_a is not None else "—")

    with col_b:
        st.markdown(f"**{nome_b}**")
        st.metric("Total gasto", formatar_moeda(metricas_b.get("total_gasto")))
        st.metric("Transações", metricas_b.get("num_transacoes"))
        st.metric("Fornecedores", metricas_b.get("num_fornecedores"))
        hhi_b = metricas_b.get("hhi_recente")
        st.metric("HHI recente", f"{hhi_b:.3f}" if hhi_b is not None else "—")


def _render_radar_duplo(risco_a: dict | None, risco_b: dict | None) -> None:
    """Radar de risco com ambos os parlamentares sobrepostos."""
    if not risco_a and not risco_b:
        st.info("Sem scores de risco disponíveis para comparação.")
        return

    dimensoes = [
        "supplier_concentration_score",
        "political_exposure_score",
        "supplier_dependency_score",
        "expense_anomaly_score",
        "network_influence_score",
    ]
    labels = [d.replace("_score", "").replace("_", " ").title() for d in dimensoes]

    import plotly.graph_objects as go

    fig = go.Figure()
    if risco_a:
        vals_a = [risco_a.get(d, 0) for d in dimensoes]
        fig.add_trace(go.Scatterpolar(
            r=vals_a + [vals_a[0]],
            theta=labels + [labels[0]],
            fill="toself",
            fillcolor="#187A52",
            opacity=0.2,
            line=dict(color="#187A52", width=2),
            name="A",
            hovertemplate="%{theta}: %{r:.3f}<extra>A</extra>",
        ))
    if risco_b:
        vals_b = [risco_b.get(d, 0) for d in dimensoes]
        fig.add_trace(go.Scatterpolar(
            r=vals_b + [vals_b[0]],
            theta=labels + [labels[0]],
            fill="toself",
            fillcolor="#0B1F33",
            opacity=0.15,
            line=dict(color="#0B1F33", width=2),
            name="B",
            hovertemplate="%{theta}: %{r:.3f}<extra>B</extra>",
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], showticklabels=False),
            angularaxis=dict(
                tickfont=dict(size=10, family="IBM Plex Mono, monospace"),
            ),
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.15,
            xanchor="center",
            x=0.5,
        ),
        margin=dict(l=40, r=40, t=30, b=40),
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_risk_index(risco_a: dict | None, risco_b: dict | None) -> None:
    """Risk index comparativo com barras de progresso."""
    st.markdown("### Risk Index")
    c1, c2 = st.columns(2)
    with c1:
        idx_a = risco_a.get("risk_index", 0) if risco_a else 0
        st.progress(min(1.0, idx_a), text=f"Parlamentar A: {idx_a:.3f}")
    with c2:
        idx_b = risco_b.get("risk_index", 0) if risco_b else 0
        st.progress(min(1.0, idx_b), text=f"Parlamentar B: {idx_b:.3f}")


def _render_anomalias(anom_a: dict, anom_b: dict) -> None:
    """Comparação de anomalias."""
    st.markdown("### Anomalias")
    c1, c2 = st.columns(2)
    with c1:
        st.metric(
            "Despesas anômalas",
            anom_a.get("num_despesas_anomalas", 0),
            delta=f"{anom_a.get('proporcao', 0):.1%}" if anom_a.get("proporcao") else None,
        )
    with c2:
        st.metric(
            "Despesas anômalas",
            anom_b.get("num_despesas_anomalas", 0),
            delta=f"{anom_b.get('proporcao', 0):.1%}" if anom_b.get("proporcao") else None,
        )


def _render_top_fornecedores(top_a: list, top_b: list) -> None:
    """Top 5 fornecedores lado a lado."""
    st.markdown("### Top 5 Fornecedores")
    col_a, col_b = st.columns(2)

    with col_a:
        if top_a:
            df = pd.DataFrame(top_a)[["nome_fornecedor", "total_gasto", "num_transacoes"]]
            df = df.rename(columns={
                "nome_fornecedor": "Fornecedor",
                "total_gasto": "Total",
                "num_transacoes": "Transações",
            })
            df["Total"] = df["Total"].map(formatar_moeda)
            st.dataframe(df, hide_index=True)
        else:
            st.info("Sem dados de fornecedores.")

    with col_b:
        if top_b:
            df = pd.DataFrame(top_b)[["nome_fornecedor", "total_gasto", "num_transacoes"]]
            df = df.rename(columns={
                "nome_fornecedor": "Fornecedor",
                "total_gasto": "Total",
                "num_transacoes": "Transações",
            })
            df["Total"] = df["Total"].map(formatar_moeda)
            st.dataframe(df, hide_index=True)
        else:
            st.info("Sem dados de fornecedores.")


def main() -> None:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Configurar batalha")

    par_a = _buscar_parlamentar("A")
    par_b = _buscar_parlamentar("B")

    if par_a is None or par_b is None:
        st.info("Selecione dois parlamentares para comparar.")
        return

    if par_a["id_parlamentar"] == par_b["id_parlamentar"]:
        st.warning("Selecione dois parlamentares diferentes.")
        return

    st.divider()

    # Carregar dados de ambos
    agente_a = _carregar_agente(par_a["id_parlamentar"])
    agente_b = _carregar_agente(par_b["id_parlamentar"])

    if agente_a is None or agente_b is None:
        st.error("Não foi possível carregar os dados de um dos parlamentares.")
        return

    # Cabeçalho com perfis
    col_perfil_a, col_perfil_b = st.columns(2)
    with col_perfil_a:
        _render_perfil_lateral(
            f"{agente_a['nome']} ({agente_a.get('sigla_partido')}-{agente_a.get('sigla_uf')})",
            agente_a,
        )
    with col_perfil_b:
        _render_perfil_lateral(
            f"{agente_b['nome']} ({agente_b.get('sigla_partido')}-{agente_b.get('sigla_uf')})",
            agente_b,
        )

    # Comparabilidade de período
    sobreposicao = calcular_sobreposicao(
        agente_a.get("janela_inicio"),
        agente_a.get("janela_fim"),
        agente_b.get("janela_inicio"),
        agente_b.get("janela_fim"),
    )

    if sobreposicao.inicio_comum and sobreposicao.fim_comum:
        st.caption(
            f"Período comum: **{sobreposicao.inicio_comum} a {sobreposicao.fim_comum}** "
            f"({sobreposicao.pct_cobertura:.0%} de cobertura do menor mandato)"
        )

    if (
        sobreposicao.pct_cobertura < 0.75
        and sobreposicao.inicio_comum is not None
    ):
        st.warning(
            "⚠ Os parlamentares têm períodos de mandato distintos "
            f"(A: {sobreposicao.inicio_a}–{sobreposicao.fim_a}, "
            f"B: {sobreposicao.inicio_b}–{sobreposicao.fim_b}) — "
            "valores totais não são diretamente comparáveis. "
            "Veja as métricas abaixo para uma comparação contextual."
        )

    st.divider()

    # Métricas comparativas
    _render_metricasComparativas(
        agente_a.get("metricas", {}),
        agente_b.get("metricas", {}),
        agente_a["nome"],
        agente_b["nome"],
    )

    st.divider()

    # Radar de risco duplo
    st.markdown("### Scores de Risco")
    _render_radar_duplo(agente_a.get("risco"), agente_b.get("risco"))
    _render_risk_index(agente_a.get("risco"), agente_b.get("risco"))

    st.divider()

    # Anomalias
    _render_anomalias(
        agente_a.get("anomalias", {}),
        agente_b.get("anomalias", {}),
    )

    st.divider()

    # Top fornecedores
    _render_top_fornecedores(
        agente_a.get("top_fornecedores", []),
        agente_b.get("top_fornecedores", []),
    )


main()
