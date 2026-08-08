"""pipeline/parlamento.py — referência canônica do domínio parlamentar (ADR-024).

Duas fontes independentes de verdade alimentam `dim_parlamentar` (Câmara e
Senado), cada uma com vocabulário e semântica próprios. Este módulo
centraliza, como dados versionados (não heurística espalhada no código):

1. Calendário das legislaturas federais: cada observação (snapshot) tem uma
   `data` (as-of); a `id_legislatura` da Silver é **derivada da data** contra
   esse calendário — e nunca copiada da API. As APIS medem coisas diferentes
   por definição (Câmara: legislatura vigente em `ultimoStatus`; Senado:
   primeira/segunda do mandato de 8 anos), então copiar seria introduzir
   assimetria no histórico SCD2 de `dim_parlamentar`.

2. De-para de `situacao`: cada fonte tem vocabulário próprio (Câmara:
   situação de exercício em `ultimoStatus`; Senado: descrição de participação
   no mandato). A Silver guarda o valor bruto (`situacao_bruta`, auditável) e
   grava uma **taxonomia mínima comum** (`situacao_normalizada`) mapeada por
   tabela explícita. Vocabulário novo que ainda não consta → sentinela
   `nao_mapeado` (nunca NULL silencioso).

Ver ADR-024 para motivacao completa.
"""

from __future__ import annotations

import enum
import unicodedata
from datetime import date

# ── Legislas cars federais (1º fev de ano ímpar → 31 jan do próximo ímpar). ──
# Tuplas (numero, inicio, fim) com fim exclusivo. Baixo volume, estável.

LEGISLATURAS: tuple[tuple[int, date, date], ...] = (
    (54, date(2011, 2, 1), date(2015, 2, 1)),
    (55, date(2015, 2, 1), date(2019, 2, 1)),
    (56, date(2019, 2, 1), date(2023, 2, 1)),
    (57, date(2023, 2, 1), date(2027, 2, 1)),
    (58, date(2027, 2, 1), date(2031, 2, 1)),
)


def legislatura_para_data(data: date) -> int | None:
    """Número da legislatura vigente em `data` (ADR-024, derivação por calendário).

    Args:
        data: Data de vigência do snapshot (as-of).

    Returns:
        Número da legislatura, ou `None` se `data` estiver fora do calendário
        conhecido (retorna à quarentena pelo gate `gt(0)` da Silver).
    """
    for numero, inicio, fim in LEGISLATURAS:
        if inicio <= data < fim:
            return numero
    return None


# ── Taxonomia comum de situação de mandato (ADR-024) ─────────────


class SituacaoParlamentar(str, enum.Enum):
    """Vocabulário mínimo normalizado para `situacao_normalizada`.

    Traduz os vocabulários de Câmara e Senado para um enum comum usado no
    histórico SCD2 de `dim_parlament` (RF-11). `NAO_MAPEADO` é a sentinela
    para valores ainda não catalogados no de-para — a auditoria sempre
    consulta `situacao_bruta`.
    """

    ATIVO = "ativo"
    LICENCA = "licenca"
    AFASTADO = "afastado"
    FIM_MANDATO = "fim_mandato"
    NAO_MAPEADO = "nao_mapeado"


# De-para fonte → token normalizado → enum. Token normalizado = minúsculas
# sem acento (cf. ADR-016). Novo vocabulário observado deve ser adicionado
# aqui (com teste) — nunca estendendo a taxonomia inline nos transformadores.
_DE_PARA_SITUACAO: dict[str, dict[str, SituacaoParlamentar]] = {
    "camara": {
        "exercicio": SituacaoParlamentar.ATIVO,
        "em exercicio": SituacaoParlamentar.ATIVO,
        "licenca": SituacaoParlamentar.LICENCA,
        "licenca a pedido": SituacaoParlamentar.LICENCA,
        "suspenso": SituacaoParlamentar.AFASTADO,
        "suspensao": SituacaoParlamentar.AFASTADO,
        "fora do exercicio": SituacaoParlamentar.AFASTADO,
        "fora do trabalho": SituacaoParlamentar.AFASTADO,
        "cassado": SituacaoParlamentar.FIM_MANDATO,
        "renunciou": SituacaoParlamentar.FIM_MANDATO,
        "renuncia": SituacaoParlamentar.FIM_MANDATO,
        "fim de mandato": SituacaoParlamentar.FIM_MANDATO,
        "fim do mandato": SituacaoParlamentar.FIM_MANDATO,
        "vaga perdida": SituacaoParlamentar.FIM_MANDATO,
    },
    "senado": {
        "titular": SituacaoParlamentar.ATIVO,
        "suplente": SituacaoParlamentar.ATIVO,
        "senador em exercicio": SituacaoParlamentar.ATIVO,
    },
}

_VALORES_NORMALIZADOS: tuple[str, ...] = tuple(
    valor.value for valor in SituacaoParlamentar
)


def normalizar_situacao(casa: str, valor_bruto: str | None) -> str:
    """Traduz o vocabulário da fonte para `situacao_normalizada`.

    O valor bruto é preservado em `situacao_bruta`; esta função só produz o
    enum comum. Ausência ou vocabulário desconhecido → `nao_mapeado` (a
    auditoria consulta o bruto). Não levanta exceção (ADR-016 — o gate de
    qualidade captura, não o parser).
    """
    if not valor_bruto:
        return SituacaoParlamentar.NAO_MAPEADO.value
    chave = _normalizar_token(valor_bruto)
    return _DE_PARA_SITUACAO.get(casa, {}).get(
        chave, SituacaoParlamentar.NAO_MAPEADO
    ).value


def _normalizar_token(valor: str) -> str:
    """Minúsculas sem acento — chave de lookup no de-para."""
    texto = unicodedata.normalize("NFD", valor)
    sem_acento = "".join(
        char for char in texto if not unicodedata.combining(char)
    )
    return " ".join(sem_acento.lower().split())