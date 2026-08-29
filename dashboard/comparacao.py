"""dashboard/comparacao.py — utilitários de comparabilidade de período (Sprint 12).

Fornece cálculo de interseção temporal entre dois parlamentares para
garantir comparação justa na Batalha Parlamentar (Página 12).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SobreposicaoPeriodo:
    """Resultado do cálculo de sobreposição entre dois períodos."""

    inicio_a: str | None
    fim_a: str | None
    inicio_b: str | None
    fim_b: str | None
    inicio_comum: str | None
    fim_comum: str | None
    pct_cobertura: float  # 0.0 a 1.0 — % do menor período coberta pela interseção


def _parse_mes(mes: str | None) -> tuple[int, int] | None:
    """Converte 'YYYY-MM' ou 'YYYY-MM-DD' para (ano, mês)."""
    if not mes:
        return None
    partes = mes[:10].split("-")
    try:
        return int(partes[0]), int(partes[1])
    except (ValueError, IndexError):
        return None


def _meses_para_str(ano: int, mes: int) -> str:
    """(2023, 7) → '2023-07'."""
    return f"{ano:04d}-{mes:02d}"


def calcular_sobreposicao(
    janela_inicio_a: str | None,
    janela_fim_a: str | None,
    janela_inicio_b: str | None,
    janela_fim_b: str | None,
) -> SobreposicaoPeriodo:
    """Calcula a interseção temporal entre os períodos de dois parlamentares.

    Os parâmetros são strings no formato 'YYYY-MM' ou 'YYYY-MM-DD'
    (compatível com `janela_inicio`/`janela_fim` do endpoint agent).

    Retorna `SobreposicaoPeriodo` com a interseção e o percentual de cobertura.
    Se não houver sobreposição, `inicio_comum`/`fim_comum` são None e
    `pct_cobertura` é 0.0.
    """
    a = _parse_mes(janela_inicio_a)
    b_fim = _parse_mes(janela_fim_a)
    b = _parse_mes(janela_inicio_b)
    d = _parse_mes(janela_fim_b)

    # Se ambos os lados têm dados, calcula interseção
    if a and b_fim and b and d:
        # Início = max dos inícios
        inicio = (max(a[0], b[0]), max(a[1], b[1]))
        # Fim = min dos fins
        fim = (min(b_fim[0], d[0]), min(b_fim[1], d[1]))

        # Total de meses de cada lado
        total_a = (b_fim[0] - a[0]) * 12 + (b_fim[1] - a[1]) + 1
        total_b = (d[0] - b[0]) * 12 + (d[1] - b[1]) + 1
        menor_total = min(total_a, total_b)

        if inicio <= fim and menor_total > 0:
            meses_comum = (fim[0] - inicio[0]) * 12 + (fim[1] - inicio[1]) + 1
            pct = meses_comum / menor_total
            return SobreposicaoPeriodo(
                inicio_a=_meses_para_str(*a),
                fim_a=_meses_para_str(*b_fim),
                inicio_b=_meses_para_str(*b),
                fim_b=_meses_para_str(*d),
                inicio_comum=_meses_para_str(*inicio),
                fim_comum=_meses_para_str(*fim),
                pct_cobertura=min(1.0, pct),
            )

    # Sem interseção ou dados incompletos — retorna o que tem
    return SobreposicaoPeriodo(
        inicio_a=_meses_para_str(*a) if a else None,
        fim_a=_meses_para_str(*b_fim) if b_fim else None,
        inicio_b=_meses_para_str(*b) if b else None,
        fim_b=_meses_para_str(*d) if d else None,
        inicio_comum=None,
        fim_comum=None,
        pct_cobertura=0.0,
    )
