"""pipeline/camara/soap_extract.py — Extração SOAP legado da Câmara (ADR-043).

Módulo isolado para consumo do webservice SOAP legado `Deputados.asmx`,
especificamente o endpoint `ObterDetalhesDeputado` que retorna
`filiacoesPartidarias` com data exata de cada filiação partidária.

Este módulo NÃO propaga dependência de SOAP/XML para o resto do pipeline
(ADR-043, item 1). Usa `httpx` + `lxml` para parsing manual de XML,
sem引入 `zeep`.

Fonte: https://www.camara.leg.br/SitCamaraWS/Deputados.asmx
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import structlog
from lxml import etree  # noqa: SLF001 — isolado neste módulo (ADR-043)
from pipeline.camara.schemas import CamaraFiliacaoPartidaria
from pipeline.config import RetryDefaultSettings
from pipeline.contracts import LoadMetadata
from pipeline.utils import RateLimiter, _tentativa, _resolver_settings

logger = structlog.get_logger()

SOAP_BASE_URL = "https://www.camara.leg.br/SitCamaraWS/Deputados.asmx"
LEGISLATURES = [54, 55, 56, 57]
NAMESPACE = {"s": "http://www.camara.leg.br/SitCamaraWS/Deputados.asmx"}


def _limitador_taxa_fixa(requisicoes_por_minuto: int = 30) -> RateLimiter:
    """Throttling proativo para o webservice SOAP legado.

    SOAP legado não tem rate limit documentado — usa 30 req/min como
    margem conservadora (vs 100 da API REST).
    """
    return RateLimiter(requisicoes_por_minuto)


def _request_soap(
    client: httpx.Client,
    id_deputado: int,
    num_legislatura: int,
    retry_settings: RetryDefaultSettings | None = None,
    limiter: RateLimiter | None = None,
) -> bytes:
    """Requisição GET ao endpoint SOAP, retornando bytes do XML.

    O endpoint aceita GET com query params (não exige POST SOAP envelope).
    """
    url = f"{SOAP_BASE_URL}/ObterDetalhesDeputado"
    params = {"ideCadastro": id_deputado, "numLegislatura": num_legislatura}
    settings = _resolver_settings(retry_settings)

    def _do_request() -> bytes:
        if limiter is not None:
            limiter.aguardar()
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.content

    return _tentativa(settings)(_do_request)()


def _parse_filiacoes(
    xml_bytes: bytes,
    id_deputado: int,
    num_legislatura: int,
    uf: str | None,
    run_meta: LoadMetadata,
) -> list[CamaraFiliacaoPartidaria]:
    """Extrai `filiacoesPartidarias` do XML de resposta.

    Estrutura XML esperada (simplificada):
    <Deputado>
      <ideCadastro>...</ideCadastro>
      <nomeParlamentar>...</nomeParlamentar>
      <siglaUf>...</siglaUf>
      <filiacoesPartidarias>
        <filiacaoPartidaria>
          <siglaPartido>PT</siglaPartido>
          <dataFiliacaoPartidoPosterior>2015-03-10T00:00:00</dataFiliacaoPartidoPosterior>
        </filiacaoPartidaria>
        ...
      </filiacoesPartidarias>
    </Deputado>
    """
    root = etree.fromstring(xml_bytes)  # noqa: S320
    filiacoes: list[CamaraFiliacaoPartidaria] = []

    # Busca filiacoesPartidarias (pode ter namespace ou não)
    filiacoes_nodes = root.findall(".//filiacoesPartidarias/filiacaoPartidaria")
    if not filiacoes_nodes:
        filiacoes_nodes = root.findall(
            ".//s:filiacoesPartidarias/s:filiacaoPartidaria", NAMESPACE
        )

    meta = run_meta.model_copy(
        update={"source_version": f"soap-leg-{num_legislatura}"}
    )

    for node in filiacoes_nodes:
        sigla = node.findtext("siglaPartido") or node.findtext(
            "s:siglaPartido", namespaces=NAMESPACE
        )
        data = node.findtext("dataFiliacaoPartidoPosterior") or node.findtext(
            "s:dataFiliacaoPartidoPosterior", namespaces=NAMESPACE
        )
        if not sigla or not data:
            continue
        filiacoes.append(
            CamaraFiliacaoPartidaria.model_validate(
                {
                    "id_deputado": id_deputado,
                    "siglaPartido": sigla.strip(),
                    "dataFiliacaoPartidoPosterior": data.strip(),
                    "numLegislatura": num_legislatura,
                    "siglaUf": uf,
                    "partido_uf_aproximado": False,
                    "metadata": meta.model_dump(),
                }
            )
        )
    return filiacoes


def _extrair_uf_do_deputado(
    client: httpx.Client,
    id_deputado: int,
    retry_settings: RetryDefaultSettings | None = None,
    limiter: RateLimiter | None = None,
) -> str | None:
    """Obtém a UF do deputado via a primeira resposta SOAP válida.

    A UF nunca muda para a Câmara (confirmado: 3.089 linhas, 1.251
    deputados, zero mudanças — ADR-043), então basta extrair de uma
    única requisição.
    """
    xml = _request_soap(client, id_deputado, LEGISLATURES[0], retry_settings, limiter)
    root = etree.fromstring(xml)  # noqa: S320
    uf = root.findtext("siglaUf") or root.findtext("s:siglaUf", namespaces=NAMESPACE)
    return uf.strip() if uf else None


def extrair_filiacoes_deputado(
    client: httpx.Client,
    id_deputado: int,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
    limiter: RateLimiter | None = None,
) -> list[CamaraFiliacaoPartidaria]:
    """Extrai filiações partidárias de um deputado para todas as legislaturas.

    Para cada legislatura (54–57), chama ObterDetalhesDeputado e extrai
    filiacoesPartidarias. Resultados duplicados (mesma filiação em mais
    de uma legislatura) são descartados por chave natural
    (id_deputado + sigla_partido + data_filiacao).
    """
    logger.info(
        "extraindo_filiacoes_deputado",
        id_deputado=id_deputado,
        legislaturas=LEGISLATURES,
    )

    # Obtém UF (uma única vez, não muda)
    uf = _extrair_uf_do_deputado(client, id_deputado, retry_settings, limiter)

    vistos: set[tuple[int, str, str]] = set()
    filiacoes: list[CamaraFiliacaoPartidaria] = []

    for legislatura in LEGISLATURES:
        try:
            xml = _request_soap(
                client, id_deputado, legislatura, retry_settings, limiter
            )
            novas = _parse_filiacoes(
                xml, id_deputado, legislatura, uf, run_meta
            )
            for fil in novas:
                chave = (fil.id_deputado, fil.sigla_partido, fil.data_filiacao)
                if chave not in vistos:
                    vistos.add(chave)
                    filiacoes.append(fil)
        except Exception:
            logger.warning(
                "falha_extracao_legislatura",
                id_deputado=id_deputado,
                legislatura=legislatura,
                exc_info=True,
            )
            continue

    logger.info(
        "filiacoes_extraidas",
        id_deputado=id_deputado,
        total=len(filiacoes),
    )
    return filiacoes


def extrair_filiacoes_em_lote(
    client: httpx.Client,
    ids_deputados: list[int],
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
    requisicoes_por_minuto: int = 30,
) -> list[CamaraFiliacaoPartidaria]:
    """Extrai filiações partidárias para uma lista de deputados.

    Função de alto nível que orquestra a extração em lote com
    rate limiting e logging de progresso.
    """
    limiter = _limitador_taxa_fixa(requisicoes_por_minuto)
    total = len(ids_deputados)
    logger.info("iniciando_extracao_filiacoes_lote", total_deputados=total)

    todas_filiacoes: list[CamaraFiliacaoPartidaria] = []
    for i, id_dep in enumerate(ids_deputados, 1):
        filiacoes = extrair_filiacoes_deputado(
            client, id_dep, run_meta, retry_settings, limiter
        )
        todas_filiacoes.extend(filiacoes)
        if i % 50 == 0 or i == total:
            logger.info(
                "progresso_extracao_filiacoes",
                concluidos=i,
                total=total,
                filiacoes_acumuladas=len(todas_filiacoes),
            )

    logger.info(
        "extracao_filiacoes_concluida",
        total_deputados=total,
        total_filiacoes=len(todas_filiacoes),
    )
    return todas_filiacoes


def salvar_cache_filiacoes(
    filiacoes: list[CamaraFiliacaoPartidaria],
    cache_dir: Path,
    run_meta: LoadMetadata,
) -> Path:
    """Persiste filiações extraídas em Parquet para cache idempotente.

    Escrita em `bronze/camara/filiacoes/` seguindo o padrão de merge
    com deduplicação por chave natural (storage.py write_merged).
    """
    import pandas as pd

    if not filiacoes:
        logger.info("nenhuma_filiacao_para_cache")
        return cache_dir

    linhas = [f.model_dump(mode="json") for f in filiacoes]
    df = pd.json_normalize(linhas, sep="_")
    # Remove prefixo metadata_ (padrão pipeline/utils.py)
    df.columns = [
        col.removeprefix("metadata_") if col.startswith("metadata_") else col
        for col in df.columns
    ]

    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"run-{run_meta.run_id}.parquet"
    destino = cache_dir / filename
    df.to_parquet(destino, index=False)

    logger.info(
        "cache_filiacoes_salvo",
        caminho=str(destino),
        linhas=len(df),
    )
    return destino
