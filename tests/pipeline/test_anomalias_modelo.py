# tests/pipeline/test_anomalias_modelo.py
"""Modelo de anomalia congelado e versionado (ADR-065, Sprint 29).

Cobre `analytics/anomalies/model.py` e a config `analytics.anomalias`:

- validação de `max_samples` (null/1.0 rejeitados — ADR-065, Contexto d);
- ordem canônica do treino (item 1) e estabilidade exata sob embaralhamento
  de linhas na inferência (critério A1 em miniatura);
- ciclo de vida do artefato `anomaly-<MAJOR>.<MINOR>`: train → candidate,
  activate → active, imutabilidade, um `active` por família e integridade
  sha256 (itens 2–4);
- o passo de anomalias NÃO treina: sem modelo ativo, falha com instrução
  (item 2, inferência-only).
"""

from __future__ import annotations

import json

import duckdb
import pandas as pd
import pytest
from pydantic import ValidationError

from analytics.anomalies.anomalies import (
    avaliar_criterios,
    executar_carga_outliers,
)
from analytics.anomalies.diagnostics import (
    COLUNAS_DIAG,
    TABELA_DIAG,
    calcular_diagnostico,
    executar_diagnostico,
    gravar_diagnostico,
)
from analytics.anomalies.model import (
    PREFIXO_FAMILIA,
    TABELA_REGISTRO,
    ativar_modelo,
    carregar_modelo_ativo,
    congelar_e_registrar,
    main,
    medir_variabilidade_seed,
    treinar_modelo,
)
from pipeline.config import AnomaliasSettings, load_analytics_settings


# ── Config: max_samples (ADR-065, Contexto, item d) ─────────────


def test_max_samples_none_rejeitado():
    """`null`/`None` é rejeitado na carga — o fit do sklearn lança erro."""
    with pytest.raises(ValidationError):
        AnomaliasSettings.model_validate({"max_samples": None})


def test_max_samples_um_rejeitado():
    """`1.0`/`1` muda a taxa de sinalização e não elimina a seed (Contexto d)."""
    with pytest.raises(ValidationError):
        AnomaliasSettings.model_validate({"max_samples": 1.0})
    with pytest.raises(ValidationError):
        AnomaliasSettings.model_validate({"max_samples": 1})


def test_max_samples_aceitos():
    """`auto`, inteiro ≥ 2 e fração em (0, 1) são válidos."""
    assert AnomaliasSettings(max_samples="auto").max_samples == "auto"
    assert AnomaliasSettings(max_samples=4096).max_samples == 4096
    assert AnomaliasSettings(max_samples=0.5).max_samples == 0.5
    with pytest.raises(ValidationError):
        AnomaliasSettings(max_samples="none")
    with pytest.raises(ValidationError):
        AnomaliasSettings(max_samples=256.0 * 0)  # 0 inválido (inteiro < 2)


def test_yaml_analytics_carrega_anomalias():
    """`config/analytics.yaml` valida com o namespace `analytics.anomalias`."""
    cfg = load_analytics_settings()
    assert cfg.anomalias.random_state == 42
    assert cfg.anomalias.n_estimators == 100
    assert cfg.anomalias.max_samples == "auto"
    assert cfg.anomalias.contamination == 0.05


# ── Ordem canônica e estabilidade (ADR-065, item 1 / critério A1) ─


def _valores_exercicio() -> pd.Series:
    """Cauda pesada determinística (sem aleatoriedade de teste)."""
    return pd.Series([100.0] * 180 + [500.0] * 15 + [2000.0] * 4 + [90000.0])


def test_treino_ordem_canonica_nao_depende_da_ordem_das_linhas():
    """Embaralhar a ordem do MESMO vetor de treino produz o MESMO modelo."""
    valores = _valores_exercicio()
    ordenados = valores.sample(frac=1.0, random_state=7)
    m1 = treinar_modelo(valores, cfg=AnomaliasSettings())
    m2 = treinar_modelo(ordenados, cfg=AnomaliasSettings())
    x = valores.to_numpy().reshape(-1, 1)
    assert (m1.decision_function(x) == m2.decision_function(x)).all()


