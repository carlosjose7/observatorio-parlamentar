# tests/pipeline/test_bronze_smoke.py
"""Smoke test do Pipeline Bronze (Sprint 2) com HTTP mockado (sem rede).

Cobre RF-01/RF-12 e versionamento.md §2/§5: sucesso total, falha isolada de
fonte, persistência de watermark entre runs, deduplicação por chave natural
entre runs (Opção 1 — read-merge-write) e gravação de `pipeline_runs`
(Parquet de controle não particionado).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd
import pytest

from pipeline.bronze import run_pipeline
from pipeline.config import RetryDefaultSettings, get_pipeline, get_sources
from pipeline.storage import LocalParquetStorage
from pipeline.watermark import JsonFileStore, NamespaceWatermarkStore, WatermarkState

RETRY_TESTS = RetryDefaultSettings(
    max_tentativas=1,
    espera_exponencial_min_segundos=0.01,
    espera_exponencial_max_segundos=0.02,
)

# ── Respostas mockadas das fontes ────────────────────────────────

DEPUTADOS = {"dados": [{"id": 1, "nome": "Deputada A"}], "links": []}

DESPESA = {
    "ano": 2026,
    "mes": 7,
    "cnpjCpfFornecedor": "11222333000181",
    "codDocumento": "guid-despesa-1",
    "codLote": 1,
    "codTipoDocumento": 0,
    "dataDocumento": "2026-07-03T00:00:00",
    "nomeFornecedor": "Fornecedor A",
    "numDocumento": "NF-123",
    "numRessarcimento": None,
    "parcela": 1,
    "tipoDespesa": "Passagem Aérea",
    "tipoDocumento": "Nota Fiscal",
    "urlDocumento": None,
    "valorDocumento": 100.0,
    "valorGlosa": 0.0,
    "valorLiquido": 100.0,
}

CSV_SENADO = """ANO;MES;SENADOR;TIPO_DESPESA;CNPJ_CPF;FORNECEDOR;DOCUMENTO;DATA;DETALHAMENTO;VALOR_REEMBOLSADO;COD_DOCUMENTO
2026;1;Senador A;Passagem;12345678000199;Fornecedor B;Doc 001;01/01/2026;;120,50;10001
ULTIMA ATUALIZACAO: 2026-07-01
"""

EMENDA = {
    "ano": 2026,
    "codigoEmenda": "emenda-1",
    "tipoEmenda": "Individual",
    "nomeAutor": "Deputada A",
    "numeroEmenda": "1234",
    "funcao": "Saúde",
    "subfuncao": "Atenção Básica",
    "localidadeDoGasto": "São Paulo",
    "valorEmpenhado": "1000,00",
    "valorLiquidado": "800,00",
    "valorPago": "800,00",
    "valorRestoInscrito": "0,00",
    "valorRestoCancelado": "0,00",
    "valorRestoPago": "0,00",
}

CARTAO = {
    "id": 500,
    "mesExtrato": "07/2026",
    "dataTransacao": "15/07/2026",
    "valorTransacao": "250,75",
    "tipoCartao": "1",
    "estabelecimento": {
        "id": 10,
        "cnpjFormatado": "11222333000181",
        "cpfFormatado": "",
        "nome": "Restaurante X",
        "razaoSocialReceita": "Restaurante X LTDA",
        "tipo": "PJ",
        "numeroInscricaoSocial": "",
    },
    "portador": {"nome": "Servidor Y", "cpfFormatado": "***.122.497-**", "nis": ""},
    "unidadeGestora": {"codigo": "150002", "nome": "Unidade Gestora Z"},
}


def _cliente_mock(
    *,
    senado_falha: bool = False,
    senado_respostas: list[str] | None = None,
    emenda_respostas: list[list[dict]] | None = None,
    cartoes_requisicoes: list | None = None,
    cartao_dinamico: bool = False,
) -> httpx.Client:
    """Cliente httpx com transporte mockado (nenhuma requisição de rede)."""
    senado_seq = list(senado_respostas or [])
    emenda_seq = list(emenda_respostas or [])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path.endswith("/deputados"):
            pagina = int(params.get("pagina", 1))
            return httpx.Response(
                200, json=DEPUTADOS if pagina == 1 else {"dados": [], "links": []}
            )
        if path.endswith("/despesas"):
            pagina = int(params.get("pagina", 1))
            return httpx.Response(
                200, json={"dados": [DESPESA] if pagina == 1 else [], "links": []}
            )
        if path.endswith(".csv"):
            if senado_falha:
                return httpx.Response(503, json={"erro": "indisponível"})
            corpo = senado_seq.pop(0) if senado_seq else CSV_SENADO
            return httpx.Response(
                200, content=corpo.encode("latin-1"), headers={"content-type": "text/csv"}
            )
        if path.endswith("/emendas"):
            pagina = int(params.get("pagina", 1))
            dados = (emenda_seq.pop(0) if emenda_seq else [EMENDA]) if pagina == 1 else []
            return httpx.Response(200, json=dados)
        if path.endswith("/cartoes"):
            pagina = int(params.get("pagina", 1))
            if cartoes_requisicoes is not None:
                cartoes_requisicoes.append(dict(params))
            cartao = CARTAO
            if cartao_dinamico:
                cartao = {**CARTAO, "mesExtrato": params.get("mesExtratoInicio", CARTAO["mesExtrato"])}
            return httpx.Response(200, json=[cartao] if pagina == 1 else [])
        return httpx.Response(404, json={"erro": "rota não encontrada"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def ambiente(tmp_path):
    return {
        "storage": LocalParquetStorage(tmp_path / "bronze"),
        "store": JsonFileStore(tmp_path / "watermarks"),
    }


def _fontes_com_janelas(ano: int = 2026, mes: str = "07/2026"):
    """Cópia de `sources.yaml` com janelas históricas recentes.

    `get_sources()` é cacheado e usado pelo módulo bronze via import; a cópia
    profunda + monkeypatch evita vazamento de estado entre testes.
    """
    fontes = get_sources().model_copy(deep=True)
    fontes.senado.carga_historica.ano_inicio = ano
    fontes.transparencia.carga_historica["emendas"].ano_inicio = ano
    fontes.transparencia.carga_historica["cartoes"].mes_inicio = mes
    return fontes


@pytest.fixture(autouse=True)
def _janelas_recentes(monkeypatch):
    """Mantém os testes existentes no período corrente (1 período por fonte)."""
    import pipeline.bronze as bronze

    monkeypatch.setattr(bronze, "get_sources", lambda: _fontes_com_janelas())


def _pipeline_com_validacao(limite_periodos: int | None = 1):
    """Cópia de `pipeline.yaml` com o modo validação habilitado.

    Usa `pipeline.config.get_pipeline` (não-patchado) para evitar recursão
    quando `pipeline.bronze.get_pipeline` já foi substituído.
    """
    cfg = get_pipeline().model_copy(deep=True)
    cfg.validacao.habilitado = True
    cfg.validacao.limite_periodos = limite_periodos
    return cfg


def _ler_parquet(ambiente, *partes):
    """Lê todos os Parquet sob `bronze/<partes>` concatenados (ou None)."""
    caminho = ambiente["storage"].root.joinpath(*partes)
    arquivos = sorted(caminho.glob("**/*.parquet")) if caminho.exists() else []
    if not arquivos:
        return None
    return pd.concat([pd.read_parquet(f) for f in arquivos], ignore_index=True)


def _ler_controle(ambiente) -> pd.DataFrame:
    arquivos = sorted(
        (ambiente["storage"].root / "controle" / "pipeline_runs").glob("*.parquet")
    )
    return pd.concat([pd.read_parquet(f) for f in arquivos], ignore_index=True)


def test_run_completo_sucesso(ambiente):
    client = _cliente_mock()
    run = run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)

    assert run.status == "success"
    assert run.fontes_com_erro == []
    assert str(run.run_id)

    camara_df = _ler_parquet(ambiente, "camara", "ano=2026", "mes=7")
    assert camara_df is not None and len(camara_df) == 1
    assert camara_df.iloc[0]["cod_documento"] == "guid-despesa-1"
    assert camara_df.iloc[0]["run_id"] == str(run.run_id)

    senado_df = _ler_parquet(ambiente, "senado", "ano=2026", "mes=1")
    assert senado_df is not None and len(senado_df) == 1
    assert senado_df.iloc[0]["cod_documento"] == 10001
    assert senado_df.iloc[0]["valor_reembolsado"] == "120,50"

    emenda_df = _ler_parquet(ambiente, "transparencia_emendas", "ano=2026", "mes=0")
    assert emenda_df is not None and len(emenda_df) == 1
    assert emenda_df.iloc[0]["codigo_emenda"] == "emenda-1"

    cartao_df = _ler_parquet(ambiente, "transparencia_cartoes", "ano=2026", "mes=7")
    assert cartao_df is not None and len(cartao_df) == 1
    assert cartao_df.iloc[0]["id"] == 500
    assert cartao_df.iloc[0]["estabelecimento_nome"] == "Restaurante X"

    runs_df = _ler_controle(ambiente)
    assert len(runs_df) == 1
    assert runs_df.iloc[0]["status"] == "success"
    assert runs_df.iloc[0]["run_id"] == str(run.run_id)


def test_escrita_nao_particionada(ambiente):
    df = pd.DataFrame({"run_id": ["run-x"], "status": ["success"]})
    ambiente["storage"].write_file(Path("controle") / "pipeline_runs", df, "run-x.parquet")
    lido = pd.read_parquet(
        ambiente["storage"].root / "controle" / "pipeline_runs" / "run-x.parquet"
    )
    assert lido.iloc[0]["status"] == "success"


def test_fonte_isolada_com_falha(ambiente):
    client = _cliente_mock(senado_falha=True)
    run = run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)

    assert run.status == "partial"
    assert run.fontes_com_erro == ["senado"]

    assert _ler_parquet(ambiente, "senado", "ano=2026", "mes=1") is None
    assert _ler_parquet(ambiente, "camara", "ano=2026", "mes=7") is not None
    assert _ler_parquet(ambiente, "transparencia_emendas", "ano=2026", "mes=0") is not None
    assert _ler_parquet(ambiente, "transparencia_cartoes", "ano=2026", "mes=7") is not None

    runs_df = _ler_controle(ambiente)
    assert runs_df.iloc[0]["status"] == "partial"
    assert runs_df.iloc[0]["fontes_com_erro"] == ["senado"]
    assert runs_df.iloc[0]["watermark_senado"] is None


def test_watermark_persiste_entre_runs(ambiente):
    client = _cliente_mock()
    run1 = run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)
    run2 = run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)

    estado_camara = ambiente["store"].get("watermark_camara_despesas")
    assert estado_camara.last_watermark == "2026-07-03"  # maior dataDocumento observado
    assert estado_camara.run_id == run2.run_id

    estado_cartao = ambiente["store"].get("watermark_cgu_cartao")
    assert estado_cartao.last_watermark

    assert len(_ler_controle(ambiente)) == 2  # uma linha de controle por run


def test_cartoes_envia_mes_inicio_e_fim(ambiente):
    requisicoes: list = []
    client = _cliente_mock(cartoes_requisicoes=requisicoes)
    run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)

    assert requisicoes
    cartao_req = requisicoes[0]
    assert cartao_req["mesExtratoInicio"] == cartao_req["mesExtratoFim"]
    assert cartao_req["tipoCartao"] == "1"


def test_deduplicacao_senado_entre_runs(ambiente):
    # Republicação do CSV anual com uma chave nova no mês 2 (Opção 1)
    csv_v2 = CSV_SENADO.replace(
        "ULTIMA ATUALIZACAO: 2026-07-01",
        "2026;2;Senador A;Hospedagem;98765432000188;Fornecedor C;Doc 002;02/02/2026;;500,00;10002\n"
        "ULTIMA ATUALIZACAO: 2026-07-01",
    )
    client = _cliente_mock(senado_respostas=[CSV_SENADO, csv_v2, csv_v2])

    run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)
    run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)
    run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)

    mes1 = _ler_parquet(ambiente, "senado", "ano=2026", "mes=1")
    mes2 = _ler_parquet(ambiente, "senado", "ano=2026", "mes=2")
    assert mes1 is not None and len(mes1) == 1 and mes1.iloc[0]["cod_documento"] == 10001
    assert mes2 is not None and len(mes2) == 1 and mes2.iloc[0]["cod_documento"] == 10002

    ano = _ler_parquet(ambiente, "senado", "ano=2026")
    assert ano is not None and len(ano) == 2  # sem duplicação após 3 runs


def test_deduplicacao_emendas_entre_runs(ambiente):
    emenda2 = {**EMENDA, "codigoEmenda": "emenda-2", "numeroEmenda": "5678"}
    client = _cliente_mock(
        emenda_respostas=[[EMENDA], [EMENDA, emenda2], [EMENDA, emenda2]]
    )

    run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)
    run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)
    run_pipeline(storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS)

    df = _ler_parquet(ambiente, "transparencia_emendas", "ano=2026", "mes=0")
    assert df is not None and len(df) == 2  # emenda-1 (first-seen) + emenda-2
    assert set(df["codigo_emenda"]) == {"emenda-1", "emenda-2"}


def test_json_file_store_round_trip(tmp_path):
    store = JsonFileStore(tmp_path / "wm")
    assert store.get("watermark_camara_despesas").last_watermark is None

    store.set("watermark_camara_despesas", WatermarkState(last_watermark="2026-07-03"))
    releitura = JsonFileStore(tmp_path / "wm").get("watermark_camara_despesas")
    assert releitura.last_watermark == "2026-07-03"


def test_config_deduplicacao_carregada():
    from pipeline.config import get_sources

    fontes = get_sources()
    assert fontes.senado.deduplicacao.campo == "cod_documento"
    assert fontes.senado.deduplicacao.escopo == "ano"
    assert fontes.transparencia.deduplicacao["emendas"].campo == "codigo_emenda"
    assert fontes.transparencia.deduplicacao["cartoes"].campo == "id"


def test_config_carga_historica_carregada():
    fontes = get_sources()
    assert fontes.camara.carga_historica.data_inicio == "2015-01-01"
    assert fontes.senado.carga_historica.ano_inicio == 2015
    assert fontes.transparencia.carga_historica["emendas"].ano_inicio == 2020
    assert fontes.transparencia.carga_historica["cartoes"].mes_inicio == "01/2013"


def test_backfill_senado_multi_ano(ambiente, monkeypatch):
    import pipeline.bronze as bronze

    monkeypatch.setattr(bronze, "get_sources", lambda: _fontes_com_janelas(ano=2025))
    csv_2025 = CSV_SENADO.replace("2026;", "2025;").replace(
        "ULTIMA ATUALIZACAO: 2026-07-01", "ULTIMA ATUALIZACAO: 2025-12-01"
    )
    client = _cliente_mock(senado_respostas=[csv_2025, CSV_SENADO])

    run = run_pipeline(
        storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS
    )

    assert run.status == "success"
    assert run.watermark_senado == "2026"  # maior ano processado
    mes2025 = _ler_parquet(ambiente, "senado", "ano=2025", "mes=1")
    mes2026 = _ler_parquet(ambiente, "senado", "ano=2026", "mes=1")
    assert mes2025 is not None and mes2025.iloc[0]["ano"] == 2025
    assert mes2026 is not None and mes2026.iloc[0]["ano"] == 2026


def test_backfill_cartoes_multi_mes(ambiente, monkeypatch):
    import pipeline.bronze as bronze

    monkeypatch.setattr(bronze, "get_sources", lambda: _fontes_com_janelas(mes="07/2026"))
    client = _cliente_mock(cartao_dinamico=True)

    run = run_pipeline(
        storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS
    )

    assert run.status == "success"
    assert run.watermark_cgu_cartao == "08/2026"  # maior mês processado (hoje é 08/2026)
    mes7 = _ler_parquet(ambiente, "transparencia_cartoes", "ano=2026", "mes=7")
    mes8 = _ler_parquet(ambiente, "transparencia_cartoes", "ano=2026", "mes=8")
    assert mes7 is not None and len(mes7) == 1
    assert mes8 is not None and len(mes8) == 1


def test_backfill_cartoes_cruza_anos_watermark_cronologico(ambiente, monkeypatch):
    # Regressão: janela real de produção cruza anos (11/2025 → 08/2026).
    # Um max() lexicográfico escolheria "12/2025" como watermark, travando o
    # incremental em dezembro — o correto é o último período cronológico.
    import pipeline.bronze as bronze

    monkeypatch.setattr(bronze, "get_sources", lambda: _fontes_com_janelas(mes="11/2025"))
    client = _cliente_mock(cartao_dinamico=True)

    run = run_pipeline(
        storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS
    )

    assert run.status == "success"
    assert run.watermark_cgu_cartao == "08/2026"  # não "12/2025"
    assert ambiente["store"].get("watermark_cgu_cartao").last_watermark == "08/2026"


def test_validacao_limita_janela_e_isola_watermark(ambiente, monkeypatch):
    import pipeline.bronze as bronze

    monkeypatch.setattr(bronze, "get_sources", lambda: _fontes_com_janelas(ano=2025))
    monkeypatch.setattr(bronze, "get_pipeline", lambda: _pipeline_com_validacao(limite_periodos=1))
    csv_2025 = CSV_SENADO.replace("2026;", "2025;")
    client = _cliente_mock(senado_respostas=[csv_2025])

    run = run_pipeline(
        storage=ambiente["storage"], store=ambiente["store"], client=client, retry_settings=RETRY_TESTS
    )

    assert run.status == "success"
    # Só o primeiro período da janela (2025→2026 truncado para 2025)
    assert _ler_parquet(ambiente, "senado", "ano=2025", "mes=1") is not None
    assert _ler_parquet(ambiente, "senado", "ano=2026", "mes=1") is None
    assert run.watermark_senado == "2025"

    # Watermark gravado em namespace isolado — store real intacto
    assert ambiente["store"].get("watermark_senado").last_watermark is None
    assert ambiente["store"].get("validacao:watermark_senado").last_watermark == "2025"


def test_namespace_watermark_store_round_trip(tmp_path):
    base = JsonFileStore(tmp_path / "wm")
    isolado = NamespaceWatermarkStore(base, namespace="validacao")

    isolado.set("watermark_senado", WatermarkState(last_watermark="2025"))
    assert isolado.get("watermark_senado").last_watermark == "2025"
    assert base.get("watermark_senado").last_watermark is None  # store real intacto
