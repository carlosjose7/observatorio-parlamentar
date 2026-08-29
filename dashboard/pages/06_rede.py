"""dashboard/pages/06_rede.py — rede parlamentar-fornecedor e comunidades.

Consome `GET /parlamentares/{id}/rede` (rede de um parlamentar) e
`GET /rede/comunidades` (comunidades detectadas, ADR-030). Renderiza um
grafo com NetworkX + matplotlib (extra `dashboard`) e permite exportação
(RF-08).
"""

from __future__ import annotations

import networkx as nx
import pandas as pd
import streamlit as st

from dashboard.charts import barras_ranking, grafo_rede
from dashboard.client import ApiClient
from dashboard.ui import (
    aplicar_identidade,
    botao_voltar,
    carregar_com_feedback,
    formatar_moeda,
    tabela_exportavel,
)

st.set_page_config(page_title="Rede", page_icon="🕸️", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("🕸️ Rede Parlamentar-Fornecedor")

client = ApiClient()

#: Teto de nós/arestas renderizados (Gate 3, auditoria Sprint 7) — evita
#: NetworkX/visualização pesada com grafos grandes.
_MAX_ARESTAS = 100
_MAX_NOS_COMUNIDADE = 200


def _selecionar_parlamentar() -> dict | None:
    """Filtros de busca + seletor de parlamentar (side effect: session_state)."""
    with st.sidebar:
        st.subheader("Buscar parlamentar")
        nome = st.text_input("Nome", key="rede_nome")
        uf = st.text_input("UF (2 letras)", max_chars=2, key="rede_uf")
        partido = st.text_input("Partido (sigla)", key="rede_partido")
        buscar = st.button("Buscar", key="rede_buscar")

    if not buscar and "rede_lista" not in st.session_state:
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
        st.session_state["rede_lista"] = payload
        st.session_state["rede_sel"] = None

    payload = st.session_state.get("rede_lista")
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
    sel = st.selectbox("Parlamentar", list(opcoes.keys()), key="rede_sel")
    if sel is None:
        return None
    return next(i for i in itens if i["id_parlamentar"] == opcoes[sel])


def _rede_do_parlamentar(id_parlamentar: int) -> None:
    """Grafo centrado em um parlamentar, com filtro de período e ranking."""
    st.subheader("Rede de um parlamentar")
    payload = carregar_com_feedback(
        lambda: client.rede_parlamentar(id_parlamentar),
        spinner="Carregando rede...",
    )
    if payload is None:
        return

    arestas = payload.get("arestas", [])
    if not arestas:
        st.info(
            "Nenhuma interação registrada para este parlamentar na janela carregada."
        )
        return

    periodos = sorted({str(a.get("periodo")) for a in arestas})
    sel_periodos = st.multiselect(
        "Filtrar por período", periodos, key=f"rede_per_{id_parlamentar}"
    )
    if sel_periodos:
        arestas = [a for a in arestas if str(a.get("periodo")) in sel_periodos]
    if not arestas:
        st.info("Nenhuma interação nos períodos selecionados.")
        return

    resumo: dict[int, dict] = {}
    for aresta in arestas:
        chave = aresta["id_fornecedor"]
        linha = resumo.setdefault(
            chave,
            {
                "nome": aresta.get("nome_fornecedor") or f"#{chave}",
                "total": 0.0,
                "periodos": set(),
            },
        )
        linha["total"] += float(aresta.get("valor_total", 0))
        linha["periodos"].add(aresta.get("periodo"))

    ordenados = sorted(resumo.items(), key=lambda kv: kv[1]["total"], reverse=True)
    if len(ordenados) > _MAX_ARESTAS:
        st.warning(
            f"{len(ordenados):,} fornecedores no recorte — exibindo os "
            f"{_MAX_ARESTAS:,} de maior vínculo.".replace(",", ".")
        )
    cortados = ordenados[:_MAX_ARESTAS]

    grafo = nx.Graph()
    parlamentar = payload.get("parlamentar", {})
    grafo.add_node("eu", label=parlamentar.get("nome", "Parlamentar"), tipo="parlamentar")
    for id_forn, info in cortados:
        grafo.add_node(id_forn, label=info["nome"], tipo="fornecedor")
        grafo.add_edge("eu", id_forn, weight=info["total"])

    nodes_df = pd.DataFrame([
        {"id": n, "label": grafo.nodes[n].get("label", str(n)), "tipo": grafo.nodes[n].get("tipo", "no")}
        for n in grafo.nodes
    ])
    edges_df = pd.DataFrame([
        {"source": u, "target": v, "weight": d.get("weight", 1)}
        for u, v, d in grafo.edges(data=True)
    ])
    grafo_rede(nodes_df, edges_df)

    st.markdown(f"**Ranking de fornecedores ({len(ordenados)})**")
    if len(cortados) >= 2:
        grafico_df = pd.DataFrame(
            {
                "Fornecedor": [info["nome"] for _, info in cortados[:10]],
                "Total": [info["total"] for _, info in cortados[:10]],
            }
        )
        st.altair_chart(
            barras_ranking(grafico_df, "Fornecedor", "Total", "Total (R$)"),
            use_container_width=True,
        )

    total_rede = sum(info["total"] for _, info in ordenados)
    df = pd.DataFrame(
        [
            {
                "#": posicao,
                "Fornecedor": info["nome"],
                "Total": info["total"],
                "% da rede": (
                    f"{info['total'] / total_rede:.1%}" if total_rede else "—"
                ),
                "Períodos": ", ".join(str(p) for p in sorted(info["periodos"])),
            }
            for posicao, (_, info) in enumerate(cortados, start=1)
        ]
    )
    df["Total"] = df["Total"].map(formatar_moeda)
    tabela_exportavel(df, nome_arquivo=f"ranking_fornecedores_{id_parlamentar}")


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


def _rede_do_fornecedor() -> None:
    """Grafo INVERSO: um fornecedor e os parlamentares que o procuram."""
    st.subheader("Rede de um fornecedor")
    busca = st.text_input(
        "Nome do fornecedor (busca parcial)",
        key="rede_forn_busca",
        placeholder="Ex.: transportes, hotel, mercado...",
    )

    if busca:
        payload = carregar_com_feedback(
            lambda: client.listar_fornecedores(nome=busca, limite=50),
            spinner="Buscando fornecedores...",
        )
        if payload is None:
            return
        itens = payload.get("itens", [])
        if not itens:
            st.warning("Nenhum fornecedor encontrado com esse nome.")
            return
    else:
        sugestoes = carregar_com_feedback(
            lambda: client.top_fornecedores(limite=15),
            spinner="Carregando maiores fornecedores...",
        )
        if not sugestoes:
            return
        itens = [
            {
                "id_fornecedor": s["id_fornecedor"],
                "nome_fornecedor": s["nome_fornecedor"],
                "tipo_documento": None,
            }
            for s in sugestoes.get("itens", [])
        ]
        if not itens:
            return
        st.caption(
            f"Top {len(itens)} fornecedores por valor recebido — "
            "ou refine pela busca parcial acima."
        )

    opcoes = {
        f"{i['nome_fornecedor']} ({i['tipo_documento'] or '?'})": i["id_fornecedor"]
        for i in itens
    }
    sel = st.selectbox("Fornecedor", list(opcoes.keys()), key="rede_forn_sel")
    id_sel = opcoes[sel]
    dados = carregar_com_feedback(
        lambda: client.rede_fornecedor(id_sel),
        spinner="Carregando rede do fornecedor...",
    )
    if dados is None:
        return
    arestas = dados.get("arestas", [])
    if not arestas:
        st.info(
            "Nenhuma interação registrada para este fornecedor na janela "
            "carregada do Gold."
        )
        return

    c1, c2 = st.columns(2)
    c1.metric("Total recebido", formatar_moeda(dados.get("total_recebido")))
    c2.metric("Parlamentares conectados", dados.get("num_parlamentares", 0))

    periodos = sorted({str(a.get("periodo")) for a in arestas})
    sel_periodos = st.multiselect(
        "Filtrar por período", periodos, key=f"forn_per_{id_sel}"
    )
    if sel_periodos:
        arestas = [a for a in arestas if str(a.get("periodo")) in sel_periodos]
    if not arestas:
        st.info("Nenhuma interação nos períodos selecionados.")
        return

    resumo: dict[int, dict] = {}
    for aresta in arestas:
        chave = aresta["id_parlamentar"]
        linha = resumo.setdefault(
            chave,
            {
                "nome": aresta.get("nome") or f"#{chave}",
                "partido": aresta.get("sigla_partido") or "?",
                "uf": aresta.get("sigla_uf") or "?",
                "total": 0.0,
                "periodos": set(),
            },
        )
        linha["total"] += float(aresta.get("valor_total", 0))
        linha["periodos"].add(aresta.get("periodo"))

    ordenados = sorted(resumo.items(), key=lambda kv: kv[1]["total"], reverse=True)

    partidos = sorted({info["partido"] for _, info in ordenados})
    ufs = sorted({info["uf"] for _, info in ordenados})
    cf1, cf2 = st.columns(2)
    with cf1:
        sel_partidos = st.multiselect(
            "Filtrar por partido", partidos, key=f"forn_p_{id_sel}"
        )
    with cf2:
        sel_ufs = st.multiselect("Filtrar por UF", ufs, key=f"forn_u_{id_sel}")

    visiveis = [
        (idp, info)
        for idp, info in ordenados
        if (not sel_partidos or info["partido"] in sel_partidos)
        and (not sel_ufs or info["uf"] in sel_ufs)
    ]
    if not visiveis:
        st.info("Nenhum parlamentar no recorte de filtros selecionado.")
        return
    if len(visiveis) > _MAX_ARESTAS:
        st.warning(
            f"{len(visiveis):,} parlamentares no recorte — exibindo os "
            f"{_MAX_ARESTAS:,} de maior vínculo.".replace(",", ".")
        )
    cortados = visiveis[:_MAX_ARESTAS]

    grafo = nx.Graph()
    grafo.add_node(
        "fornecedor",
        label=dados.get("nome_fornecedor", "Fornecedor"),
        tipo="fornecedor",
    )
    for id_parl, info in cortados:
        grafo.add_node(
            id_parl,
            label=f"{info['nome']} ({info['partido']}-{info['uf']})",
            tipo="parlamentar",
        )
        grafo.add_edge("fornecedor", id_parl, weight=info["total"])

    nodes_df = pd.DataFrame([
        {"id": n, "label": grafo.nodes[n].get("label", str(n)), "tipo": grafo.nodes[n].get("tipo", "no")}
        for n in grafo.nodes
    ])
    edges_df = pd.DataFrame([
        {"source": u, "target": v, "weight": d.get("weight", 1)}
        for u, v, d in grafo.edges(data=True)
    ])
    grafo_rede(nodes_df, edges_df)

    st.markdown(f"**Ranking de parlamentares conectados ({len(visiveis)})**")
    if len(cortados) >= 2:
        grafico_df = pd.DataFrame(
            {
                "Parlamentar": [
                    f"{info['nome']} ({info['partido']}-{info['uf']})"
                    for _, info in cortados[:10]
                ],
                "Total": [info["total"] for _, info in cortados[:10]],
            }
        )
        st.altair_chart(
            barras_ranking(grafico_df, "Parlamentar", "Total", "Total (R$)"),
            use_container_width=True,
        )

    total_recebido = float(dados.get("total_recebido") or 0)
    df = pd.DataFrame(
        [
            {
                "#": posicao,
                "Parlamentar": info["nome"],
                "Partido": info["partido"],
                "UF": info["uf"],
                "Total": info["total"],
                "% do recebido": (
                    f"{info['total'] / total_recebido:.1%}" if total_recebido else "—"
                ),
                "Períodos": ", ".join(str(p) for p in sorted(info["periodos"])),
            }
            for posicao, (_, info) in enumerate(cortados, start=1)
        ]
    )
    df["Total"] = df["Total"].map(formatar_moeda)
    tabela_exportavel(df, nome_arquivo=f"ranking_fornecedor_{id_sel}")


def main() -> None:
    abas = st.tabs(["Rede do parlamentar", "Rede do fornecedor", "Comunidades"])
    with abas[0]:
        parlamentar = _selecionar_parlamentar()
        if parlamentar is not None:
            st.divider()
            _rede_do_parlamentar(parlamentar["id_parlamentar"])
    with abas[1]:
        _rede_do_fornecedor()
    with abas[2]:
        _comunidades()


main()
