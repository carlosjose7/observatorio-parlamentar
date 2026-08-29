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


def _de_total_meses(total: int) -> tuple[int, int]:
    """Converte meses totais (1-indexed) de volta para (ano, mes).

    Exemplos:
        24288 → (2023, 12)  # 2023*12 + 12
        24277 → (2023, 1)   # 2023*12 + 1
    """
    ano, mes = divmod(total, 12)
    if mes == 0:
        return ano - 1, 12
    return ano, mes


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
    O percentual é calculado como `meses_comum / menor_periodo` — mede quanto
    do mandato MENOR é coberto pela interseção. Se o parlamentar com menos
    dados não está inteiramente na interseção, a comparação é potencialmente
    enviesada. Se não houver sobreposição, `inicio_comum`/`fim_comum` são
    None e `pct_cobertura` é 0.0.
    """
    a = _parse_mes(janela_inicio_a)
    b_fim = _parse_mes(janela_fim_a)
    b = _parse_mes(janela_inicio_b)
    d = _parse_mes(janela_fim_b)

    # Se ambos os lados têm dados, calcula interseção
    if a and b_fim and b and d:
        # Converter para meses totais para comparação cronológica correta
        a_inicio = a[0] * 12 + a[1]
        a_fim = b_fim[0] * 12 + b_fim[1]
        b_inicio = b[0] * 12 + b[1]
        b_fim_total = d[0] * 12 + d[1]

        # Início = max dos inícios (em meses)
        inicio_meses = max(a_inicio, b_inicio)
        # Fim = min dos fins (em meses)
        fim_meses = min(a_fim, b_fim_total)

        # Total de meses de cada lado
        total_a = a_fim - a_inicio + 1
        total_b = b_fim_total - b_inicio + 1
        menor_total = min(total_a, total_b)

        if inicio_meses <= fim_meses and menor_total > 0:
            meses_comum = fim_meses - inicio_meses + 1
            pct = meses_comum / menor_total

            # Converter de volta para YYYY-MM
            ini_ano, ini_mes = _de_total_meses(inicio_meses)
            fim_ano, fim_mes = _de_total_meses(fim_meses)

            return SobreposicaoPeriodo(
                inicio_a=_meses_para_str(*a),
                fim_a=_meses_para_str(*b_fim),
                inicio_b=_meses_para_str(*b),
                fim_b=_meses_para_str(*d),
                inicio_comum=f"{ini_ano:04d}-{ini_mes:02d}",
                fim_comum=f"{fim_ano:04d}-{fim_mes:02d}",
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
