"""dashboard/pages/02_parlamentar.py — perfil e gastos de um parlamentar.

Consome `GET /parlamentares`, `GET /parlamentares/{id}` e
`GET /parlamentares/{id}/gastos` (RF-05). Permite buscar por nome/UF/partido,
selecionar um parlamentar e explorar suas despesas por ano, com exportação
(RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import (
    aplicar_identidade,
    carregar_com_feedback,
    filtro_periodo,
    formatar_moeda,
    grafico_mensal,
    tabela_exportavel,
)

st.set_page_config(page_title="Parlamentar", page_icon="👤", layout="wide")
aplicar_identidade()
st.title("👤 Parlamentar")

client = ApiClient()


def _selecionar_parlamentar() -> dict | None:
    """Filtros de busca + seletor de parlamentar (side effect: session_state)."""
    with st.sidebar:
        st.subheader("Buscar parlamentar")
        nome = st.text_input("Nome", key="parl_nome")
        uf = st.text_input("UF (2 letras)", max_chars=2, key="parl_uf")
        partido = st.text_input("Partido (sigla)", key="parl_partido")
        buscar = st.button("Buscar", key="parl_buscar")

    if not buscar and "parl_lista" not in st.session_state:
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
        st.session_state["parl_lista"] = payload
        st.session_state["parl_sel"] = None

    payload = st.session_state.get("parl_lista")
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
    sel = st.selectbox(
        "Parlamentar",
        list(opcoes.keys()),
        key="parl_sel",
    )
    if sel is None:
        return None
    return next(i for i in itens if i["id_parlamentar"] == opcoes[sel])


def _render_perfil(id_parlamentar: int) -> None:
    """Seção de perfil (dimensão SCD2 vigente)."""
    perfil = carregar_com_feedback(
        lambda: client.perfil_parlamentar(id_parlamentar),
        spinner="Carregando perfil...",
    )
    if perfil is None:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nome", perfil.get("nome"))
    c2.metric("Partido", perfil.get("sigla_partido"))
    c3.metric("UF", perfil.get("sigla_uf"))
    c4.metric("Situação", perfil.get("situacao_normalizada"))
    st.caption(
        f"Fonte: {perfil.get('fonte')} · Legislatura {perfil.get('id_legislatura')} · "
        f"Desde {perfil.get('effective_date')}"
    )


def _render_gastos(id_parlamentar: int) -> None:
    """Despesas do parlamentar com filtro de ano/mês, gráfico mensal e exportação."""
    st.subheader("Despesas")
    payload = carregar_com_feedback(
        lambda: client.gastos_parlamentar(id_parlamentar, limite=100),
        spinner="Carregando despesas...",
    )
    if payload is None:
        return

    itens = payload.get("itens", [])
    if not itens:
        st.info("Nenhuma despesa registrada para este parlamentar.")
        return

    df = pd.DataFrame(itens)
    df = filtro_periodo(df, key_prefix=f"gastos_{id_parlamentar}")
    if df.empty:
        st.info("Nenhuma despesa nos períodos selecionados.")
        return

    total = float(df["valor_liquido"].sum())
    tabela = df[
        ["data", "tipo_despesa", "nome_fornecedor", "tipo_documento",
         "valor_liquido", "valor_glosa"]
    ].rename(
        columns={
            "data": "Data",
            "tipo_despesa": "Tipo",
            "nome_fornecedor": "Fornecedor",
            "tipo_documento": "Doc.",
            "valor_liquido": "Valor líquido",
            "valor_glosa": "Glosa",
        }
    )
    st.markdown(f"**Total de {len(tabela)} despesas · {formatar_moeda(total)}**")
    grafico_mensal(df)
    tabela_exportavel(tabela, nome_arquivo=f"gastos_{id_parlamentar}")


def main() -> None:
    parlamentar = _selecionar_parlamentar()
    if parlamentar is None:
        return
    st.divider()
    _render_perfil(parlamentar["id_parlamentar"])
    _render_gastos(parlamentar["id_parlamentar"])


main()