def test_inferencia_congelada_embaralhar_linhas_nao_muda_flags():
    """A1 em miniatura: modelo congelado + linhas embaralhadas → 0 flips."""
    valores = _valores_exercicio()
    modelo = treinar_modelo(valores, cfg=AnomaliasSettings())
    fatos = pd.DataFrame(
        {
            "id_despesa": range(1, len(valores) + 1),
            "id_parlamentar": [1] * len(valores),
            "valor_liquido": valores,
        }
    )
    r1 = avaliar_criterios(fatos, modelo_if=modelo)
    r2 = avaliar_criterios(
        fatos.sample(frac=1.0, random_state=13), modelo_if=modelo
    ).sort_values("id_despesa")
    assert (r1["criterio_if"].to_numpy() == r2["criterio_if"].to_numpy()).all()
    assert (r1["if_score"].to_numpy() == r2["if_score"].to_numpy()).all()


def test_variabilidade_entre_seeds_medida_e_nao_zero_assumida():
    """Item 4: a variabilidade é medida no treino e vem no manifesto."""
    valores = _valores_exercicio()
    medida = medir_variabilidade_seed(valores, cfg=AnomaliasSettings())
    assert medida["seed_a"] == 42
    assert medida["seed_b"] == 43
    assert medida["flags_diferentes"] >= 0
    assert medida["n_sinalizados_a"] > 0


# ── Ciclo de vida do artefato (ADR-065, itens 2–3) ──────────────


def test_ciclo_congelar_registrar_ativar_carregar(tmp_path):
    db = tmp_path / "pipe.duckdb"
    store = tmp_path / "models"
    manifesto = congelar_e_registrar(
        _valores_exercicio(),
        anos=[2023, 2024],
        db_path=db,
        store_dir=store,
        model_version="anomaly-1.0",
    )
    assert (store / "anomaly-1.0" / "model.joblib").exists()
    assert (store / "anomaly-1.0" / "manifest.json").exists()

    con = duckdb.connect(str(db))
    try:
        row = con.execute(
            f"select status, family from {TABELA_REGISTRO} where model_version = 'anomaly-1.0'"
        ).fetchone()
    finally:
        con.close()
    assert row == ("candidate", "anomaly")

    ativar_modelo(
        "anomaly-1.0", db_path=db, referencia="aceite ADR-065", store_dir=store
    )
    modelo, registro = carregar_modelo_ativo(db_path=db, store_dir=store)
    assert registro["model_version"] == "anomaly-1.0"
    assert registro["manifest_sha256"] == manifesto["artifact"]["sha256"]
    assert modelo.decision_function([[100.0]]).shape == (1,)


def test_manifesto_registra_hiperparametros_e_dados(tmp_path):
    db = tmp_path / "pipe.duckdb"
    store = tmp_path / "models"
    manifesto = congelar_e_registrar(
        _valores_exercicio(),
        anos=[2024],
        db_path=db,
        store_dir=store,
    )
    assert manifesto["hyperparameters"] == {
        "random_state": 42,
        "n_estimators": 100,
        "max_samples": "auto",
        "contamination": 0.05,
    }
    assert manifesto["dados"]["anos"] == [2024]
    assert manifesto["dados"]["n_valores"] == 200
    assert manifesto["seed_variabilidade"]["flags_diferentes"] >= 0
    gravado = json.loads((store / "anomaly-1.0" / "manifest.json").read_text())
    assert gravado["artifact"]["sha256"] == manifesto["artifact"]["sha256"]


def test_model_version_imutavel(tmp_path):
    db = tmp_path / "pipe.duckdb"
    store = tmp_path / "models"
    congelar_e_registrar(_valores_exercicio(), anos=[2024], db_path=db, store_dir=store)
    with pytest.raises(ValueError, match="imutáveis"):
        congelar_e_registrar(
            _valores_exercicio(), anos=[2024], db_path=db, store_dir=store
        )


def test_familia_obrigatoria(tmp_path):
    with pytest.raises(ValueError, match=PREFIXO_FAMILIA):
        congelar_e_registrar(
            _valores_exercicio(),
            anos=[2024],
            db_path=tmp_path / "p.duckdb",
            store_dir=tmp_path / "m",
            model_version="risk-9.9",
        )


