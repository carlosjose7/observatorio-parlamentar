"""dashboard/pages/03_partido.py — visão por partido.

Lista parlamentares de um partido com resumo de despesas, consumindo
`GET /parlamentares` (filtro `partido`) + `GET /parlamentares/{id}/gastos`
para o total. Exportação (RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import carregar_com_feedback, formatar_moeda, tabela_exportavel

st.set_page_config(page_title="Partido", page_icon="🏛️", layout="wide")
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

    # Total gasto por parlamentar via agregação de gastos (até 100).
    linhas = []
    for _, row in df.iterrows():
        g = carregar_com_feedback(
            lambda rid=row["id_parlamentar"]: client.gastos_parlamentar(rid, limite=100),
            spinner="",
        )
        total = sum(float(x["valor_liquido"]) for x in (g or {}).get("itens", [])) if g else 0.0
        linhas.append(
            {
                "nome": row["nome"],
                "uf": row["sigla_uf"],
                "situacao": row["situacao_normalizada"],
                "total_gasto": total,
            }
        )

    resumo = pd.DataFrame(linhas).sort_values("total_gasto", ascending=False)
    resumo["total_gasto"] = resumo["total_gasto"].map(formatar_moeda)
    st.markdown(f"**{len(resumo)} parlamentares de {partido}**")
    tabela_exportavel(resumo, nome_arquivo=f"partido_{partido}")


main()
