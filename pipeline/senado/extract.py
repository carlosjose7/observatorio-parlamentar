"""Extração de dados do Senado Federal (CEAPS — Sprint 2 / Onda 2).

Duas fontes distintas sob a mesma Fonte Senado:

- Despesas CEAPS: CSV anual `despesa_ceaps_{ano}.csv` (ISO-8859-1, ';').
  Sem watermark incremental (ADR-009) — o "watermark" é o próprio ano do CSV
  (versionamento.md §2.2). Deduplicação por `COD_DOCUMENTO` na carga Bronze.
- Dados mestres de senadores (Onda 2, dim_parlamentar / ADR-020): snapshot via
  API de Dados Abertos (`GET /senador/lista/atual.json`); `data_status` = data
  de execução.
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pandas as pd
import structlog

from pipeline.config import RetryDefaultSettings, SenadoSettings
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.senado.schemas import SenadoBronzeDespesa, SenadoBronzeParlamentar
from pipeline.utils import request_json, request_text

logger = structlog.get_logger()


def _url_csv(cfg: SenadoSettings, ano: int) -> str:
    return f"{cfg.base_url.rstrip('/')}/{cfg.padrao_arquivo.format(ano=ano)}"


def _parse_csv(
    texto: str,
    cfg: SenadoSettings,
    run_meta: LoadMetadata,
    ano: int,
) -> list[SenadoBronzeDespesa]:
    # A fonte publica uma linha de rodapé "ULTIMA ATUALIZACAO: ..." (ou
    # `"ULTIMA ATUALIZACAO";"06/08/2021 02:01"` no formato com aspas — pode vir
    # ANTES do header no CSV real) que não pertence ao dataset — descartada em
    # qualquer posição antes do parsing.
    linhas = [
        linha
        for linha in texto.splitlines()
        if not linha.strip().strip('"').upper().startswith("ULTIMA ATUALIZACAO")
    ]
    df = pd.read_csv(
        io.StringIO("\n".join(linhas)),
        sep=cfg.separador,
        quotechar=cfg.quote_char,
        dtype=str,
        keep_default_na=False,
    )

    source_version = cfg.padrao_arquivo.format(ano=ano)
    registros: list[SenadoBronzeDespesa] = []
    descartadas = 0
    for _, row in df.iterrows():
        try:
            cod_documento = int(row["COD_DOCUMENTO"])
        except (ValueError, KeyError):
            # Linhas corrompidas da fonte (aspas não escapadas deslocam colunas
            # e esvaziam COD_DOCUMENTO) — sem chave natural, não há como
            # deduplicar; descarta com contagem (auditável no log).
            descartadas += 1
            continue
        meta = run_meta.model_copy(update={"source_version": source_version})
        registros.append(
            SenadoBronzeDespesa(
                ano=int(row["ANO"]),
                mes=int(row["MES"]),
                senador=row["SENADOR"],
                tipo_despesa=row["TIPO_DESPESA"],
                cnpj_cpf=row["CNPJ_CPF"],
                fornecedor=row["FORNECEDOR"],
                documento=row["DOCUMENTO"],
                data=row["DATA"],
                detalhamento=(row.get("DETALHAMENTO") or "").strip() or None,
                valor_reembolsado=row["VALOR_REEMBOLSADO"],
                cod_documento=cod_documento,
                metadata=meta,
            )
        )

    if descartadas:
        logger.warning(
            "senado_linhas_corrompidas_descartadas",
            ano=ano,
            descartadas=descartadas,
        )

    vistos: set[int] = set()
    unicos: list[SenadoBronzeDespesa] = []
    for registro in registros:
        if registro.cod_documento in vistos:
            continue
        vistos.add(registro.cod_documento)
        unicos.append(registro)
    return unicos


def extract_ceaps(
    cfg: SenadoSettings,
    client: httpx.Client,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
    ano: int | None = None,
) -> ExtractResult:
    """Baixa e parseia o CSV anual de despesas CEAPS.

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → senado).
        client: Cliente HTTP compartilhado (injetável para testes).
        run_meta: Metadados de carga (RF-12); `source_version` é o nome do
            arquivo CSV (versionamento.md §3).
        retry_settings: Política de retry (tenacity) — override para testes.
        ano: Ano do CSV a baixar (carga histórica). None usa o ano da
            execução.

    Returns:
        ExtractResult com os registros e o ano do CSV como novo watermark.
    """
    ano = ano or run_meta.execution_timestamp.year
    url = _url_csv(cfg, ano)
    logger.info("baixando_csv_senado", url=url, ano=ano)
    texto = request_text(client, url, cfg.encoding, retry_settings)
    registros = _parse_csv(texto, cfg, run_meta, ano)
    return ExtractResult(
        records=registros,
        new_watermark=str(ano),
        source_version=cfg.padrao_arquivo.format(ano=ano),
    )


def _itens_senador(payload: dict) -> list[dict]:
    """Extrai a lista de senadores do aninhamento da API de Dados Abertos.

    A API devolve `Parlamentar` ora como lista, ora como objeto único
    (quando há um só registro) — ambos normalizados para lista.
    """
    lista = payload.get("ListaParlamentarEmExercicio", {}) or {}
    itens = lista.get("Parlamentares", {}) or {}
    parl = itens.get("Parlamentar", []) or []
    if isinstance(parl, dict):
        parl = [parl]
    return parl


def _construir_senador(item: dict[str, Any], run_meta: LoadMetadata) -> SenadoBronzeParlamentar:
    """Acha um item `Parlamentar` do `lista/atual` no registro Bronze.

    Os atributos de vigência (partido, UF, situação, legislatura) já vêm no
    próprio item da lista — não há request por id (diferente da Câmara).

    A `id_legislatura` gravada aqui é o valor bruto (primeira do mandato, ou
    0 quando ausente) — preservado apenas para auditoria. A regra de negócio
    do SCD2 não usa esse número: a Silver deriva a legislatura do calendário
    a partir de `data_status` (ADR-024).
    """
    ident = item.get("IdentificacaoParlamentar", {}) or {}
    mandato = item.get("Mandato", {}) or {}
    primeira = mandato.get("PrimeiraLegislaturaDoMandato", {}) or {}
    segunda = mandato.get("SegundaLegislaturaDoMandato", {}) or {}
    leg = primeira.get("NumeroLegislatura") or segunda.get("NumeroLegislatura")

    meta = run_meta.model_copy(
        update={"source_version": run_meta.execution_timestamp.date().isoformat()}
    )
    return SenadoBronzeParlamentar(
        id_senador=int(ident.get("CodigoParlamentar") or 0),
        nome_parlamentar=ident.get("NomeParlamentar") or "",
        nome_completo=ident.get("NomeCompletoParlamentar") or None,
        sigla_partido=ident.get("SiglaPartidoParlamentar") or None,
        sigla_uf=ident.get("UfParlamentar") or None,
        id_legislatura=int(leg) if leg else 0,
        situacao=(mandato.get("DescricaoParticipacao") or None),
        url_foto=ident.get("UrlFotoParlamentar"),
        data_status=run_meta.execution_timestamp.date().isoformat(),
        metadata=meta,
    )


def extract_senadores(
    cfg: SenadoSettings,
    client: httpx.Client,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
) -> ExtractResult:
    """Extrai o snapshot de dados mestres dos senadores em exercício (Onda 2).

    Uma requisição ao endpoint `senador/lista/atual` da API de Dados Abertos
    (a lista já carrega os atributos rastreados pelo SCD2 de
    `dim_parlamentar` (ADR-020); sem segundo request por id). O snapshot é o
    estado observado na data de execução (`data_status` = `run_meta`), mesmo
    padrão dos deputados da Câmara.

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → senado).
        client: Cliente HTTP compartilhado (injetável para testes).
        run_meta: Metadados de carga (RF-12); `source_version` é a data de
            execução (versionamento.md §3).
        retry_settings: Política de retry (tenacity) — override para testes.

    Returns:
        ExtractResult com os registros de senadores e o watermark (data da
        execução).
    """
    logger.info("iniciando_extracao_senadores")
    url = cfg.api_dados.base_url + cfg.api_dados.endpoints["senadores"].path
    payload = request_json(client, url, None, retry_settings)
    registros = [_construir_senador(item, run_meta) for item in _itens_senador(payload)]

    watermark = run_meta.execution_timestamp.date().isoformat()
    return ExtractResult(
        records=registros,
        new_watermark=watermark,
        source_version=watermark,
    )