def test_um_active_por_familia(tmp_path):
    db = tmp_path / "pipe.duckdb"
    store = tmp_path / "models"
    congelar_e_registrar(_valores_exercicio(), anos=[2024], db_path=db, store_dir=store)
    congelar_e_registrar(
        _valores_exercicio() * 1.1,
        anos=[2024],
        db_path=db,
        store_dir=store,
        model_version="anomaly-1.1",
    )
    ativar_modelo("anomaly-1.0", db_path=db, referencia="v1", store_dir=store)
    with pytest.raises(ValueError, match="já existe modelo ativo"):
        ativar_modelo("anomaly-1.1", db_path=db, referencia="v2", store_dir=store)
    ativar_modelo(
        "anomaly-1.1", db_path=db, referencia="v2", substituir=True, store_dir=store
    )
    modelo, registro = carregar_modelo_ativo(db_path=db, store_dir=store)
    assert registro["model_version"] == "anomaly-1.1"


def test_ativacao_exige_referencia_humana(tmp_path):
    db = tmp_path / "pipe.duckdb"
    store = tmp_path / "models"
    congelar_e_registrar(_valores_exercicio(), anos=[2024], db_path=db, store_dir=store)
    with pytest.raises(ValueError, match="referencia"):
        ativar_modelo("anomaly-1.0", db_path=db, referencia="   ", store_dir=store)


def test_artefato_corrompido_rejeitado(tmp_path):
    db = tmp_path / "pipe.duckdb"
    store = tmp_path / "models"
    congelar_e_registrar(_valores_exercicio(), anos=[2024], db_path=db, store_dir=store)
    ativar_modelo("anomaly-1.0", db_path=db, referencia="ok", store_dir=store)
    (store / "anomaly-1.0" / "model.joblib").write_bytes(b"corrompido")
    with pytest.raises(ValueError, match="corrompido"):
        carregar_modelo_ativo(db_path=db, store_dir=store)


# ── Inferência-only: sem modelo ativo, o passo falha (item 2) ────


def test_sem_modelo_ativo_carga_falha_com_instrucao(tmp_path, monkeypatch):
    db = tmp_path / "pipe.duckdb"
    monkeypatch.setenv("ANOMALY_MODEL_STORE", str(tmp_path / "models"))
    fatos = pd.DataFrame(
        {
            "id_despesa": [1, 2],
            "id_parlamentar": [1, 1],
            "id_fornecedor": [10, 10],
            "data_sk": [20240501, 20240501],
            "valor_liquido": [100.0, 100.0],
        }
    )
    with pytest.raises(RuntimeError, match="ADR-065"):
        executar_carga_outliers(fatos, run_id="r", db_path=str(db))


# ── Monitor de deriva informativo (ADR-065, item 5) ─────────────


def _fatos_diagnostico() -> pd.DataFrame:
    """Janela 2023–2024 (referência) + 2025 (fora da janela)."""
    linhas = []
    id_despesa = 1
    for ano, n in ((2023, 120), (2024, 120), (2025, 60)):
        for i in range(n):
            linhas.append(
                {
                    "id_despesa": id_despesa,
                    "id_parlamentar": 1,
                    "id_fornecedor": 10,
                    "data_sk": ano * 10000 + 501,
                    "valor_liquido": 100.0 + (i % 40) * 25.0 + (0.0 if ano != 2025 else 50.0),
                }
            )
            id_despesa += 1
    return pd.DataFrame(linhas)


def test_diagnostico_por_ano_vs_janela_de_referencia():
    """Taxa por ano + quantis de score contra a janela fechada do manifesto."""
    fatos = _fatos_diagnostico()
    modelo = treinar_modelo(
        fatos.loc[fatos["data_sk"] < 20250000, "valor_liquido"],
        cfg=AnomaliasSettings(),
    )
    registro = {"model_version": "anomaly-1.0", "manifest_sha256": "abc123"}
    diag = calcular_diagnostico(
        fatos, None, modelo=modelo, anos_janela=[2023, 2024], registro=registro
    )
    assert list(diag.columns) == COLUNAS_DIAG
    assert sorted(diag["ano"].tolist()) == [2023, 2024, 2025]
    assert diag["taxa_if"].between(0.0, 1.0).all()
    assert diag["taxa_anomalia"].between(0.0, 1.0).all()
    janela = fatos[fatos["data_sk"] < 20250000]
    scores_janela = pd.Series(
        modelo.decision_function(
            pd.to_numeric(janela["valor_liquido"]).to_numpy(dtype=float).reshape(-1, 1)
        )
    )
    ref = diag[diag["ano"] == 2023]
    assert ref["ref_score_p99"].iloc[0] == pytest.approx(scores_janela.quantile(0.99))
    assert diag["ref_score_p99"].nunique() == 1
    assert diag["model_version"].eq("anomaly-1.0").all()
    assert diag["manifest_sha256"].eq("abc123").all()
    assert (diag["delta_p99_vs_ref"] == diag["score_p99"] - diag["ref_score_p99"]).all()


