"""analytics/parliamentarians/analytics.py — estatística descritiva e correlações (Sprint 5, Onda 1).

Implementa a Onda 1 de Analytics (PROJECT_CONTEXT §13): estatística
descritiva e correlações que alimentam as features registradas na
Feature Store (ADR-028) e os scores do ADR-027. Esta primeira camada é
pura e determinística (sem ML) — o reservado para as Ondas 2/3
(Isolation Forest, NetworkX).

Cada função consome um DataFrame de fatos Gold (ex: `fact_despesa`) no
grão correto e devolve métricas que correspondem a features do registry
(ADR-028). O contrato de features é validado por `analytics/features.py`;
estas funções apenas documentam, via log estruturado, quais features do
registry consomem.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog

from analytics.features import carregar_registry

logger = structlog.get_logger()


@dataclass
class ResumoEstatistico:
    """Estatística descritiva de uma série monetária (métricas §7/§8).

    Attributes:
        contagem: Número de observações não nulas.
        media: Média aritmética (métrica `gasto_medio`).
        mediana: Mediana (métrica `valor_mediano`).
        desvio_padrao: Desvio padrão populacional.
        minimo / maximo: Extremos observados.
        percentil_95: Percentil 95 (métrica `percentil_95`).
    """

    contagem: int
    media: float
    mediana: float
    desvio_padrao: float
    minimo: float
    maximo: float
    percentil_95: float


def resumo_estatistico(serie: pd.Series) -> ResumoEstatistico:
    """Calcula estatística descritiva de uma série numérica.

    Usada para descrever distribuições de valores monetários de fatos
    (ex: `valor_liquido` de `fact_despesa`) — insumo das features de
    estatística descritiva do registry e dos percentis §8.

    Args:
        serie: Série numérica de valores (nulos são ignorados).

    Returns:
        `ResumoEstatistico` com as métricas descritivas.

    Raises:
        ValueError: Se a série for vazia ou conter apenas nulos.
    """
    valores = pd.to_numeric(serie, errors="coerce").dropna()
    if valores.empty:
        raise ValueError("série vazia — impossível calcular estatística descritiva")

    percentil_95 = np.percentile(valores, 95)
    return ResumoEstatistico(
        contagem=int(valores.size),
        media=float(valores.mean()),
        mediana=float(valores.median()),
        desvio_padrao=float(valores.std(ddof=0)),
        minimo=float(valores.min()),
        maximo=float(valores.max()),
        percentil_95=float(percentil_95),
    )


def correlacao_pearson(
    colunas: Iterable[str], fatos: pd.DataFrame
) -> dict[str, dict[str, float]]:
    """Correlação de Pearson entre pares de colunas numéricas dos fatos.

    Insumo de dependências entre métricas (ex: total gasto x número de
    fornecedores por parlamentar) — alimenta o entendimento das
    features do ADR-027 antes de qualquer ML.

    Args:
        colunas: Nomes das colunas numéricas a correlacionar.
        fatos: DataFrame Gold (ex: `fact_despesa`) contendo as colunas.

    Returns:
        Dicionário `{coluna_a: {coluna_b: r}}` com a matriz triangular
        superior (r em [-1, 1]). Pares com variância nula resultam em
        `nan`.
    """
    colunas_validas = [
        c for c in colunas if c in fatos.columns and pd.api.types.is_numeric_dtype(fatos[c])
    ]
    if len(colunas_validas) < 2:
        return {}
    matriz = fatos[colunas_validas].corr(method="pearson")
    resultado: dict[str, dict[str, float]] = {}
    for i, a in enumerate(colunas_validas):
        resultado[a] = {}
        for b in colunas_validas[i + 1 :]:
            valor = float(matriz.loc[a, b])
            resultado[a][b] = np.nan if np.isnan(valor) else valor
    return resultado


def normalizar_minmax(serie: pd.Series) -> pd.Series:
    """Normalização Min-Max para [0, 1] — feature `minmax` (ADR-028).

    Executa a função derivada `minmax` registrada na Feature Store
    (`feature_store/registry.yaml`, ADR-028): `norm(x) = (x − min_X(x)) /
    (max_X(x) − min_X(x))` no universo `X` do período (ADR-003/ADR-027).
    É a implementação REUTILIZÁVEL da feature — o módulo de scores
    (`analytics/parliamentarians/risk.py`) consome esta função; nada de versão solta.

    Args:
        serie: Série numérica com os valores crus de um score no universo
            do período (nulos são ignorados no cálculo dos extremos).

    Returns:
        Série normalizada em [0, 1]. Série constante (min == max) →
        todos os valores viram `0.0` (sem informação de escala); série
        vazia → série vazia.
    """
    valores = pd.to_numeric(serie, errors="coerce").astype(float)
    if valores.empty:
        return serie.iloc[0:0].copy()
    minimo, maximo = float(valores.min()), float(valores.max())
    if maximo == minimo:
        # Série constante (raw idêntico no universo do período): norm é
        # 0/0 indefinida — mapear para 0.0 preserva a ordenação (todos
        # iguais entre si) e não infla o risk_index de ninguém.
        resultado = pd.Series(0.0, index=valores.index)
        resultado.loc[valores.isna()] = np.nan
        return resultado
    return (valores - minimo) / (maximo - minimo)


def resumo_por_parlamentar(
    fatos: pd.DataFrame,
    coluna_valor: str = "valor_liquido",
    coluna_fornecedor: str = "id_fornecedor",
    coluna_id: str = "id_parlamentar",
) -> pd.DataFrame:
    """Agrega métricas de gasto por parlamentar (insumo do ADR-027).

    Para cada parlamentar, calcula `total_gasto`, `num_fornecedores`,
    `ticket_medio`, `gasto_medio` e `percentil_95` — métricas §8 que
    entram como features derivadas no cálculo dos scores de
    concentração/dependência.

    Args:
        fatos: DataFrame Gold no grão de fato (uma linha por despesa).
        coluna_valor: Coluna de valor monetário.
        coluna_fornecedor: Coluna de id do fornecedor (pode conter nulos).
        coluna_id: Coluna de id do parlamentar.

    Returns:
        DataFrame no grão parlamentar com as métricas agregadas.
    """
    if fatos.empty:
        return pd.DataFrame(
            columns=[
                coluna_id,
                "total_gasto",
                "num_fornecedores",
                "ticket_medio",
                "gasto_medio",
                "percentil_95",
            ]
        )

    valores = pd.to_numeric(fatos[coluna_valor], errors="coerce").fillna(0.0)
    trabalho = fatos.assign(_valor=valores, _parlamentar=fatos[coluna_id].astype("object"))
    agrupado = trabalho.groupby("_parlamentar")

    resultado = agrupado.agg(
        total_gasto=("_valor", "sum"),
        num_fornecedores=(coluna_fornecedor, "nunique"),
        ticket_medio=("_valor", "mean"),
        gasto_medio=("_valor", "mean"),
    ).reset_index()
    percentil_95 = agrupado["_valor"].apply(
        lambda g: float(np.percentile(g, 95))
    )
    resultado["percentil_95"] = percentil_95.reset_index(drop=True).to_numpy()
    resultado = resultado.rename(columns={"_parlamentar": coluna_id})
    return resultado


def validar_features_no_registry(registry_path: str | None = None) -> list[str]:
    """Conferência de rastreabilidade: features que o registry declara.

    Consulta o `feature_store/registry.yaml` via `analytics/features.py`
    (ADR-028) e devolve os nomes de features que hoje são consumidas
    pela camada analítica (scores do ADR-027). Serve de guarda
    documental: qualquer score calculado sem registro no registry deve
    aparecer na diferença entre este retorno e o que a Onda 4 consumir.

    Args:
        registry_path: Caminho alternativo do registry (para testes).

    Returns:
        Lista (ordenada) dos nomes de features registrados.
    """
    from pathlib import Path

    registry = carregar_registry(Path(registry_path) if registry_path else None)
    nomes = sorted(f.nome for f in registry.features)
    logger.info("features_ativas", total=len(nomes), features=nomes)
    return nomes
