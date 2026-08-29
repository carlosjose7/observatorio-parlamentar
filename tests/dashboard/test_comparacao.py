"""tests/dashboard/test_comparacao.py — testes unitários de comparabilidade de período (Sprint 12).

Valida `calcular_sobreposicao()` com os cenários limite do checklist
de smoke test (4.C), incluindo boundary conditions em 75%.
"""

from __future__ import annotations

import pytest

from dashboard.comparacao import SobreposicaoPeriodo, calcular_sobreposicao


class TestCalcularSobreposicao:
    """Casos de teste para cálculo de interseção temporal."""

    def test_periodos_identicos(self) -> None:
        """4.C.1 — Mesmo período: 100% de cobertura, sem disclaimer."""
        r = calcular_sobreposicao("2019-01", "2023-12", "2019-01", "2023-12")
        assert r.inicio_comum == "2019-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == 1.0

    def test_um_dentro_do_outro(self) -> None:
        """4.C.2 — B dentro de A: 80% (48/60), sem disclaimer."""
        r = calcular_sobreposicao("2019-01", "2023-12", "2020-01", "2023-12")
        assert r.inicio_comum == "2020-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == pytest.approx(0.8, abs=0.01)

    def test_acima_do_limiar(self) -> None:
        """4.C.3 — 60% (36/60) < 75%: disclaimer DEVE aparecer."""
        r = calcular_sobreposicao("2019-01", "2023-12", "2021-01", "2023-12")
        assert r.inicio_comum == "2021-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == pytest.approx(0.6, abs=0.01)
        assert r.pct_cobertura < 0.75  # disclaimer deve ativar

    def test_bem_abaixo_do_limiar(self) -> None:
        """4.C.4 — 40% (24/60) < 75%: disclaimer."""
        r = calcular_sobreposicao("2019-01", "2023-12", "2022-01", "2023-12")
        assert r.inicio_comum == "2022-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == pytest.approx(0.4, abs=0.01)

    def test_sem_dados(self) -> None:
        """4.C.5 — Sem janelas: sem sobreposição."""
        r = calcular_sobreposicao(None, None, None, None)
        assert r.inicio_comum is None
        assert r.fim_comum is None
        assert r.pct_cobertura == 0.0

    def test_apenas_um_lado_com_dados(self) -> None:
        """Só A tem dados, B não."""
        r = calcular_sobreposicao("2020-01", "2023-12", None, None)
        assert r.inicio_comum is None
        assert r.fim_comum is None
        assert r.pct_cobertura == 0.0

    def test_sem_sobreposicao(self) -> None:
        """Períodos disjuntos: sem interseção."""
        r = calcular_sobreposicao("2015-01", "2018-12", "2020-01", "2023-12")
        assert r.inicio_comum is None
        assert r.fim_comum is None
        assert r.pct_cobertura == 0.0

    def test_boundary_75_pct_exato(self) -> None:
        """Boundary: exatamente 75% — sem disclaimer (>= 75%).

        A: 24 meses (2020-01 a 2021-12)
        B: 32 meses (2019-05 a 2021-12)
        Interseção: 24 meses = 24/32 = 75%
        """
        r = calcular_sobreposicao("2020-01", "2021-12", "2019-05", "2021-12")
        assert r.pct_cobertura == pytest.approx(0.75, abs=0.01)
        assert r.pct_cobertura >= 0.75  # boundary: NÃO ativa disclaimer

    def test_boundary_74_pct(self) -> None:
        """Boundary: ~73% < 75% — disclaimer DEVE ativar.

        A: 24 meses (2020-01 a 2021-12)
        B: 33 meses (2019-04 a 2021-12)
        Interseção: 24 meses = 24/33 ≈ 72.7%
        """
        r = calcular_sobreposicao("2020-01", "2021-12", "2019-04", "2021-12")
        assert r.pct_cobertura == pytest.approx(0.727, abs=0.02)
        assert r.pct_cobertura < 0.75

    def test_datas_com_dia(self) -> None:
        """Formato YYYY-MM-DD (compatível com janela_inicio/fim do agent)."""
        r = calcular_sobreposicao("2020-01-15", "2023-06-20", "2021-03-01", "2023-12-31")
        assert r.inicio_comum == "2021-03"
        assert r.fim_comum == "2023-06"
        assert r.pct_cobertura > 0.0

    def test_resultado_imutavel(self) -> None:
        """SobreposicaoPeriodo é dataclass frozen (imutável)."""
        r = calcular_sobreposicao("2020-01", "2023-12", "2021-01", "2023-12")
        with pytest.raises(AttributeError):
            r.pct_cobertura = 0.5  # type: ignore[misc]

    def test_a_menor_que_b(self) -> None:
        """A menor que B: interseção = A inteiro = 36/60 = 60%."""
        r = calcular_sobreposicao("2021-01", "2023-12", "2019-01", "2023-12")
        assert r.inicio_comum == "2021-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == pytest.approx(0.6, abs=0.01)