def test_gravar_diagnostico_append(tmp_path):
    """Gravação appenda em `control.anomaly_model_diagnostics`."""
    fatos = _fatos_diagnostico()
    modelo = treinar_modelo(fatos["valor_liquido"], cfg=AnomaliasSettings())
    registro = {"model_version": "anomaly-1.0", "manifest_sha256": "abc"}
    diag = calcular_diagnostico(
        fatos, None, modelo=modelo, anos_janela=[2023], registro=registro
    )
    db = tmp_path / "diag.duckdb"
    assert gravar_diagnostico(diag, db_path=db) == len(diag)
    assert gravar_diagnostico(diag, db_path=db) == len(diag)
    con = duckdb.connect(str(db))
    try:
        n = con.execute(f"SELECT count(*) FROM {TABELA_DIAG}").fetchone()[0]
    finally:
        con.close()
    assert n == 2 * len(diag)


def test_diagnose_cli_inferencia_pura(tmp_path):
    """`diagnose` grava o monitor SEM treinar nem mexer no registro (item 5)."""
    db = tmp_path / "diag.duckdb"
    store = tmp_path / "models"
    congelar_e_registrar(
        _fatos_diagnostico().query("data_sk < 20250000")["valor_liquido"],
        anos=[2023, 2024],
        db_path=db,
        store_dir=store,
        model_version="anomaly-1.0",
    )
    ativar_modelo("anomaly-1.0", db_path=db, referencia="ok", store_dir=store)
    artefato = (store / "anomaly-1.0" / "model.joblib").read_bytes()

    con = duckdb.connect(str(db))
    try:
        con.execute("CREATE SCHEMA gold")
        con.execute(
            "CREATE TABLE gold.fact_despesa AS SELECT * FROM "
            "(SELECT 1::BIGINT AS id_despesa, 1::BIGINT AS id_parlamentar, "
            " 10::BIGINT AS id_fornecedor, 20230501 AS data_sk, 100.0 AS valor_liquido)"
        )
        con.execute(
            "CREATE TABLE gold.dim_data AS SELECT 20230501 AS data_sk, "
            "2023 AS ano, 5 AS mes, TRUE AS is_dia_util, DATE '2023-05-01' AS data"
        )
        antes = con.execute(
            f"SELECT count(*), max(status) FROM {TABELA_REGISTRO}"
        ).fetchone()
    finally:
        con.close()

    rc = main(["diagnose", "--db", str(db), "--store-dir", str(store)])
    assert rc == 0

    con = duckdb.connect(str(db))
    try:
        depois = con.execute(
            f"SELECT count(*), max(status) FROM {TABELA_REGISTRO}"
        ).fetchone()
        linhas = con.execute(f"SELECT count(*) FROM {TABELA_DIAG}").fetchone()[0]
        modelo_ativo = con.execute(
            f"SELECT model_version FROM {TABELA_REGISTRO} WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        con.close()
    assert depois == antes
    assert linhas == 1
    assert modelo_ativo == "anomaly-1.0"
    assert (store / "anomaly-1.0" / "model.joblib").read_bytes() == artefato


def test_executar_diagnostico_sem_modelo_ativo_falha(tmp_path):
    """Sem modelo ativo o monitor falha como o passo de anomalias (item 5)."""
    db = tmp_path / "vazio.duckdb"
    with pytest.raises(RuntimeError, match="ADR-065"):
        executar_diagnostico(db_path=db, store_dir=tmp_path / "models")
