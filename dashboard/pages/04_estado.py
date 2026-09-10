"""dashboard/pages/04_estado.py — visão por estado (UF).

Sprint 20 (Onda 20.3): reescrita server-side — antes, 1 + N×até5 GETs
(`gastos_parlamentar_tudo` por parlamentar) estouravam o timeout de 30s e
exibiam "API indisponível" (sintoma mais frequente nesta página, com 214
parlamentares em SP). Agora: `GET /agregacoes/por-uf` (totais),
`GET /agregacoes/top-parlamentares?uf=` (ranking + totais, paginado),
`GET /agregacoes/no-tempo?uf=` (série mensal) e
`GET /parlamentares?uf=` (roster p/ Situação). Exportação (RF-08).
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

st.set_page_config(page_title="Estado", page_icon="🗺️", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("🗺️ Estado")

_UF = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]


@st.cache_data(ttl=300)
def _totais_uf() -> list[dict]:
    """Totais por UF (1 chamada agregada)."""
    payload = ApiClient().agregacao_por_uf(limite=27)
    return payload.get("itens", [])


@st.cache_data(ttl=300)
def _top_da_uf(uf: str, ano: int | None, max_paginas: int = 3) -> list[dict]:
    """Ranking + totais dos parlamentares da UF (paginado, server-side)."""
    client = ApiClient()
    itens: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        payload = client.top_parlamentares(
            limite=100, ano=ano, uf=uf, pagina=pagina,
        )
        lote = (payload or {}).get("itens", [])
        itens.extend(lote)
        if len(lote) < 100:
            break
    return itens


@st.cache_data(ttl=300)
def _serie_da_uf(uf: str) -> list[dict]:
    """Série mensal da UF (server-side)."""
    payload = ApiClient().despesas_no_tempo(uf=uf)
    return (payload or {}).get("itens", [])


@st.cache_data(ttl=300)
def _roster_da_uf(uf: str, max_paginas: int = 3) -> list[dict]:
    """Roster vigente da UF (p/ coluna Situação)."""
    client = ApiClient()
    itens: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        payload = client.listar_parlamentares(
            uf=uf, pagina=pagina, limite=100,
        )
        lote = (payload or {}).get("itens", [])
        itens.extend(lote)
        if len(lote) < 100:
            break
    return itens


def main() -> None:
    totais = carregar_com_feedback(
        _totais_uf, spinner="Carregando totais por UF...",
    )
    if totais is None:
        return

    uf = st.selectbox("UF", _UF)

    serie_itens = carregar_com_feedback(
        lambda: _serie_da_uf(uf),
        spinner=f"Carregando série de {uf}...",
    )
    if serie_itens is None:
        return
    anos = sorted({int(i["periodo"][:4]) for i in serie_itens if i.get("periodo")})
    ano_sel = st.selectbox(
        "Ano", ["Todos"] + anos, format_func=str, key=f"uf_{uf}_ano",
    )
    ano = None if ano_sel == "Todos" else int(ano_sel)

    top_itens = carregar_com_feedback(
        lambda: _top_da_uf(uf, ano),
        spinner=f"Agregando {uf}...",
    )
    if top_itens is None:
        return
    if not top_itens:
        st.info(f"Nenhuma despesa encontrada para parlamentares da UF {uf}.")
        return

    roster = carregar_com_feedback(
        lambda: _roster_da_uf(uf),
        spinner="Carregando roster...",
    )
    situacao = {(r.get("nome"), r.get("sigla_partido")): r.get("situacao_normalizada")
                for r in (roster or [])}

    df_top = pd.DataFrame(top_itens)
    df_top["Total gasto"] = df_top["total"].astype(float)
    df_top["Parlamentar"] = df_top["rotulo"]
    df_top["Partido"] = df_top["sigla_partido"].fillna("—")
    df_top["Situação"] = [
        situacao.get((n, p), "—")
        for n, p in zip(df_top["rotulo"], df_top["sigla_partido"])
    ]
    df_top["N despesas"] = df_top["num_despesas"].astype(int)

    total_recorte = float(df_top["Total gasto"].sum())
    st.markdown(
        f"**{len(df_top)} parlamentares da UF {uf} · "
        f"{formatar_moeda(total_recorte)} no recorte**"
    )
    total_uf_gold = next(
        (float(i.get("total") or 0) for i in totais if i.get("rotulo") == uf), None,
    )
    if total_uf_gold is not None:
        st.caption(f"{uf} soma {formatar_moeda(total_uf_gold)} no Gold.")

    if serie_itens:
        df_serie = pd.DataFrame([
            {"ano": int(i["periodo"][:4]), "mes": int(i["periodo"][4:6]),
             "valor_liquido": float(i["total"])}
            for i in serie_itens if i.get("periodo")
        ])
        if ano is not None:
            df_serie = df_serie[df_serie["ano"] == ano]
        df_serie = filtro_periodo(df_serie, key_prefix=f"uf_{uf}")
        if not df_serie.empty:
            grafico_mensal(df_serie)

    resumo = df_top[["Parlamentar", "Partido", "Situação", "Total gasto", "N despesas"]].sort_values(
        "Total gasto", ascending=False,
    )
    tabela = resumo.copy()
    tabela["Total gasto"] = tabela["Total gasto"].map(formatar_moeda)
    tabela_exportavel(tabela, nome_arquivo=f"uf_{uf}")


main()
