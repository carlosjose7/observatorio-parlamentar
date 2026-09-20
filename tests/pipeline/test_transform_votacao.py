# tests/pipeline/test_transform_votacao.py
"""Transform Bronze → Silver do domínio votação (Sprint 27 — Onda 1, ADR-058).

Cobre: de-para versionado (situação do evento, voto nominal, sentinela
`nao_mapeado`), construção das 5 Silver e carga integrada com garantia de
tabela mesmo com Bronze vazio (diferença deliberada das cargas legadas —
`dbt build` completo nunca quebra por fonte ausente).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from pipeline.camara.votacao_transform import (
    carregar_silver_evento,
    carregar_silver_orientacao,
    carregar_silver_presenca,
    carregar_silver_votacao,
    carregar_silver_voto,
    construir_silver_evento,
    construir_silver_voto,
    normalizar_situacao_evento,
    normalizar_tipo_voto,
)
from pipeline.storage import LocalParquetStorage

_RUN = {
    "run_id": "run-0001",
    "pipeline_version": "teste",
    "execution_timestamp": "2026-01-01T00:00:00",
    "source_version": "2024-05-15",
}


def test_de_para_situacao_evento():
    assert normalizar_situacao_evento("Encerrada") == "encerrada"
    assert normalizar_situacao_evento("Em Andamento") == "em_andamento"
    assert normalizar_situacao_evento("Convocada") == "convocada"
    assert normalizar_situacao_evento("Suspensa") == "nao_mapeado"
    assert normalizar_situacao_evento(None) == "nao_mapeado"
    assert normalizar_situacao_evento("  ") == "nao_mapeado"


def test_de_para_tipo_voto():
    assert normalizar_tipo_voto("Sim") == "sim"
    assert normalizar_tipo_voto("Não") == "nao"
    assert normalizar_tipo_voto("Abstenção") == "abstencao"
    assert normalizar_tipo_voto("Artigo 17") == "artigo17"
    assert normalizar_tipo_voto("Obstrução") == "obstrucao"
    assert normalizar_tipo_voto("Voto Secreto") == "nao_mapeado"
    assert normalizar_tipo_voto(None) == "nao_mapeado"


def _df_evento():
    return pd.DataFrame(
        [
            {
                "id_evento": 10,
                "data_inicio": "2024-05-15T14:00",
                "data_fim": "2024-05-15T18:00",
                "descricao_tipo": "Sessão Deliberativa",
                "situacao": "Encerrada",
                **_RUN,
            },
            {
                "id_evento": 11,
                "data_inicio": "2024-05-16T14:00",
                "data_fim": None,
                "descricao_tipo": "Sessão Deliberativa",
                "situacao": "Em Andamento",
                **_RUN,
            },
        ]
    )


def test_construir_evento_preserva_bruto_e_normaliza():
    df = construir_silver_evento(_df_evento())
    assert list(df["situacao_normalizada"]) == ["encerrada", "em_andamento"]
    assert list(df["situacao_bruta"]) == ["Encerrada", "Em Andamento"]
    assert str(df["data_inicio"].dtype) == "datetime64[ns]"


def test_construir_voto_normaliza():
    df = construir_silver_voto(
        pd.DataFrame(
            [
                {"id_votacao": 100, "id_deputado": 1, "tipo_voto": "Sim", **_RUN},
                {"id_votacao": 100, "id_deputado": 2, "tipo_voto": "Não", **_RUN},
            ]
        )
    )
    assert list(df["voto_normalizado"]) == ["sim", "nao"]


def _bronze(storage: LocalParquetStorage, diretorio: str, df: pd.DataFrame):
    storage.write_file(Path(diretorio), df, "run-1.parquet")


def _db(tmp_path, monkeypatch):
    import pipeline.config as config

    db_path = tmp_path / "observatorio.duckdb"
    config.load_env_settings.cache_clear()
    old = os.environ.get("DUCKDB_DATABASE_PATH")
    os.environ["DUCKDB_DATABASE_PATH"] = str(db_path)
    return db_path, old, config


def _restaura(old, config):
    if old is None:
        os.environ.pop("DUCKDB_DATABASE_PATH", None)
    else:
        os.environ["DUCKDB_DATABASE_PATH"] = old
    config.load_env_settings.cache_clear()


def test_carga_evento_persiste_e_garante_tabela_vazia(tmp_path, monkeypatch):
    root = tmp_path / "bronze"
    root.mkdir(parents=True, exist_ok=True)
    storage = LocalParquetStorage(root)
    _bronze(storage, "camara_eventos", _df_evento())

    db_path, old, config = _db(tmp_path, monkeypatch)
    try:
        res = carregar_silver_evento(storage=storage, run_id="run-0001")
        assert len(res.aceitos) == 2
        assert res.quarentena.empty

        # Bronze vazio → tabela garantida com 0 linhas (nunca None).
        res_vazio = carregar_silver_presenca(storage=storage, run_id="run-0001")
        assert len(res_vazio.aceitos) == 0
    finally:
        _restaura(old, config)

    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        assert con.execute("select count(*) from silver.silver_evento").fetchone()[0] == 2
        assert con.execute("select count(*) from silver.silver_presenca").fetchone()[0] == 0
    finally:
        con.close()


def test_carga_voto_orientacao(tmp_path, monkeypatch):
    root = tmp_path / "bronze"
    root.mkdir(parents=True, exist_ok=True)
    storage = LocalParquetStorage(root)
    _bronze(
        storage,
        "camara_votos",
        pd.DataFrame(
            [
                {"id_votacao": 100, "id_deputado": 1, "tipo_voto": "Sim", **_RUN},
                {"id_votacao": 100, "id_deputado": 1, "tipo_voto": "Sim", **_RUN},
            ]
        ),
    )
    _bronze(
        storage,
        "camara_orientacoes",
        pd.DataFrame(
            [{"id_votacao": 100, "sigla_bancada": "PARTIDO B", "orientacao_voto": "Sim", **_RUN}]
        ),
    )

    db_path, old, config = _db(tmp_path, monkeypatch)
    try:
        res_voto = carregar_silver_voto(storage=storage, run_id="run-0001")
        # Dedup independente (ADR-014): duplicata colapsa antes do gate.
        assert len(res_voto.aceitos) == 1
        res_ori = carregar_silver_orientacao(storage=storage, run_id="run-0001")
        assert len(res_ori.aceitos) == 1
        res_votacao = carregar_silver_votacao(storage=storage, run_id="run-0001")
        assert len(res_votacao.aceitos) == 0
    finally:
        _restaura(old, config)

    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        assert con.execute("select voto_normalizado from silver.silver_voto").fetchall() == [
            ("sim",)
        ]
    finally:
        con.close()
