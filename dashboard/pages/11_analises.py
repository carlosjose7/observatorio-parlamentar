"""dashboard/pages/11_analises.py — análises agregadas em gráficos de barras.

Consome os endpoints `GET /agregacoes/*` (ADR-026: agregação no Gold pela
API): gastos por UF, por partido, top parlamentares e série mensal. Os
gráficos seguem a identidade visual da landing (paleta única via
`dashboard.theme`, ADR-038).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.charts import barras_ranking, serie_mensal
from dashboard.client import ApiClient
from dashboard.ui import (
    aplicar_identidade,
    botao_voltar,
    carregar_com_feedback,
    formatar_moeda,
)

st.set_page_config(page_title="Análises", page_icon="📊", layout="wide")
aplicar_identidade()
botao_voltar()
st.title("📊 Análises")
st.caption("Gastos parlamentares agregados na camada Gold — Câmara e Senado.")

client = ApiClient()


def _df_agregacao(payload: dict | None) -> pd.DataFrame:
    """Converte o envelope `/agregacoes/*` em DataFrame pronto para gráfico."""
    if not payload:
        return pd.DataFrame()
    itens = payload.get("itens", [])
    if not itens:
        return pd.DataFrame()
    df = pd.DataFrame(itens)
    if "periodo" in df.columns:
        df = df.rename(columns={"periodo": "rotulo"})
    df["total_num"] = df["total"].astype(float)
    df["total_fmt"] = df["total_num"].map(formatar_moeda)
    return df


def _render_secao(titulo: str, payload: dict | None, grafico: str) -> None:
    """Título + gráfico de um recorte; silencioso se a API falhou."""
    st.subheader(titulo)
    df = _df_agregacao(payload)
    if df.empty:
        st.info("Sem dados disponíveis para este recorte.")
        return
    if grafico == "tempo":
        st.altair_chart(
            serie_mensal(df, "rotulo", "total_num"),
            use_container_width=True,
        )
        return
    st.altair_chart(
        barras_ranking(df, "rotulo", "total_num"),
        use_container_width=True,
    )


def _render_janela(serie: dict | None) -> None:
    """Faixa de período avaliado, derivada da própria série mensal do Gold."""
    itens = (serie or {}).get("itens") or []
    if not itens:
        return

    def _fmt(periodo: str) -> str:
        return f"{int(periodo[4:6])}/{periodo[:4]}"

    total = sum(i.get("num_despesas", 0) for i in itens)
    st.caption(
        f"Janela analisada: **{_fmt(itens[0]['periodo'])} a "
        f"{_fmt(itens[-1]['periodo'])}** · {total:,} despesas na camada "
        "Gold (Câmara + Senado).".replace(",", ".")
    )


def main() -> None:
    uf = carregar_com_feedback(
        lambda: client.agregacao_por_uf(limite=10),
        spinner="Agregando gastos por UF...",
    )
    partido = carregar_com_feedback(
        lambda: client.agregacao_por_partido(limite=10),
        spinner="Agregando gastos por partido...",
    )
    serie = carregar_com_feedback(
        lambda: client.despesas_no_tempo(),
        spinner="Montando série mensal...",
    )

    _render_janela(serie)

    col_uf, col_partido = st.columns(2)
    with col_uf:
        _render_secao("Gastos por UF", uf, "ranking")
    with col_partido:
        _render_secao("Gastos por partido", partido, "ranking")

    _render_secao("Gastos no tempo (mês de competência)", serie, "tempo")

    top = carregar_com_feedback(
        lambda: client.top_parlamentares(limite=10),
        spinner="Calculando top parlamentares...",
    )
    if top and top.get("itens"):
        for item in top["itens"]:
            partido = item.get("sigla_partido") or "—"
            item["rotulo"] = f"{item['rotulo']} ({partido})"
    _render_secao("Top parlamentares por gasto acumulado", top, "ranking")

    st.caption(
        "Valores agregados de valor líquido na versão vigente do parlamentar "
        "(SCD2). Sinalizações estatísticas não implicam irregularidade."
    )


main()
