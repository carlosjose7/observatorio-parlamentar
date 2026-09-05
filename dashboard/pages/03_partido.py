"""dashboard/pages/03_partido.py — visão por partido.

Lista parlamentares de um partido com resumo de despesas, consumindo
`GET /parlamentares` (filtro `partido`) + `GET /parlamentares/{id}/gastos`
para o total. Exportação (RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import (
    aplicar_identidade,
    botao_voltar,
    carregar_com_feedback,
    filtro_periodo,
    formatar_moeda,
    grafico_mensal,
    tabela_exportavel,
)

st.set_page_config(page_title="Partido", page_icon="🏛️", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("🏛️ Partido")

client = ApiClient()


def _lista_partidos() -> list[str]:
    """Partidos distintos a partir da lista paginada de parlamentares."""
    payload = carregar_com_feedback(
        lambda: client.listar_parlamentares(limite=100),
        spinner="Carregando partidos...",
    )
    if not payload:
        return []
    itens = payload.get("itens", [])
    return sorted({i["sigla_partido"] for i in itens if i.get("sigla_partido")})


def _parlamentares_do_partido(partido: str) -> pd.DataFrame:
    payload = carregar_com_feedback(
        lambda: client.listar_parlamentares(partido=partido, limite=100),
        spinner=f"Carregando {partido}...",
    )
    if not payload:
        return pd.DataFrame()
    return pd.DataFrame(payload.get("itens", []))


def main() -> None:
    partidos = _lista_partidos()
    if not partidos:
        st.info("Nenhum partido encontrado.")
        return

    partido = st.selectbox("Partido", partidos)
    df = _parlamentares_do_partido(partido)
    if df.empty:
        st.info(f"Nenhum parlamentar de {partido}.")
        return

    # Despesas (paginadas: histórico completo p/ o filtro de ano) por parlamentar.
    linhas = []
    for _, row in df.iterrows():
        itens = carregar_com_feedback(
            lambda rid=row["id_parlamentar"]: client.gastos_parlamentar_tudo(rid),
            spinner="",
        )
        for x in itens or []:
            linhas.append(
                {
                    "nome": row["nome"],
                    "uf": row["sigla_uf"],
                    "situacao": row["situacao_normalizada"],
                    "ano": x["ano"],
                    "mes": x["mes"],
                    "valor_liquido": float(x["valor_liquido"]),
                }
            )
    if not linhas:
        st.info(f"Nenhuma despesa encontrada para parlamentares de {partido}.")
        return

    despesas = filtro_periodo(pd.DataFrame(linhas), key_prefix=f"partido_{partido}")
    if despesas.empty:
        st.info("Nenhuma despesa nos períodos selecionados.")
        return

    resumo = (
        despesas.groupby(["nome", "uf", "situacao"], as_index=False)["valor_liquido"]
        .sum()
        .sort_values("valor_liquido", ascending=False)
        .rename(
            columns={
                "nome": "Parlamentar",
                "uf": "UF",
                "situacao": "Situação",
                "valor_liquido": "Total gasto",
            }
        )
    )
    st.markdown(
        f"**{len(resumo)} parlamentares de {partido} · "
        f"{formatar_moeda(resumo['Total gasto'].sum())} no recorte**"
    )
    grafico_mensal(despesas)
    resumo["Total gasto"] = resumo["Total gasto"].map(formatar_moeda)
    tabela_exportavel(resumo, nome_arquivo=f"partido_{partido}")


main()
