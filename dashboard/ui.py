"""dashboard/ui.py — componentes de UI reutilizáveis do dashboard (Sprint 7).

Padrões comuns às 10 páginas Streamlit: estado de erro amigável quando a
API está indisponível, formatação de moeda pt-BR, métricas com fallback,
downloads de exportação (RF-08) e barra lateral padrão com filtros globais.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.client import ApiClient, ApiError, ApiIndisponivel


def formatar_moeda(valor: float | None) -> str:
    """Formata um valor monetário em pt-BR (R$ 1.234,56) ou '—' quando nulo."""
    if valor is None:
        return "—"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def metricas_seguras(rotulo: str, valor: Any, **kwargs: Any) -> None:
    """`st.metric` com valor formatado quando não nulo, senão placeholder."""
    if valor is None:
        st.metric(rotulo, "—", **kwargs)
    else:
        st.metric(rotulo, valor, **kwargs)


def estado_api(
    client: ApiClient,
    titulo: str = "API indisponível",
) -> ApiClient | None:
    """Testa a API e exibe erro amigável; retorna o cliente se acessível.

    Chamado no topo de cada página: se a API não responder, mostra `st.error`
    com a causa e `st.stop()`, evitando cascatas de erros nos widgets.
    """
    try:
        client.agent_context()
        return client
    except ApiIndisponivel as exc:
        st.error(f"{titulo} — não foi possível conectar à API. {exc}")
        st.stop()
    except ApiError:
        # API respondeu mas o contexto falhou (dado vazio) — segue mesmo assim.
        return client


def carregar_com_feedback(
    chamada: Any,
    *,
    spinner: str,
) -> Any:
    """Executa uma chamada de API com spinner e traduz erros para a UI.

    Returns:
        O payload JSON, ou `None` quando a API está indisponível (a página
        exibe o erro em vez de quebrar).
    """
    try:
        with st.spinner(spinner):
            return chamada()
    except ApiIndisponivel as exc:
        st.error(str(exc))
        return None
    except ApiError as exc:
        st.warning(str(exc))
        return None


def tabela_exportavel(
    df: pd.DataFrame,
    *,
    nome_arquivo: str = "dados",
    formatos: Iterable[str] | None = None,
) -> None:
    """Renderiza um DataFrame com botões de exportação (RF-08).

    Gera CSV (sempre), Excel e PDF conforme `formatos`. Os downloads usam o
    padrão de `st.download_button` — sem dependência de backend de arquivo.

    Gate 2 (auditoria Sprint 7): Excel/PDF são limitados a
    `exportacao_max_linhas` linhas (config) para evitar DoS de memória/CPU
    com datasets grandes; o CSV mantém o dataset completo. Quando o
    DataFrame excede o teto, um aviso informa que a exportação é parcial.
    """
    if df.empty:
        st.info("Sem dados para exibir.")
        return

    st.dataframe(df)

    from pipeline.config import get_dashboard

    max_linhas = get_dashboard().exportacao_max_linhas
    formato_parcial = len(df) > max_linhas

    formatos = set(formatos or ["csv", "excel", "pdf"])
    if "csv" in formatos:
        st.download_button(
            "📥 Exportar CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name=f"{nome_arquivo}.csv",
            mime="text/csv",
        )
    if formato_parcial and (formatos & {"excel", "pdf"}):
        st.caption(
            f"⚠️ Dataset com {len(df):,} linhas — Excel/PDF são limitados às "
            f"{max_linhas:,} primeiras (CSV exporta tudo)."
        )
    if "excel" in formatos:
        try:
            import io

            buf = io.BytesIO()
            df.head(max_linhas).to_excel(buf, index=False)
            st.download_button(
                "📥 Exportar Excel",
                buf.getvalue(),
                file_name=f"{nome_arquivo}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except ImportError:
            st.caption("Excel indisponível (instale o extra `dashboard` com openpyxl).")
    if "pdf" in formatos:
        try:
            import io

            import matplotlib.pyplot as plt

            parcial = df.head(max_linhas)
            fig, ax = plt.subplots(figsize=(10, max(2, 0.3 * len(parcial) + 1)))
            ax.axis("off")
            ax.table(
                cellText=parcial.round(2).astype(str).values,
                colLabels=parcial.columns,
                loc="center",
                cellLoc="left",
            )
            buf = io.BytesIO()
            fig.savefig(buf, format="pdf", bbox_inches="tight")
            plt.close(fig)
            st.download_button(
                "📥 Exportar PDF",
                buf.getvalue(),
                file_name=f"{nome_arquivo}.pdf",
                mime="application/pdf",
            )
        except ImportError:
            st.caption("PDF indisponível (instale matplotlib).")
