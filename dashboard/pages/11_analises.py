"""dashboard/pages/11_analises.py — análises agregadas em gráficos de barras.

Consome os endpoints `GET /agregacoes/*` (ADR-026: agregação no Gold pela
API): gastos por UF, por partido, top parlamentares e série mensal. Os
gráficos seguem a identidade visual da landing (navy `#0B1F33`, destaque
verde `#187A52` para o líder do ranking).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.client import ApiClient
from dashboard.ui import aplicar_identidade, carregar_com_feedback, formatar_moeda

st.set_page_config(page_title="Análises", page_icon="📊", layout="wide")
aplicar_identidade()
st.title("📊 Análises")
st.caption("Gastos parlamentares agregados na camada Gold — Câmara e Senado.")

client = ApiClient()

_NAVY = "#0B1F33"
_GREEN = "#187A52"
_GRID = "#D9DEE3"


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
    df["lider"] = range(len(df)) == 0
    return df


def _estilo(chart):
    """Aplica fonte, grade e fundo da identidade visual a um gráfico."""
    return (
        chart.configure(font="'DM Sans', sans-serif")
        .configure_axis(
            labelColor="#5C6B7A",
            titleColor="#5C6B7A",
            labelFontSize=12,
            titleFontSize=12,
            grid=True,
            gridColor=_GRID,
            gridOpacity=0.6,
        )
        .configure_view(stroke=None)
    )


def _barras_ranking(df: pd.DataFrame, titulo_eixo: str) -> alt.Chart:
    """Barras horizontais ordenadas por total (líder em verde)."""
    return _estilo(
        alt.Chart(df).mark_bar().encode(
            x=alt.X("total_num:Q", title=titulo_eixo, axis=alt.Axis(format=",.0f")),
            y=alt.Y("rotulo:N", sort="-x", title=None),
            color=alt.condition(
                "datum.lider",
                alt.value(_GREEN),
                alt.value(_NAVY),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("rotulo:N", title="Recorte"),
                alt.Tooltip("total_fmt:N", title="Total"),
                alt.Tooltip("num_despesas:Q", title="Despesas", format=",d"),
            ],
        ).properties(height=380, width="container")
    )


def _render_secao(titulo: str, payload: dict | None, grafico: str) -> None:
    """Título + gráfico de um recorte; silencioso se a API falhou."""
    st.subheader(titulo)
    df = _df_agregacao(payload)
    if df.empty:
        st.info("Sem dados disponíveis para este recorte.")
        return
    if grafico == "tempo":
        _render_serie_tempo(df)
        return
    st.altair_chart(_barras_ranking(df, "Total (R$)"), use_container_width=True)


def _render_serie_tempo(df: pd.DataFrame) -> None:
    """Série mensal de gasto — barras verticais por mês (AAAAMM)."""
    chart = _estilo(
        alt.Chart(df).mark_bar(color=_NAVY).encode(
            x=alt.X("rotulo:N", title="Mês (AAAAMM)", sort=None),
            y=alt.Y("total_num:Q", title="Total (R$)", axis=alt.Axis(format=",.0f")),
            tooltip=[
                alt.Tooltip("rotulo:N", title="Mês"),
                alt.Tooltip("total_fmt:N", title="Total"),
                alt.Tooltip("num_despesas:Q", title="Despesas", format=",d"),
            ],
        ).properties(height=320, width="container")
    )
    st.altair_chart(chart, use_container_width=True)


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
    _render_secao("Top parlamentares por gasto acumulado", top, "ranking")

    st.caption(
        "Valores agregados de valor líquido na versão vigente do parlamentar "
        "(SCD2). Sinalizações estatísticas não implicam irregularidade."
    )


main()
