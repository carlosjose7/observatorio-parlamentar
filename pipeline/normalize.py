"""pipeline/normalize.py — normalização multi-fonte (ADR-016).

Concentra, em um único módulo de funções puras e testáveis isoladamente,
a lógica de parsing/normalização das fontes divergentes de data e valor
monetário entre Câmara (ISO 8601 + float), Senado e CGU (DD/MM/AAAA +
string pt-BR com vírgula decimal, CGU com separador de milhar).

Regra central (ADR-016): valores não-parseáveis **nunca lançam exceção**
que interrompa o pipeline — resultam em `None` + log estruturado. A
detecção e o reporte de falhas de parsing são responsabilidade do gate
Pandera (ADR-013) via `pipeline/quality.py`, não do parser.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import structlog

logger = structlog.get_logger()

_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
)
_PTBR_FORMAT = "%d/%m/%Y"


def parse_date_multi_format(
    valor: str | None,
    formatos: tuple[str, ...] | None = None,
) -> date | None:
    """Converte uma string de data para `date` em múltiplos formatos.

    Aceita ISO 8601 (Câmara) e DD/MM/AAAA (Senado, CGU). Ordem de
    tentativa: formatos explícitos (se fornecidos), depois os padrões
    ISO e pt-BR. Valor vazio/nulo ou não parseável retorna `None` +
    log estruturado — nunca lança (ADR-016).

    Args:
        valor: String de data bruta.
        formatos: Tuple de formatos `strftime` a tentar antes dos
            padrões (default: ISO + pt-BR).

    Returns:
        Objeto `date`, ou `None` se não for possível interpretar.
    """
    if not valor or not valor.strip():
        return None

    candidatos = formatos or (*_ISO_FORMATS, _PTBR_FORMAT)
    texto = valor.strip()

    for fmt in candidatos:
        try:
            parsed = datetime.strptime(texto, fmt)
        except ValueError:
            continue
        logger.debug("data_parseada", valor=valor, formato=fmt)
        return parsed.date()

    logger.warning("data_nao_parseada", valor=valor)
    return None


def parse_decimal_ptbr(valor: str | None) -> Decimal | None:
    """Converte string monetária pt-BR para `Decimal` com precisão.

    Aceita vírgula decimal (Senado, CGU) com ou sem separador de
    milhar, e ponto decimal (Câmara quando string). A regra de
    desambiguação: se a string contém vírgula, ela é o separador
    decimal e os pontos são milhares; se contém apenas ponto com
    exatamente duas casas, é ponto decimal; caso contrário os pontos
    são milhares. Valor não interpretável retorna `None` + log —
    nunca lança (ADR-016).

    Args:
        valor: String monetária bruta (ex: "1.234,56", "12,50", "0").

    Returns:
        `Decimal` ou `None` se a string não for interpretável.
    """
    if valor is None:
        return None
    texto = valor.strip()
    if not texto:
        return None

    if "," in texto:
        normalizado = texto.replace(".", "").replace(",", ".")
    elif "." in texto:
        partes = texto.split(".")
        if len(partes[-1]) == 2 and len(partes) == 2:
            normalizado = texto  # "1234.56" — ponto decimal
        else:
            normalizado = texto.replace(".", "")  # "1.234" — milhar
    else:
        normalizado = texto

    try:
        return Decimal(normalizado)
    except InvalidOperation:
        logger.warning("decimal_nao_parseado", valor=valor)
        return None


def clean_document_number(valor: str | None) -> str | None:
    """Sanitiza um campo CNPJ/CPF removendo formatação não numérica.

    Remove pontos, barras, hífens e espaços, retornando apenas os
    dígitos (ADR-011, passo de sanitização). Ausência retorna
    `None`. Não classifica o comprimento — isso é responsabilidade
    de `pipeline.contracts.resolve_tipo_documento`.

    Args:
        valor: String formatada (ex: "00.000.000/0001-91", "123.456").

    Returns:
        String com apenas dígitos, ou `None` se vazio.
    """
    if not valor or not valor.strip():
        return None
    digitos = "".join(char for char in valor.strip() if char.isdigit())
    if not digitos:
        return None
    return digitos


def normalizar_nome_proprio(valor: str | None) -> str | None:
    """Normaliza um nome próprio para maiúsculas e sem acentos.

    Aplicado a `nome_autor` na CGU (schema_silver_emenda, quality.py):
    o uppercase + remoção de diacríticos padroniza a grafia do autor para a
    futura comparação com `dim_parlamentar` no Gold (ADR-017). Valor vazio
    ou nulo retorna `None`.

    Args:
        valor: Nome bruto (ex: "João da Silva").

    Returns:
        Nome em maiúsculas sem acentos, ou `None` se vazio.
    """
    if not valor or not valor.strip():
        return None
    maiusculos = valor.strip().upper()
    decomposto = unicodedata.normalize("NFD", maiusculos)
    return "".join(
        char for char in decomposto if not unicodedata.combining(char)
    )
