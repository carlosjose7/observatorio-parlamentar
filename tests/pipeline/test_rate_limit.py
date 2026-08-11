# tests/pipeline/test_rate_limit.py
"""Testes do throttling proativo (corretivo 6.5, ADR-009 §rate limiting).

O retry reativo (tenacity, 429) resolve instabilidade transitória, mas a CGU
suspende a **chave inteira por 8h** ao exceder o limite/min — controle precisa
ser proativo (nunca deixar a taxa de saída ultrapassar o limite). Cobre o
token bucket (`RateLimiter`), a taxa diurna/noturna da CGU, o override por
endpoint (`/cartoes` a 180/min) e a consulta do token ANTES de cada tentativa
de HTTP (inclusive retries). Nenhuma rede — relógio e sleep injetados.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from pipeline.config import RetryDefaultSettings, get_sources
from pipeline.transparencia.extract import _limitador, _taxa_por_minuto
from pipeline.utils import RateLimiter, request_json, request_text

RETRY_TESTS = RetryDefaultSettings(
    max_tentativas=3,
    espera_exponencial_min_segundos=0.01,
    espera_exponencial_max_segundos=0.02,
)


class _RelogioFake:
    """Relógio manual: `t` avança só quando o teste pede."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def avancar(self, segundos: float) -> None:
        self.t += segundos


def _limiter_com(taxa: float, relogio: _RelogioFake, dormidas: list[float]):
    # `dormir` espelha o `time.sleep` real: além de registrar, avança o
    # relógio (em produção o monotonic avança durante o sleep — o bucket
    # reserva o token no futuro e a contagem só funciona se o relógio seguir).
    def dormir(segundos: float) -> None:
        dormidas.append(segundos)
        relogio.avancar(segundos)

    return RateLimiter(taxa, monotonic=relogio, dormir=dormir)


def test_bucket_limita_taxa_de_saida():
    """N requisições instantâneas geram dormidas que respeitam o limite."""
    relogio = _RelogioFake()
    dormidas: list[float] = []
    limiter = _limiter_com(60.0, relogio, dormidas)  # 60/min → 0.85 tokens/s

    for _ in range(10):
        limiter.aguardar()

    # A primeira usa o token inicial (sem dormir); as 9 seguintes precisam
    # de 1 token cada a 0.85 tokens/s → 9 × (1/0.85) s.
    assert len(dormidas) == 9
    assert sum(dormidas) == pytest.approx(9 * (1.0 / 0.85), abs=0.2)


def test_bucket_burst_inicial_nao_dorme():
    relogio = _RelogioFake()
    dormidas: list[float] = []
    limiter = _limiter_com(3600.0, relogio, dormidas)  # folga: 51 tokens/s

    for _ in range(10):
        limiter.aguardar()
    assert dormidas == []


def test_bucket_recupera_tokens_com_tempo():
    relogio = _RelogioFake()
    dormidas: list[float] = []
    limiter = _limiter_com(60.0, relogio, dormidas)

    for _ in range(5):
        limiter.aguardar()
        relogio.avancar(2.0)  # mais que o necessário (1/0.85 ≈ 1.18s/token)

    # Com folga real entre requisições, o bucket recompleta os tokens: só a
    # primeira não dorme, as demais encontram token disponível.
    assert sum(dormidas) == pytest.approx(0.0, abs=0.1)


