"""dashboard/theme.py — design system unificado do Observatório Parlamentar.

Paleta única (navy/verde/dourado) consumida por `ui.py`, `charts.py` e todas
as páginas do dashboard. Elimina a duplicação entre `config.toml`, CSS de
`ui.py`, constantes de `11_analises.py` e `:root` de `site/index.html`
(ADR-038).

`.streamlit/config.toml` e `site/index.html` permanecem literais por natureza
estática — sincronizados por comentário de referência.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta — única fonte de verdade no lado Python.
# Mantida em sincronia com `.streamlit/config.toml` e `site/index.html`.
# ---------------------------------------------------------------------------

NAVY = "#0B1F33"
NAVY_2 = "#102D47"
INK = "#14202B"
MUTED = "#5C6B7A"
LINE = "#D9DEE3"
PAPER = "#F7F7F4"
WHITE = "#FFFFFF"
GREEN = "#187A52"
GREEN_SOFT = "#E7F1EC"
GOLD = "#B58A42"
GOLD_INK = "#8A6A2F"
CONCRETE = "#ECEDEA"

# ---------------------------------------------------------------------------
# CSS — chrome do Streamlit, tipografia, componentes.
# Complementa o tema de `.streamlit/config.toml` (paleta core do Streamlit).
# ---------------------------------------------------------------------------

CSS_IDENTIDADE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

/* --- Tipografia base --- */
.stApp { font-family: "DM Sans", "Source Sans Pro", sans-serif; }
h1, h2, h3 { color: #0B1F33; letter-spacing: -0.02em; }

/* --- Métricas --- */
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #D9DEE3;
    border-radius: 0;
    padding: 16px 16px 12px;
}
[data-testid="stMetricLabel"] p {
    font-family: "IBM Plex Mono", monospace;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #5C6B7A;
}
[data-testid="stMetricValue"] { color: #0B1F33; font-weight: 700; }

/* --- Botões --- */
.stButton > button,
.stDownloadButton > button,
[data-testid="stDownloadButton"] > button {
    border-radius: 0;
    font-weight: 600;
}

/* --- Captions e labels --- */
[data-testid="stCaptionContainer"],
[data-testid="stWidgetLabel"] p { color: #5C6B7A; }

/* --- Separadores --- */
hr { border: none; border-top: 1px solid #D9DEE3; }

/* --- Abas (tabs) --- */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid #D9DEE3;
}
.stTabs [data-baseweb="tab"] {
    font-family: "IBM Plex Mono", monospace;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #5C6B7A;
    border-radius: 0;
    padding: 10px 16px;
}
.stTabs [aria-selected="true"] {
    color: #0B1F33;
    border-bottom: 2px solid #187A52;
    font-weight: 600;
}

/* --- DataFrames --- */
[data-testid="stDataFrame"] {
    border: 1px solid #D9DEE3;
    border-radius: 0;
}
[data-testid="stDataFrame"] th {
    font-family: "IBM Plex Mono", monospace;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #5C6B7A;
}

/* --- Expanders --- */
[data-testid="stExpander"] {
    border: 1px solid #D9DEE3;
    border-radius: 0;
}
[data-testid="stExpander"] summary {
    font-family: "IBM Plex Mono", monospace;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #5C6B7A;
}

/* --- Inputs (text_input, selectbox, multiselect, etc.) --- */
.stTextInput > div > div > input,
.stSelectbox > div > div,
.stMultiSelect > div > div {
    border-radius: 0;
    border-color: #D9DEE3;
}
.stTextInput > div > div > input:focus,
.stSelectbox > div > div:focus-within,
.stMultiSelect > div > div:focus-within {
    border-color: #187A52;
    box-shadow: none;
}

/* --- Botão primário --- */
.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"] {
    background-color: #187A52;
    border-color: #187A52;
    border-radius: 0;
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover {
    background-color: #145C3E;
    border-color: #145C3E;
}

/* --- Avatar parlamentar --- */
.op-avatar {
    width: 96px;
    height: 96px;
    border-radius: 50%;
    object-fit: cover;
    border: 2px solid #D9DEE3;
    display: block;
    margin-bottom: 0.5rem;
}
.op-avatar-sm {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    object-fit: cover;
    border: 2px solid #D9DEE3;
    display: block;
    margin-bottom: 0.25rem;
}

/* --- Sidebar --- */
section[data-testid="stSidebar"] {
    background-color: #0B1F33;
}
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: #DDE5EB;
}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown li {
    color: #DDE5EB;
}
</style>
"""


def aplicar_identidade() -> None:
    """Injeta o CSS da identidade visual compartilhada com a landing page.

    Complementa o tema de `.streamlit/config.toml` (paleta) com tipografia
    DM Sans/IBM Plex Mono, cartões de métrica, abas, dataframes, expanders,
    inputs e sidebar navy. Deve ser chamado logo após `st.set_page_config`
    em todas as páginas.
    """
    st.markdown(CSS_IDENTIDADE, unsafe_allow_html=True)


def cabecalho_pagina(kicker: str, titulo: str, lede: str | None = None) -> None:
    """Cabeçalho editorial replicando o padrão da landing page.

    Padrão: kicker mono (IBM Plex Mono) + título (DM Sans) + lede opcional.
    Adotado nas 11 páginas do dashboard para unificar o tom visual.

    Args:
        kicker: Texto curto acima do título (ex.: "Página 01", "Análises").
        titulo: Título principal da página.
        lede: Subtítulo ou descrição opcional.
    """
    st.markdown(
        f"""<div style="margin-bottom: 1.5rem;">
<p style="
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #5C6B7A;
    margin: 0 0 0.25rem 0;
">{kicker}</p>
<h1 style="
    font-family: 'DM Sans', sans-serif;
    font-size: 2rem;
    font-weight: 700;
    color: #0B1F33;
    letter-spacing: -0.02em;
    margin: 0 0 0.5rem 0;
">{titulo}</h1>
{"<p style='font-size: 1.05rem; color: #5C6B7A; margin: 0;'>" + lede + "</p>" if lede else ""}
</div>""",
        unsafe_allow_html=True,
    )
