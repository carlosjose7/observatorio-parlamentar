"""dashboard/charts.py — builders de gráficos tematizados (Sprint 11).

Single source of truth para gráficos estatísticos do dashboard.
Altair para rankings, séries temporais e barras (padrão estatístico).
Plotly para radar de risco e grafo de rede interativo (ADR-038).

Todas as funções recebem DataFrames prontos e retornam figuras renderizáveis
via `st.altair_chart` ou `st.plotly_chart`. Nenhuma chamada de API aqui —
o dado vem pronto das páginas.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.theme import GOLD, GREEN, LINE, MUTED, NAVY, WHITE

# ---------------------------------------------------------------------------
# Altair — builders de gráficos estatísticos
# ---------------------------------------------------------------------------


def _estilo_altair(chart: alt.Chart) -> alt.Chart:
    """Aplica identidade visual a um gráfico Altair (fonte, grade, eixos)."""
    return (
        chart.configure(font="'DM Sans', sans-serif")
        .configure_axis(
            labelColor=MUTED,
            titleColor=MUTED,
            labelFontSize=12,
            titleFontSize=12,
            grid=True,
            gridColor=LINE,
            gridOpacity=0.6,
        )
        .configure_view(stroke=None)
    )


def barras_ranking(
    df: pd.DataFrame,
    col_rotulo: str,
    col_valor: str,
    titulo_eixo: str = "Total (R$)",
    *,
    destaque: bool = True,
    altura: int = 380,
) -> alt.Chart:
    """Barras horizontais ordenadas por valor (maior no topo).

    Quando ``destaque=True``, o primeiro item (líder) fica verde;
    os demais ficam navy.

    Args:
        df: DataFrame com pelo menos ``col_rotulo`` e ``col_valor``.
        col_rotulo: Nome da coluna de rótulos (eixo Y).
        col_valor: Nome da coluna de valores (eixo X), numérico.
        titulo_eixo: Rótulo do eixo X.
        destaque: Se True, líder fica verde.
        altura: Altura do gráfico em pixels.
    """
    if df.empty:
        return alt.Chart(pd.DataFrame()).mark_text()

    tmp = df.copy()
    tmp["__rank"] = range(len(tmp))
    tmp["__lider"] = tmp["__rank"] == 0

    color_condition = (
        alt.condition("datum.__lider", alt.value(GREEN), alt.value(NAVY))
        if destaque
        else alt.value(NAVY)
    )

    chart = alt.Chart(tmp).mark_bar().encode(
        x=alt.X(
            f"{col_valor}:Q",
            title=titulo_eixo,
            axis=alt.Axis(format=",.0f"),
        ),
        y=alt.Y(
            f"{col_rotulo}:N",
            sort="-x",
            title=None,
        ),
        color=color_condition if destaque else alt.value(NAVY),
        tooltip=[
            alt.Tooltip(f"{col_rotulo}:N", title="Recorte"),
            alt.Tooltip(
                f"{col_valor}:Q",
                title="Total",
                format=",.0f",
            ),
        ],
    ).properties(height=altura, width="container")

    return _estilo_altair(chart)


def serie_mensal(
    df: pd.DataFrame,
    col_periodo: str,
    col_valor: str,
    titulo_eixo_y: str = "Total (R$)",
    *,
    cor: str = NAVY,
    altura: int = 320,
) -> alt.Chart:
    """Barras verticais de série temporal (AAAAMM).

    Args:
        df: DataFrame com ``col_periodo`` (categórico) e ``col_valor`` (numérico).
        col_periodo: Coluna do período (eixo X).
        col_valor: Coluna de valores (eixo Y).
        titulo_eixo_y: Rótulo do eixo Y.
        cor: Cor das barras.
        altura: Altura em pixels.
    """
    if df.empty:
        return alt.Chart(pd.DataFrame()).mark_text()

    chart = alt.Chart(df).mark_bar(color=cor).encode(
        x=alt.X(
            f"{col_periodo}:N",
            title="Mês (AAAAMM)",
            sort=None,
        ),
        y=alt.Y(
            f"{col_valor}:Q",
            title=titulo_eixo_y,
            axis=alt.Axis(format=",.0f"),
        ),
        tooltip=[
            alt.Tooltip(f"{col_periodo}:N", title="Mês"),
            alt.Tooltip(f"{col_valor}:Q", title="Total", format=",.0f"),
        ],
    ).properties(height=altura, width="container")

    return _estilo_altair(chart)


def barras_vert(
    df: pd.DataFrame,
    col_rotulo: str,
    col_valor: str,
    titulo: str = "",
    *,
    cor: str = NAVY,
    altura: int = 300,
) -> None:
    """Barras verticais genéricas (agregados por critério, ano, etc.).

    Usa Altair ``mark_bar`` com orientação vertical — respeita a paleta
    e evita ``st.bar_chart`` default (ADR-038).
    """
    if df.empty:
        st.info("Sem dados para exibir.")
        return
    if titulo:
        st.markdown(f"**{titulo}**")
    chart = (
        alt.Chart(df)
        .mark_bar(color=cor)
        .encode(
            x=alt.X(f"{col_rotulo}:N", title=None, sort=None),
            y=alt.Y(f"{col_valor}:Q", title="Quantidade", axis=alt.Axis(format=",.0f")),
            tooltip=[
                alt.Tooltip(f"{col_rotulo}:N", title="Categoria"),
                alt.Tooltip(f"{col_valor}:Q", title="Quantidade", format=",d"),
            ],
        )
        .properties(height=altura, width="container")
    )
    st.altair_chart(_estilo_altair(chart), use_container_width=True)


# ---------------------------------------------------------------------------
# Plotly — radar de risco e grafo de rede
# ---------------------------------------------------------------------------


def radar_risco(
    scores: dict[str, float],
    *,
    cor: str = GREEN,
    titulo: str = "",
) -> None:
    """Gráfico de radar (polar) com scores de risco (ADR-029/038).

    Cada chave de ``scores`` vira uma dimensão. Valores devem estar
    na faixa [0, 1].

    Args:
        scores: Dict {nome_dimensao: valor_float}.
        cor: Cor da linha e preenchimento.
        titulo: Título opcional do gráfico.
    """
    if not scores:
        st.info("Sem scores de risco para exibir.")
        return

    dimensoes = list(scores.keys())
    valores = list(scores.values())
    labels = [d.replace("_score", "").replace("_", " ").title() for d in dimensoes]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=valores + [valores[0]],
        theta=labels + [labels[0]],
        fill="toself",
        fillcolor=cor,
        opacity=0.25,
        line=dict(color=cor, width=2),
        hovertemplate="%{theta}: %{r:.3f}<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], showticklabels=False),
            angularaxis=dict(
                tickfont=dict(size=10, family="IBM Plex Mono, monospace"),
            ),
        ),
        showlegend=False,
        margin=dict(l=40, r=40, t=30, b=30),
        height=400,
    )
    if titulo:
        fig.update_layout(title=dict(text=titulo, x=0.5, font=dict(size=14)))
    st.plotly_chart(fig, use_container_width=True)


def grafo_rede(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    *,
    node_colors: dict[str, str] | None = None,
    titulo: str = "",
) -> None:
    """Grafo interativo de rede (hover/zoom/pan) via Plotly (ADR-038).

    Layout computado por NetworkX (spring); renderização 100% Plotly.
    O grafo permanece sobre ``network_nodes``/``network_edges``
    materializados (ADR-030 — zero recálculo, Gate 3 preservado).

    Args:
        nodes: DataFrame com ``id``, ``label``, ``tipo``.
        edges: DataFrame com ``source``, ``target``, ``weight``.
        node_colors: Dict {tipo: cor}. Padrão: navy=parlamentar, gold=fornecedor.
        titulo: Título opcional do grafo.
    """
    if nodes.empty:
        st.info("Sem nós para exibir no grafo.")
        return

    import networkx as nx

    if node_colors is None:
        node_colors = {"parlamentar": NAVY, "fornecedor": GOLD}

    G = nx.Graph()
    for _, row in nodes.iterrows():
        G.add_node(row["id"], label=row.get("label", row["id"]), tipo=row.get("tipo", "no"))
    for _, row in edges.iterrows():
        G.add_edge(row["source"], row["target"], weight=row.get("weight", 1))

    pos = nx.spring_layout(G, seed=42)

    # --- Arestas ---
    edge_x, edge_y = [], []
    for e in G.edges():
        x0, y0 = pos[e[0]]
        x1, y1 = pos[e[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=0.5, color=LINE),
        hoverinfo="none",
        mode="lines",
    )

    # --- Nós ---
    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_full = [str(G.nodes[n].get("label", n)) for n in G.nodes()]
    # Rótulo curto no grafo (nomes longos estouravam o layout); hover
    # mostra o nome completo (Sprint 19).
    node_text = [t if len(t) <= 26 else t[:25] + "…" for t in node_full]
    node_tipo = [G.nodes[n].get("tipo", "no") for n in G.nodes()]
    node_color = [node_colors.get(t, MUTED) for t in node_tipo]

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=9, family="IBM Plex Mono, monospace"),
        hovertemplate="%{customdata[0]} (%{customdata[1]})<extra></extra>",
        customdata=list(zip(node_full, node_tipo)),
        marker=dict(size=10, color=node_color, line=dict(width=1, color=WHITE)),
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        showlegend=False,
        hovermode="closest",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=10, r=10, t=30, b=10),
        height=500,
    )
    if titulo:
        fig.update_layout(title=dict(text=titulo, x=0.5, font=dict(size=14)))
    st.plotly_chart(fig, use_container_width=True)