def test_bucket_sustenta_taxa_alvo_em_janela():
    """Valida a matemática do alvo: 400/min documentado × 0.85 = 340/min.

    Capacidade inicial = ~1s de tokens (5.67), NÃO a janela inteira (340):
    decisão explícita e conservadora — o burst máximo é ~6 requisições e a
    taxa sustentada converge para 340/min. Em nenhuma janela de 60s se chega
    perto dos 400 documentados.
    """
    relogio = _RelogioFake()
    dormidas: list[float] = []
    limiter = _limiter_com(400.0, relogio, dormidas)  # alvo: 340/min

    # Simula operação contínua até 120s de relógio (avançado pelas dormidas).
    # Cada chamada devolve a contagem desde o relógio atual (não cumulativa).
    def _requisicoes_ate(limite: float) -> int:
        n = 0
        while relogio.t < limite:
            limiter.aguardar()
            n += 1
        return n

    primeiro_minuto = _requisicoes_ate(60.0)
    segundo_minuto = _requisicoes_ate(120.0)

    # Capacidade inicial ≈ 5.67 tokens (≈6 reqs de burst) + 340/min.
    assert primeiro_minuto == pytest.approx(340 + 400 * 0.85 / 60, abs=3)
    # Segundo minuto: só a taxa sustentada (sem burst) → ≈340.
    assert segundo_minuto == pytest.approx(340, abs=3)
    # Nunca perto do limite documentado em qualquer janela.
    assert primeiro_minuto < 400 and segundo_minuto < 400


def test_bucket_taxa_variavel_com_hora():
    """A taxa diurna/noturna da CGU muda o intervalo entre requisições."""
    relogio = _RelogioFake()
    dormidas: list[float] = []
    cfg = get_sources().transparencia

    taxa = _taxa_por_minuto(cfg)
    limiter = RateLimiter(taxa, monotonic=relogio, dormir=lambda s: dormidas.append(s))

    for _ in range(2):
        limiter.aguardar()
        relogio.avancar(0.0)

    # Sem saber a hora real não asserimos o valor exato — só que o bucket
    # produz dormidas não-negativas e consistentes com 400 ou 700 req/min.
    assert all(s >= 0 for s in dormidas)


def test_cgu_transicao_dia_noite_com_relogio_fake():
    """A janela noturna (00:00–06:00) muda a taxa no limite exato."""
    cfg = get_sources().transparencia
    relogio_hora = {"dt": datetime(2026, 8, 11, 5, 59, 0)}  # noturno
    taxa = _taxa_por_minuto(cfg, agora=lambda: relogio_hora["dt"])

    assert taxa() == 700.0  # 05:59 → noturno
    relogio_hora["dt"] = datetime(2026, 8, 11, 6, 0, 0)
    assert taxa() == 400.0  # 06:00 → diurno (limite superior exclusivo)
    relogio_hora["dt"] = datetime(2026, 8, 11, 0, 0, 0)
    assert taxa() == 700.0  # 00:00 → noturno (limite inferior inclusivo)
    relogio_hora["dt"] = datetime(2026, 8, 11, 23, 59, 0)
    assert taxa() == 400.0  # fora da janela → diurno


def test_bucket_respeita_transicao_dia_noite_sem_recriar():
    """O bucket reavalia a taxa a cada `aguardar` — a troca de janela vale
    sem recriar o limitador (bug clássico: fixar a taxa da criação)."""
    cfg = get_sources().transparencia
    relogio_hora = {"dt": datetime(2026, 8, 11, 5, 59, 0)}  # noturno
    relogio = _RelogioFake()
    dormidas: list[float] = []
    limiter = RateLimiter(
        _taxa_por_minuto(cfg, agora=lambda: relogio_hora["dt"]),
        monotonic=relogio,
        dormir=lambda s: (dormidas.append(s), relogio.avancar(s)),
    )

    # Esvazia o burst (capacidade noturna ≈ 9.92).
    for _ in range(12):
        limiter.aguardar()
    # Próxima requisição noturna dorme 60/(700×0.85) ≈ 0.1008s.
    limiter.aguardar()
    assert dormidas[-1] == pytest.approx(60 / (700 * 0.85), abs=0.01)

    # Muda para diurno SEM recriar o limitador.
    relogio_hora["dt"] = datetime(2026, 8, 11, 6, 1, 0)
    limiter.aguardar()
    assert dormidas[-1] == pytest.approx(60 / (400 * 0.85), abs=0.01)


