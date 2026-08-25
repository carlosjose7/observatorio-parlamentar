"""dashboard/pages/05_fornecedor.py — perfil e parlamentares de um fornecedor.

Consome `GET /fornecedores`, `GET /fornecedores/{cnpj_cpf}` e
`GET /fornecedores/{cnpj_cpf}/parlamentares` (RF-05). CNPJ casa exatamente;
CPF está pseudonimizado na Silver (ADR-011/033) — busca por CPF cru retorna
404. Exportação (RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import (
    carregar_com_feedback,
    formatar_moeda,
    tabela_exportavel,
)

st.set_page_config(page_title="Fornecedor", page_icon="🏢", layout="wide")
st.title("🏢 Fornecedor")

client = ApiClient()


def _selecionar_fornecedor() -> dict | None:
    with st.sidebar:
        st.subheader("Buscar fornecedor")
        nome = st.text_input("Nome", key="forn_nome")
        tipo = st.selectbox("Tipo de documento", ["", "CNPJ", "CPF"], key="forn_tipo")
        buscar = st.button("Buscar", key="forn_buscar")

    if not buscar and "forn_lista" not in st.session_state:
        st.info("Use a busca na barra lateral para localizar um fornecedor.")
        return None

    if buscar:
        payload = carregar_com_feedback(
            lambda: client.listar_fornecedores(
                nome=nome or None, tipo_documento=tipo or None, limite=100,
            ),
            spinner="Buscando fornecedores...",
        )
        st.session_state["forn_lista"] = payload
        st.session_state["forn_sel"] = None

    payload = st.session_state.get("forn_lista")
    if not payload:
        return None

    itens = payload.get("itens", [])
    if not itens:
        st.warning("Nenhum fornecedor encontrado com os filtros informados.")
        return None

    opcoes = {
        f"{i['nome_fornecedor']} ({i['cnpj_cpf_valor']})": i["cnpj_cpf_valor"]
        for i in itens
    }
    sel = st.selectbox("Fornecedor", list(opcoes.keys()), key="forn_sel")
    if sel is None:
        return None
    return next(i for i in itens if i["cnpj_cpf_valor"] == opcoes[sel])


def _render_perfil(cnpj_cpf_valor: str) -> None:
    perfil = carregar_com_feedback(
        lambda: client.perfil_fornecedor(cnpj_cpf_valor),
        spinner="Carregando perfil...",
    )
    if perfil is None:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nome", perfil.get("nome_fornecedor"))
    c2.metric("Documento", perfil.get("cnpj_cpf_valor"))
    c3.metric("Despesas", perfil.get("num_despesas"))
    c4.metric("Total recebido", formatar_moeda(perfil.get("valor_liquido_total")))


def _render_parlamentares(cnpj_cpf_valor: str) -> None:
    st.subheader("Parlamentares que gastaram neste fornecedor")
    payload = carregar_com_feedback(
        lambda: client.parlamentares_fornecedor(cnpj_cpf_valor, limite=100),
        spinner="Carregando parlamentares...",
    )
    if payload is None:
        return
    itens = payload.get("itens", [])
    if not itens:
        st.info("Nenhum parlamentar vinculado.")
        return
    df = pd.DataFrame(itens)[
        ["nome", "sigla_partido", "sigla_uf", "total_gasto", "num_despesas"]
    ].rename(
        columns={
            "nome": "Nome",
            "sigla_partido": "Partido",
            "sigla_uf": "UF",
            "total_gasto": "Total gasto",
            "num_despesas": "Despesas",
        }
    )
    df["Total gasto"] = df["Total gasto"].map(formatar_moeda)
    tabela_exportavel(df, nome_arquivo=f"fornecedor_{cnpj_cpf_valor[:8]}")


def main() -> None:
    fornecedor = _selecionar_fornecedor()
    if fornecedor is None:
        return
    st.divider()
    cnpj_cpf_valor = fornecedor["cnpj_cpf_valor"]
    if not cnpj_cpf_valor:
        st.warning("Fornecedor sem documento de identificação.")
        return
    _render_perfil(cnpj_cpf_valor)
    _render_parlamentares(cnpj_cpf_valor)


main()
