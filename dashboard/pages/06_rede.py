"""dashboard/pages/06_rede.py — rede parlamentar-fornecedor e comunidades.

Consome `GET /parlamentares/{id}/rede` (rede de um parlamentar) e
`GET /rede/comunidades` (comunidades detectadas, ADR-030). Renderiza um
grafo com NetworkX + matplotlib (extra `dashboard`) e permite exportação
(RF-08).
"""

from __future__ import annotations

import io

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import carregar_com_feedback, tabela_exportavel

st.set_page_config(page_title="Rede", page_icon="🕸️", layout="wide")
st.title("🕸️ Rede Parlamentar-Fornecedor")

client = ApiClient()

#: Teto de nós/arestas renderizados (Gate 3, auditoria Sprint 7) — evita
#: NetworkX/visualização pesada com grafos grandes.
_MAX_ARESTAS = 100
_MAX_NOS_COMUNIDADE = 200


def _rede_do_parlamentar(id_parlamentar: int) -> None:
    """Grafo centrado em um parlamentar (limitado a `_MAX_ARESTAS` arestas)."""
    st.subheader("Rede de um parlamentar")
    payload = carregar_com_feedback(
        lambda: client.rede_parlamentar(id_parlamentar),
        spinner="Carregando rede...",
    )
    if payload is None:
        return

    arestas = payload.get("arestas", [])
    if len(arestas) > _MAX_ARESTAS:
        st.warning(
            f"Rede com {len(arestas):,} fornecedores — exibindo os "
            f"{_MAX_ARESTAS:,} com maior vínculo."
        )
        arestas = sorted(
            arestas, key=lambda a: a.get("valor_total", 0), reverse=True
        )[:_MAX_ARESTAS]

    grafo = nx.Graph()
    parlamentar = payload.get("parlamentar", {})
    grafo.add_node("eu", label=parlamentar.get("nome", "Parlamentar"), tipo="parlamentar")
    for aresta in arestas:
        grafo.add_node(aresta["id_fornecedor"], label=aresta["nome_fornecedor"], tipo="fornecedor")
        grafo.add_edge("eu", aresta["id_fornecedor"], weight=aresta.get("valor_total", 1.0))

    fig, ax = plt.subplots(figsize=(10, 7))
    pos = nx.spring_layout(grafo, seed=42)
    cores = {
        "parlamentar": "#e74c3c",
        "fornecedor": "#2980b9",
    }
    nx.draw_networkx_nodes(
        grafo, pos,
        node_color=[cores[grafo.nodes[n]["tipo"]] for n in grafo.nodes],
        node_size=500,
    )
    nx.draw_networkx_labels(grafo, pos, font_size=7)
    nx.draw_networkx_edges(grafo, pos, alpha=0.4)
    ax.axis("off")
    st.pyplot(fig)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    st.download_button(
        "📥 Baixar grafo (PNG)",
        buf.getvalue(),
        file_name=f"rede_{id_parlamentar}.png",
        mime="image/png",
    )


def _comunidades() -> None:
    """Comunidades detectadas no grafo (ADR-030)."""
    st.subheader("Comunidades detectadas")
    payload = carregar_com_feedback(
        client.comunidades,
        spinner="Carregando comunidades...",
    )
    if payload is None:
        return
    itens = payload.get("itens", [])
    if not itens:
        st.info("Nenhuma comunidade detectada.")
        return

    linhas = []
    total_nos = sum(len(c.get("nos", [])) for c in itens)
    if total_nos > _MAX_NOS_COMUNIDADE:
        st.warning(
            f"{total_nos:,} nós no grafo — exibindo os {_MAX_NOS_COMUNIDADE:,} "
            "de maior pagerank (Exportar CSV gera o conjunto completo)."
        )
    for comunidade in itens:
        nos = comunidade.get("nos", [])
        if total_nos > _MAX_NOS_COMUNIDADE:
            nos = sorted(nos, key=lambda n: n.get("pagerank", 0), reverse=True)
            nos = nos[: max(1, int(_MAX_NOS_COMUNIDADE * len(nos) / total_nos))]
        for no in nos:
            linhas.append(
                {
                    "comunidade_id": comunidade["comunidade_id"],
                    "periodo": comunidade["periodo"],
                    "tipo_no": no["tipo_no"],
                    "nome": no.get("nome"),
                    "pagerank": no["pagerank"],
                    "degree_centrality": no["degree_centrality"],
                }
            )
    df = pd.DataFrame(linhas).sort_values(["comunidade_id", "pagerank"], ascending=[True, False])
    st.markdown(f"**{len(itens)} comunidades · {len(df)} nós exibidos**")
    tabela_exportavel(df, nome_arquivo="comunidades")


def main() -> None:
    abas = st.tabs(["Rede do parlamentar", "Comunidades"])
    with abas[0]:
        id_parlamentar = st.number_input(
            "ID do parlamentar", min_value=1, step=1, value=1,
        )
        _rede_do_parlamentar(int(id_parlamentar))
    with abas[1]:
        _comunidades()


main()