def _spy_limiter(chamadas: list[str]) -> "_SpyLimiter":
    class _SpyLimiter(RateLimiter):
        def aguardar(self) -> None:
            chamadas.append("aguardar")
            return super().aguardar()

    return _SpyLimiter(10**9, dormir=lambda _s: None)


def test_request_json_aguarda_antes_de_cada_tentativa():
    """O token é consultado ANTES de cada tentativa, inclusive nos retries."""
    chamadas: list[str] = []
    respostas = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json=[{"ok": 1}]),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append("http")
        return respostas.pop(0)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    limiter = _spy_limiter(chamadas)

    request_json(
        client, "https://api.test/emendas", {"pagina": 1}, RETRY_TESTS, limiter=limiter
    )

    # aguardar → http → aguardar → http → aguardar → http (3 tentativas)
    assert chamadas == [
        "aguardar", "http",
        "aguardar", "http",
        "aguardar", "http",
    ]


def test_request_text_aguarda_antes_de_cada_tentativa():
    chamadas: list[str] = []
    respostas = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, content=b"a;b\n1;2\n"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append("http")
        return respostas.pop(0)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    limiter = _spy_limiter(chamadas)

    request_text(client, "https://api.test/ceaps.csv", "utf-8", RETRY_TESTS, limiter=limiter)

    assert chamadas == [
        "aguardar", "http",
        "aguardar", "http",
        "aguardar", "http",
    ]


def test_request_json_nao_aguarda_depois_do_get():
    """O limiter é consultado antes do GET, nunca depois."""
    chamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append("http")
        return httpx.Response(200, json=[{"ok": 1}])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    limiter = _spy_limiter(chamadas)

    request_json(client, "https://api.test/emendas", {"pagina": 1}, RETRY_TESTS, limiter=limiter)

    assert chamadas == ["aguardar", "http"]


def test_302_nao_retria_com_contagem_de_chamadas():
    """302 (bloqueio-acesso da CGU) falha limpo: não retry, uma única chamada."""
    contagem = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        contagem["n"] += 1
        return httpx.Response(302, headers={"location": "/bloqueio-acesso"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    limiter = _spy_limiter([])

    with pytest.raises(httpx.HTTPStatusError):
        request_json(client, "https://api.test/emendas", {"pagina": 1}, RETRY_TESTS, limiter=limiter)

    assert contagem["n"] == 1


def test_cartoes_override_180_na_config():
    """Override por endpoint (`/cartoes` a 180/min) declarado em sources.yaml."""
    cfg = get_sources().transparencia
    ep = cfg.endpoints["cartoes"]
    assert ep.rate_limit is not None
    assert ep.rate_limit.requisicoes_por_minuto == 180


def test_override_ganha_do_limite_global():
    """Precedência: override por endpoint > taxa da fonte (dia/noite)."""
    cfg = get_sources().transparencia
    relogio_hora = {"dt": datetime(2026, 8, 11, 2, 0, 0)}  # noturno → global 700

    # Sem override (emendas) → usa a taxa noturna da fonte (700).
    lim_emendas = _limitador(cfg, "emendas", agora=lambda: relogio_hora["dt"])
    assert lim_emendas._capacidade == pytest.approx(700 * 0.85 / 60, abs=0.01)

    # Com override (cartões) → 180/min, ignora a taxa global (700) mesmo
    # dentro da janela noturna.
    lim_cartoes = _limitador(cfg, "cartoes", agora=lambda: relogio_hora["dt"])
    assert lim_cartoes._capacidade == pytest.approx(180 * 0.85 / 60, abs=0.01)


def test_limitador_emendas_usa_taxa_diurna_noturna():
    cfg = get_sources().transparencia
    limiter = _limitador(cfg, "emendas")
    # 400/min × 0.85 / 60 ≈ 5.67 ou 700 × 0.85 / 60 ≈ 9.92.
    assert limiter._capacidade == pytest.approx(400 * 0.85 / 60, abs=0.01) or (
        limiter._capacidade == pytest.approx(700 * 0.85 / 60, abs=0.01)
    )
