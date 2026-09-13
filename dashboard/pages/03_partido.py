"""dashboard/pages/03_partido.py — visão por partido.

Sprint 20 (Onda 20.3): reescrita server-side — antes, 1 + N×até5 GETs
(`gastos_parlamentar_tudo` por parlamentar) estouravam o timeout de 30s e
exibiam "API indisponível". Agora: `GET /agregacoes/por-partido` (opções),
`GET /agregacoes/top-parlamentares?partido=` (ranking + totais, paginado),
`GET /agregacoes/no-tempo?partido=` (série mensal) e
`GET /parlamentares?partido=` (roster p/ Situação). Exportação (RF-08).
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


@st.cache_data(ttl=300)
def _opcoes_partido() -> list[dict]:
    """Ranking de partidos (total desc) — 1 chamada agregada."""
    payload = ApiClient().agregacao_por_partido(limite=40)
    return payload.get("itens", [])


@st.cache_data(ttl=300)
def _top_do_partido(partido: str, ano: int | None, max_paginas: int = 3) -> list[dict]:
    """Ranking + totais dos membros do partido (paginado, server-side)."""
    client = ApiClient()
    itens: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        payload = client.top_parlamentares(
            limite=100, ano=ano, partido=partido, pagina=pagina,
        )
        lote = (payload or {}).get("itens", [])
        itens.extend(lote)
        if len(lote) < 100:
            break
    return itens


@st.cache_data(ttl=300)
def _serie_do_partido(partido: str) -> list[dict]:
    """Série mensal do partido (server-side)."""
    payload = ApiClient().despesas_no_tempo(partido=partido)
    return (payload or {}).get("itens", [])


@st.cache_data(ttl=300)
def _roster_do_partido(partido: str, max_paginas: int = 3) -> list[dict]:
    """Roster vigente do partido (p/ coluna Situação)."""
    client = ApiClient()
    itens: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        payload = client.listar_parlamentares(
            partido=partido, pagina=pagina, limite=100,
        )
        lote = (payload or {}).get("itens", [])
        itens.extend(lote)
        if len(lote) < 100:
            break
    return itens


def main() -> None:
    ranking_partidos = carregar_com_feedback(
        _opcoes_partido, spinner="Carregando partidos...",
    )
    if not ranking_partidos:
        st.info("Nenhum partido encontrado.")
        return

    total_geral = sum(float(i.get("total") or 0) for i in ranking_partidos)
    opcoes = [i["rotulo"] for i in ranking_partidos]
    partido = st.selectbox("Partido", opcoes)

    serie_itens = carregar_com_feedback(
        lambda: _serie_do_partido(partido),
        spinner=f"Carregando série de {partido}...",
    )
    if serie_itens is None:
        return
    anos = sorted({int(i["periodo"][:4]) for i in serie_itens if i.get("periodo")})
    ano_sel = st.selectbox(
        "Ano", ["Todos"] + anos, format_func=str, key=f"partido_{partido}_ano",
    )
    ano = None if ano_sel == "Todos" else int(ano_sel)

    top_itens = carregar_com_feedback(
        lambda: _top_do_partido(partido, ano),
        spinner=f"Agregando {partido}...",
    )
    if top_itens is None:
        return
    if not top_itens:
        st.info(f"Nenhuma despesa encontrada para parlamentares de {partido}.")
        return

    roster = carregar_com_feedback(
        lambda: _roster_do_partido(partido),
        spinner="Carregando roster...",
    )
    situacao = {(r.get("nome"), r.get("sigla_uf")): r.get("situacao_normalizada")
                for r in (roster or [])}

    df_top = pd.DataFrame(top_itens)
    df_top["Total gasto"] = df_top["total"].astype(float)
    df_top["Parlamentar"] = df_top["rotulo"]
    df_top["UF"] = df_top["sigla_uf"].fillna("—")
    df_top["Situação"] = [
        situacao.get((n, u), "—")
        for n, u in zip(df_top["rotulo"], df_top["sigla_uf"])
    ]
    df_top["N despesas"] = df_top["num_despesas"].astype(int)

    total_recorte = float(df_top["Total gasto"].sum())
    total_partido_gold = sum(
        float(i.get("total") or 0) for i in ranking_partidos if i["rotulo"] == partido
    )
    st.markdown(
        f"**{len(df_top)} parlamentares de {partido} · "
        f"{formatar_moeda(total_recorte)} no recorte**"
    )
    if total_geral:
        st.caption(
            f"{partido} soma {formatar_moeda(total_partido_gold)} no Gold "
            f"({total_recorte / total_geral:.1%} do total entre partidos)."
        )

    if serie_itens:
        df_serie = pd.DataFrame([
            {"ano": int(i["periodo"][:4]), "mes": int(i["periodo"][4:6]),
             "valor_liquido": float(i["total"])}
            for i in serie_itens if i.get("periodo")
        ])
        if ano is not None:
            df_serie = df_serie[df_serie["ano"] == ano]
        df_serie = filtro_periodo(df_serie, key_prefix=f"partido_{partido}_serie")
        if not df_serie.empty:
            grafico_mensal(df_serie)

    resumo = df_top[["Parlamentar", "UF", "Situação", "Total gasto", "N despesas"]].sort_values(
        "Total gasto", ascending=False,
    )
    tabela = resumo.copy()
    tabela["Total gasto"] = tabela["Total gasto"].map(formatar_moeda)
    tabela_exportavel(tabela, nome_arquivo=f"partido_{partido}")


main()
