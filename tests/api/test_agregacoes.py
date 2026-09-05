"""tests/api/test_agregacoes.py — endpoints `GET /agregacoes/*` (análises).

Cobre os recortes agregados de `fact_despesa` sobre o Gold determinístico
do conftest: por UF, por partido, top parlamentares e série mensal. A versão
vigente do SCD2 (`is_current`) é a única considerada — a versão histórica de
MARIA DA SILVA (PSDB/DF, encerrada) não entra nas agregações.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings


def test_gastos_por_uf_usa_versao_vigente(_cliente):
    corpo = _cliente.get("/agregacoes/por-uf").json()
    assert corpo["limite"] == 10
    # MARIA (DF, vigente): 1500 + 300.50 + 700 = 2500.50 em 3 despesas;
    # ANA (SP): 900.00 em 1 despesa.
    itens = {item["rotulo"]: item for item in corpo["itens"]}
    assert set(itens) == {"DF", "SP"}
    assert itens["DF"]["num_despesas"] == 3
    assert float(itens["DF"]["total"]) == 2500.50
    assert itens["SP"]["num_despesas"] == 1
    assert float(itens["SP"]["total"]) == 900.00
    assert corpo["itens"][0]["rotulo"] == "DF"


def test_gastos_por_partido(_cliente):
    itens = _cliente.get("/agregacoes/por-partido").json()["itens"]
    por_partido = {item["rotulo"]: float(item["total"]) for item in itens}
    assert por_partido == {"PSDB": 2500.50, "PT": 900.00}


def test_top_parlamentares_ordenado_por_total(_cliente):
    itens = _cliente.get("/agregacoes/top-parlamentares").json()["itens"]
    assert [item["rotulo"] for item in itens] == ["MARIA DA SILVA", "ANA SOUZA"]
    assert float(itens[0]["total"]) == 2500.50


def test_top_fornecedores_ordenado_por_total(_cliente):
    corpo = _cliente.get("/agregacoes/top-fornecedores").json()
    assert corpo["limite"] == 10
    itens = corpo["itens"]
    # Transportes Brasil: 1500 + 700 + 900 = 3100.00 de 2 parlamentares;
    # Ana Souza: 300.50 de 1 parlamentar.
    assert [i["id_fornecedor"] for i in itens] == [10, 11]
    assert itens[0]["nome_fornecedor"] == "Transportes Brasil Ltda"
    assert float(itens[0]["total_recebido"]) == 3100.00
    assert itens[0]["num_parlamentares"] == 2
    assert float(itens[1]["total_recebido"]) == 300.50
    assert itens[1]["num_parlamentares"] == 1


def test_serie_no_tempo_ordenada_por_mes(_cliente):
    corpo = _cliente.get("/agregacoes/no-tempo").json()
    periodos = [item["periodo"] for item in corpo["itens"]]
    assert periodos == ["202211", "202303", "202305"]
    totais = {item["periodo"]: float(item["total"]) for item in corpo["itens"]}
    assert totais["202211"] == 700.00
    assert totais["202303"] == 2400.00
    assert totais["202305"] == 300.50


def test_limite_aplicado_na_consulta(_cliente):
    corpo = _cliente.get("/agregacoes/por-uf", params={"limite": 1}).json()
    assert corpo["limite"] == 1
    assert len(corpo["itens"]) == 1
    assert corpo["itens"][0]["rotulo"] == "DF"


def test_limite_acima_do_maximo_rejeitado(_cliente):
    resposta = _cliente.get("/agregacoes/por-uf", params={"limite": 999999})
    assert resposta.status_code == 422


def test_por_uf_filtrado_por_ano(_cliente):
    # Só 2022: a despesa de 700.00 (202211) da MARIA (DF); SP some.
    itens = {
        item["rotulo"]: item
        for item in _cliente.get("/agregacoes/por-uf", params={"ano": 2022}).json()["itens"]
    }
    assert set(itens) == {"DF"}
    assert float(itens["DF"]["total"]) == 700.00
    assert itens["DF"]["num_despesas"] == 1


def test_por_partido_filtrado_por_ano(_cliente):
    # Só 2023: MARIA (PSDB) 1500 + 300.50; ANA (PT) 900.
    itens = {
        item["rotulo"]: item
        for item in _cliente.get("/agregacoes/por-partido", params={"ano": 2023}).json()["itens"]
    }
    assert float(itens["PSDB"]["total"]) == 1800.50
    assert float(itens["PT"]["total"]) == 900.00


def test_top_parlamentares_filtrado_por_ano(_cliente):
    itens = _cliente.get("/agregacoes/top-parlamentares", params={"ano": 2022}).json()["itens"]
    assert [item["rotulo"] for item in itens] == ["MARIA DA SILVA"]
    assert float(itens[0]["total"]) == 700.00


def test_ano_sem_dados_retorna_vazio(_cliente):
    corpo = _cliente.get("/agregacoes/por-uf", params={"ano": 2020}).json()
    assert corpo["itens"] == []


def test_ano_fora_da_faixa_rejeitado(_cliente):
    assert _cliente.get("/agregacoes/por-uf", params={"ano": 1999}).status_code == 422
    assert _cliente.get("/agregacoes/por-uf", params={"ano": 2101}).status_code == 422


def test_gold_indisponivel_503_agregacoes(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/agregacoes/por-uf")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}
