"""dashboard/pages/04_estado.py — visão por estado (UF).

Lista parlamentares de uma UF com resumo de despesas, consumindo
`GET /parlamentares` (filtro `uf`) + `GET /parlamentares/{id}/gastos`.
Exportação (RF-08).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import carregar_com_feedback, formatar_moeda, tabela_exportavel

st.set_page_config(page_title="Estado", page_icon="🗺️", layout="wide")
st.title("🗺️ Estado")

client = ApiClient()

_UF = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]


def _parlamentares_da_uf(uf: str) -> pd.DataFrame:
    payload = carregar_com_feedback(
        lambda: client.listar_parlamentares(uf=uf, limite=100),
        spinner=f"Carregando {uf}...",
    )
    if not payload:
        return pd.DataFrame()
    return pd.DataFrame(payload.get("itens", []))


def main() -> None:
    uf = st.selectbox("UF", _UF)
    df = _parlamentares_da_uf(uf)
    if df.empty:
        st.info(f"Nenhum parlamentar da UF {uf}.")
        return

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
                "partido": row["sigla_partido"],
                "situacao": row["situacao_normalizada"],
                "total_gasto": total,
            }
        )

    resumo = pd.DataFrame(linhas).sort_values("total_gasto", ascending=False)
    resumo["total_gasto"] = resumo["total_gasto"].map(formatar_moeda)
    st.markdown(f"**{len(resumo)} parlamentares da UF {uf}**")
    tabela_exportavel(resumo, nome_arquivo=f"uf_{uf}")


main()
