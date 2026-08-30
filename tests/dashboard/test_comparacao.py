"""tests/dashboard/test_comparacao.py — testes unitários de comparabilidade de período (Sprint 12).

Valida `calcular_sobreposicao()` com os cenários do checklist
de smoke test (4.C), incluindo boundary conditions em 75%.

Denominador = menor período (ADR-041): mede quanto do mandato
MENOR é coberto pela interseção. Se o parlamentar com menos dados
não está inteiramente na interseção, a comparação é enviesada.
"""

from __future__ import annotations

import pytest

from dashboard.comparacao import calcular_sobreposicao


class TestCalcularSobreposicao:
    """Casos de teste para cálculo de interseção temporal."""

    def test_periodos_identicos(self) -> None:
        """Mesmo período: 100% de cobertura, sem disclaimer."""
        r = calcular_sobreposicao("2019-01", "2023-12", "2019-01", "2023-12")
        assert r.inicio_comum == "2019-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == 1.0

    def test_b_dentro_de_a(self) -> None:
        """B totalmente contido em A: 100% (menor = B = interseção), sem disclaimer."""
        r = calcular_sobreposicao("2019-01", "2023-12", "2020-01", "2023-12")
        assert r.inicio_comum == "2020-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == 1.0  # 48/48 (menor = B)

    def test_a_dentro_de_b(self) -> None:
        """A totalmente contido em B: 100% (menor = A = interseção), sem disclaimer."""
        r = calcular_sobreposicao("2020-01", "2023-12", "2019-01", "2024-12")
        assert r.inicio_comum == "2020-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == 1.0  # 48/48 (menor = A)

    def test_sobreposicao_parcial_acima_do_limiar(self) -> None:
        """B começa antes de A, termina junto: 75% (36/48), sem disclaimer.

        A: 2019-01 a 2023-12 (60 meses)
        B: 2018-01 a 2023-12 (72 meses)
        Interseção: 2019-01 a 2023-12 (60 meses)
        menor = 60 (A), pct = 60/60 = 100% — B é maior, A é menor.
        """
        r = calcular_sobreposicao("2019-01", "2023-12", "2018-01", "2023-12")
        assert r.inicio_comum == "2019-01"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == 1.0  # 60/60

    def test_sobreposicao_parcial_abaixo_do_limiar(self) -> None:
        """Interseção parcial: 71% (30/42) < 75%, disclaimer DEVE aparecer.

        A: 2019-01 a 2023-12 (60 meses)
        B: 2021-07 a 2024-12 (42 meses)
        Interseção: 2021-07 a 2023-12 (30 meses)
        menor = 42 (B), pct = 30/42 ≈ 71.4%
        """
        r = calcular_sobreposicao("2019-01", "2023-12", "2021-07", "2024-12")
        assert r.inicio_comum == "2021-07"
        assert r.fim_comum == "2023-12"
        assert r.pct_cobertura == pytest.approx(0.714, abs=0.02)
        assert r.pct_cobertura < 0.75

    def test_sobreposicao_muito_abaixo(self) -> None:
        """Interseção pequena: 50% (24/48) < 75%, disclaimer.

        A: 2019-01 a 2023-12 (60 meses)
        B: 2022-01 a 2025-12 (48 meses)
        Interseção: 2022-01 a 2023-12 (24 meses)
        menor = 48 (B), pct = 24/48 = 50%
        """
        r = calcular_sobreposicao("2019-01", "2023-12", "2022-01", "2025-12")
        assert r.pct_cobertura == pytest.approx(0.5, abs=0.01)

    def test_sem_dados(self) -> None:
        """Sem janelas: sem sobreposição."""
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

        A: 2019-01 a 2022-12 (48 meses)
        B: 2020-01 a 2022-12 (36 meses)
        Interseção: 2020-01 a 2022-12 (36 meses)
        menor = 36 (B), pct = 36/36 = 100%
        → Precisamos de um cenário onde o menor NÃO é a interseção.

        A: 2019-01 a 2022-12 (48 meses)
        B: 2019-01 a 2023-09 (45 meses)
        Interseção: 2019-01 a 2022-12 (48 meses? não — B termina antes)
        B termina em 2023-09, A termina em 2022-12 → interseção = 2019-01 a 2022-12 = 48 meses
        menor = 45 (B)? não — A=48, B=45, menor=45, interseção=45? não...

        Vamos direto:
        A: 2020-01 a 2022-12 (36 meses)
        B: 2019-01 a 2022-12 (48 meses)
        Interseção: 2020-01 a 2022-12 (36 meses)
        menor = 36 (A), pct = 36/36 = 100% — A é menor e está totalmente na interseção.

        Para ter 75% com min, precisamos que o menor NÃO esteja contido:
        A: 2020-01 a 2023-12 (48 meses)
        B: 2019-01 a 2022-06 (42 meses)
        Interseção: 2020-01 a 2022-06 (30 meses)
        menor = 42 (B), pct = 30/42 ≈ 71.4%

        Para 75% exato:
        A: 2020-01 a 2023-12 (48 meses)
        B: 2019-01 a 2022-09 (45 meses)
        Interseção: 2020-01 a 2022-09 (33 meses)
        menor = 45, pct = 33/45 ≈ 73.3%

        A: 2020-01 a 2023-12 (48 meses)
        B: 2019-01 a 2022-12 (48 meses)
        Interseção: 2020-01 a 2022-12 (36 meses)
        menor = 48, pct = 36/48 = 75% exato.
        """
        r = calcular_sobreposicao("2020-01", "2023-12", "2019-01", "2022-12")
        assert r.inicio_comum == "2020-01"
        assert r.fim_comum == "2022-12"
        assert r.pct_cobertura == pytest.approx(0.75, abs=0.01)
        assert r.pct_cobertura >= 0.75  # boundary: NÃO ativa disclaimer

    def test_boundary_74_pct(self) -> None:
        """Boundary: ~73% < 75% — disclaimer DEVE ativar.

        A: 2020-01 a 2023-12 (48 meses)
        B: 2019-01 a 2022-11 (47 meses)
        Interseção: 2020-01 a 2022-11 (35 meses)
        menor = 47 (B), pct = 35/47 ≈ 74.5%
        → Ainda >= 75%... vamos ajustar.

        A: 2020-01 a 2023-12 (48 meses)
        B: 2019-01 a 2022-10 (46 meses)
        Interseção: 2020-01 a 2022-10 (34 meses)
        menor = 46, pct = 34/46 ≈ 73.9%
        """
        r = calcular_sobreposicao("2020-01", "2023-12", "2019-01", "2022-10")
        assert r.pct_cobertura == pytest.approx(0.739, abs=0.02)
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

    def test_cenario_original_plano(self) -> None:
        """Cenário do plano: mandato longo (A) vs mandato curto (B) contido.

        A: 2019-01 a 2023-12 (60 meses)
        B: 2021-01 a 2023-12 (36 meses, totalmente contido em A)
        Interseção: 36 meses = 36/36 = 100% (menor = B)
        → Sem disclaimer (B inteiro está na comparação).
        """
        r = calcular_sobreposicao("2019-01", "2023-12", "2021-01", "2023-12")
        assert r.pct_cobertura == 1.0
        # B está totalmente contido — comparação é justa para B

    def test_cenario_original_parcial(self) -> None:
        """Cenário do plano: mandato longo (A) vs mandato curto (B) parcial.

        A: 2019-01 a 2023-12 (60 meses)
        B: 2021-07 a 2024-12 (42 meses, começa no meio, vai além)
        Interseção: 2021-07 a 2023-12 (30 meses)
        menor = 42 (B), pct = 30/42 ≈ 71.4% < 75%
        → Disclaimer: 29% dos dados de B ficam fora da comparação.
        """
        r = calcular_sobreposicao("2019-01", "2023-12", "2021-07", "2024-12")
        assert r.pct_cobertura == pytest.approx(0.714, abs=0.02)
        assert r.pct_cobertura < 0.75
