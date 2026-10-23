"""analytics/anomalies/model.py — modelo de anomalia de despesas congelado (ADR-065).

O Isolation Forest do critério 2 (ADR-002) deixa de ser retreinado a cada
carga. Este módulo implementa o ciclo de VIDA do modelo (ADR-065, itens 2–4):

- **treino explícito** (`train`): janela de anos fechados → vetor de
  `valor_liquido` **ordenado por valor** (ordem canônica, item 1) → `fit` →
  serialização joblib + `manifest.json` (sha256, versões das bibliotecas,
  identidade dos dados, hiperparâmetros, variabilidade entre seeds) →
  registro como artefato `anomaly-<MAJOR>.<MINOR>` com status `candidate`
  em `control.risk_model_registry` (contrato do ADR-064);
- **ativação humana** (`activate`): `candidate|retired → active` com
  referência da decisão registrada; no máximo um `active` por família
  (ADR-065, item 2);
- **inferência**: `carregar_modelo_ativo` é o único caminho de leitura do
  passo de anomalias (`analytics/anomalies/anomalies.py`, inferência-only
  com threshold `-0.1` — ADR-002/ADR-065).

Armazenamento: diretório local `data/models/` (dev e testes; gitignored) ou
o path de `ANOMALY_MODEL_STORE`. O backend MinIO previsto no ADR-064 (prefixo
por `model_version`) entra junto com os artefatos do modelo de risco — o
layout do store é o mesmo (`<store>/<model_version>/model.joblib` +
`manifest.json`).

- **monitor de deriva** (`diagnose`, ADR-065, item 5): taxa de sinalização
  do modelo congelado por ano + distribuição dos scores vs. janela de
  referência, gravado em `control.anomaly_model_diagnostics`; **nunca
  retreina**.

Armazenamento: diretório local `data/models/` (dev e testes; gitignored) ou
o path de `ANOMALY_MODEL_STORE`. O backend MinIO previsto no ADR-064 (prefixo
por `model_version`) entra junto com os artefatos do modelo de risco — o
layout do store é o mesmo (`<store>/<model_version>/model.joblib` +
`manifest.json`).

Uso:
    python -m analytics.anomalies.model train  --db <duckdb> --anos 2023,2024,2025
    python -m analytics.anomalies.model activate --db <duckdb> \\
        --model-version anomaly-1.0 --referencia "ADR-065 aceito — Sprint 29"
    python -m analytics.anomalies.model diagnose --db <duckdb>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

from pipeline.config import REPO_ROOT, get_analytics, get_pipeline_version

logger = structlog.get_logger()

#: Prefixo de família (ADR-065, item 2) — um `active` por família.
PREFIXO_FAMILIA = "anomaly-"

#: Tabela de registro (ADR-064, item 3; ADR-065 estende a duas famílias).
TABELA_REGISTRO = "control.risk_model_registry"

#: Store local padrão quando `ANOMALY_MODEL_STORE` não está definido.
STORE_PADRAO = REPO_ROOT / "data" / "models"


# ── Treino (ADR-065, itens 1, 3 e 4) ────────────────────────────


def treinar_modelo(
    valores: pd.Series,
    *,
    cfg=None,
):
    """Treina o Isolation Forest de despesas com ordem canônica (ADR-065).

    O vetor de treino é **ordenado por valor** antes do `fit` — pré-condição
    universal do ADR-065, item 1: remove a componente de ordem de forma
    exata, sem depender de chave de linha nem de `id_despesa`.

    Args:
        valores: Valores monetários das despesas da janela de referência.
        cfg: `AnomaliasSettings` (`pipeline.config`); padrão `get_analytics().anomalias`.

    Returns:
        `sklearn.ensemble.IsolationForest` ajustado.
    """
    from sklearn.ensemble import IsolationForest

    cfg = cfg or get_analytics().anomalias
    v = pd.to_numeric(valores, errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    ordenado = np.sort(v)
    modelo = IsolationForest(
        n_estimators=cfg.n_estimators,
        max_samples=cfg.max_samples,
        contamination=cfg.contamination,
        random_state=cfg.random_state,
    )
    modelo.fit(ordenado.reshape(-1, 1))
    return modelo


def _sinalizados(modelo, ordenado: np.ndarray) -> np.ndarray:
    """Flags do critério 2 em inferência (score < -0.1, ADR-002)."""
    return modelo.decision_function(ordenado.reshape(-1, 1)) < -0.1


def medir_variabilidade_seed(valores: pd.Series, *, cfg=None, modelo=None) -> dict:
    """Variabilidade entre duas seeds sobre a janela de referência (ADR-065, item 4).

    Nunca assume zero: treina um segundo modelo com `random_state + 1` sobre
    o MESMO vetor ordenado e conta os flags diferentes na janela.

    Args:
        valores: Valores da janela de referência.
        cfg: `AnomaliasSettings`; padrão o de `get_analytics()`.
        modelo: Modelo principal já treinado (evita retreinar).

    Returns:
        Dict com seeds, flags distintos e contagens de sinalizados de cada um.
    """
    cfg = cfg or get_analytics().anomalias
    if modelo is None:
        modelo = treinar_modelo(valores, cfg=cfg)
    v = pd.to_numeric(valores, errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    ordenado = np.sort(v)
    from sklearn.ensemble import IsolationForest

    cfg_b = cfg.model_copy(update={"random_state": cfg.random_state + 1})
    modelo_b = IsolationForest(
        n_estimators=cfg_b.n_estimators,
        max_samples=cfg_b.max_samples,
        contamination=cfg_b.contamination,
        random_state=cfg_b.random_state,
    )
    modelo_b.fit(ordenado.reshape(-1, 1))
    flags_a = _sinalizados(modelo, ordenado)
    flags_b = _sinalizados(modelo_b, ordenado)
    return {
        "seed_a": cfg.random_state,
        "seed_b": cfg_b.random_state,
        "n_sinalizados_a": int(flags_a.sum()),
        "n_sinalizados_b": int(flags_b.sum()),
        "flags_diferentes": int((flags_a != flags_b).sum()),
    }


# ── Artefato + manifesto (ADR-064, item 2 / ADR-065, item 2) ────


def _sha256_bytes(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _git_commit() -> str | None:
    """Commit atual do repositório (best-effort — identidade de código)."""
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            or None
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _sha256_modulos() -> dict:
    """sha256 dos módulos de anomalia (identidade de código, ADR-064, item 2d)."""
    identidade = {}
    for nome in ("anomalies.py", "model.py"):
        caminho = Path(__file__).resolve().parent / nome
        identidade[nome] = _sha256_bytes(caminho.read_bytes())
    return identidade


def construir_manifesto(
    *,
    model_version: str,
    joblib_bytes: bytes,
    cfg,
    valores: pd.Series,
    anos: list[int],
    variabilidade_seed: dict,
    tabela: str = "gold.fact_despesa",
) -> dict:
    """Manifesto do artefato (ADR-064, item 2 — subset do modelo de anomalia).

    Registra sha256 do joblib, versões das bibliotecas, identidade do código,
    identidade dos dados (janela, contagem, soma, hash dos valores ordenados)
    e a variabilidade medida entre seeds (nunca assumida zero).
    """
    import joblib
    import pandas as __pandas
    from sklearn import __version__ as sklearn_version

    v = pd.to_numeric(valores, errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    ordenado = np.sort(v)
    dados = {
        "tabela": tabela,
        "anos": sorted(anos),
        "n_valores": int(ordenado.size),
        "soma_valores": float(ordenado.sum()),
        "sha256_valores_ordenados": _sha256_bytes(ordenado.tobytes()),
    }
    config_sha256 = _sha256_bytes(
        json.dumps(cfg.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    )
    return {
        "model_version": model_version,
        "family": "anomaly",
        "created_at": datetime.now(UTC).isoformat(),
        "artifact": {
            "filename": "model.joblib",
            "sha256": _sha256_bytes(joblib_bytes),
            "bytes": len(joblib_bytes),
        },
        "hyperparameters": {
            "random_state": cfg.random_state,
            "n_estimators": cfg.n_estimators,
            "max_samples": cfg.max_samples,
            "contamination": cfg.contamination,
        },
        "threshold_score_inferencia": -0.1,
        "bibliotecas": {
            "scikit-learn": sklearn_version,
            "numpy": np.__version__,
            "pandas": __pandas.__version__,
            "joblib": joblib.__version__,
            "python": sys.version.split()[0],
        },
        "codigo": {
            "pipeline_version": get_pipeline_version(),
            "git_commit": _git_commit(),
            "sha256_modulos": _sha256_modulos(),
        },
        "dados": dados,
        "data_fingerprint": _sha256_bytes(
            json.dumps(dados, sort_keys=True).encode("utf-8")
        ),
        "seed_variabilidade": variabilidade_seed,
        "config_sha256": config_sha256,
    }


def _resolver_store(store_dir: str | Path | None) -> Path:
    if store_dir is not None:
        return Path(store_dir)
    env = os.environ.get("ANOMALY_MODEL_STORE")
    return Path(env) if env else STORE_PADRAO


def _persistir_artefato(store: Path, model_version: str, joblib_bytes: bytes, manifesto: dict) -> Path:
    """Grava `<store>/<model_version>/{model.joblib,manifest.json}`."""
    destino = store / model_version
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "model.joblib").write_bytes(joblib_bytes)
    (destino / "manifest.json").write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destino


# ── Registro (ADR-064, item 3; ADR-065, item 2) ─────────────────


def _garantir_tabela(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS control")
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABELA_REGISTRO} (
            model_version VARCHAR PRIMARY KEY,
            family VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at VARCHAR NOT NULL,
            manifest_sha256 VARCHAR NOT NULL,
            data_fingerprint VARCHAR,
            source_reports VARCHAR,
            activated_at VARCHAR,
            activation_reference VARCHAR
        )
        """
    )


def _registrar_candidate(con, manifesto: dict) -> None:
    _garantir_tabela(con)
    con.execute(
        f"INSERT INTO {TABELA_REGISTRO} "
        "(model_version, family, status, created_at, manifest_sha256, "
        " data_fingerprint, source_reports) VALUES (?, ?, 'candidate', ?, ?, ?, ?)",
        [
            manifesto["model_version"],
            manifesto["family"],
            manifesto["created_at"],
            manifesto["artifact"]["sha256"],
            manifesto["data_fingerprint"],
            json.dumps(
                {"manifest": f"{manifesto['model_version']}/manifest.json"},
                ensure_ascii=False,
            ),
        ],
    )


def congelar_e_registrar(
    valores: pd.Series,
    *,
    anos: list[int],
    db_path: str | Path,
    cfg=None,
    store_dir: str | Path | None = None,
    model_version: str = "anomaly-1.0",
) -> dict:
    """Treina, congela (joblib + manifesto) e registra como `candidate`.

    Args:
        valores: `valor_liquido` da janela de referência.
        anos: Anos fechados da janela (identidade dos dados no manifesto).
        db_path: DuckDB com (ou para) `control.risk_model_registry`.
        cfg: `AnomaliasSettings`; padrão o de `get_analytics()`.
        store_dir: Store de artefatos; padrão `ANOMALY_MODEL_STORE` ou `data/models`.
        model_version: Identificador `anomaly-<MAJOR>.<MINOR>` (imutável).

    Returns:
        Manifesto gravado.

    Raises:
        ValueError: se `model_version` já existe no registro (imutabilidade).
        RuntimeError: se a janela estiver vazia.
    """
    import duckdb
    import joblib

    cfg = cfg or get_analytics().anomalias
    if not model_version.startswith(PREFIXO_FAMILIA):
        raise ValueError(
            f"model_version deve pertencer à família {PREFIXO_FAMILIA}* (ADR-065) — {model_version}"
        )
    if pd.to_numeric(valores, errors="coerce").dropna().empty:
        raise RuntimeError("janela de treino sem valores — informe --anos sobre Gold populado")

    modelo = treinar_modelo(valores, cfg=cfg)
    variabilidade = medir_variabilidade_seed(valores, cfg=cfg, modelo=modelo)
    buffer = io.BytesIO()
    joblib.dump(modelo, buffer)
    joblib_bytes = buffer.getvalue()
    manifesto = construir_manifesto(
        model_version=model_version,
        joblib_bytes=joblib_bytes,
        cfg=cfg,
        valores=valores,
        anos=anos,
        variabilidade_seed=variabilidade,
    )
    store = _resolver_store(store_dir)
    destino = _persistir_artefato(store, model_version, joblib_bytes, manifesto)

    con = duckdb.connect(str(db_path))
    try:
        _garantir_tabela(con)
        existe = con.execute(
            f"SELECT 1 FROM {TABELA_REGISTRO} WHERE model_version = ?",
            [model_version],
        ).fetchone()
        if existe:
            raise ValueError(
                f"model_version {model_version} já registrada — artefatos são imutáveis (ADR-064)"
            )
        _registrar_candidate(con, manifesto)
    finally:
        con.close()

    logger.info(
        "anomalias_modelo_congelado",
        model_version=model_version,
        artifact_dir=str(destino),
        manifest_sha256=manifesto["artifact"]["sha256"],
        data_fingerprint=manifesto["data_fingerprint"],
        flags_diferentes_entre_seeds=variabilidade["flags_diferentes"],
    )
    return manifesto


def carregar_modelo_ativo(
    *,
    db_path: str | Path,
    store_dir: str | Path | None = None,
):
    """Carrega o modelo de anomalia `active` para INFERÊNCIA (ADR-065, item 2).

    Verifica o sha256 do joblib contra o registro antes de carregar.

    Returns:
        (modelo `IsolationForest`, linha do registro como dict).

    Raises:
        RuntimeError: se não houver modelo `active` — o passo de anomalias
            NÃO retreina (ADR-065); é preciso treinar e ativar pelo CLI.
        ValueError: se o artefato estiver corrompido (sha256 divergente).
    """
    import duckdb
    import joblib

    if not Path(db_path).exists():
        raise RuntimeError(
            f"ADR-065: banco {db_path} inexistente — nenhum modelo de anomalia "
            "registrado; treinar (python -m analytics.anomalies.model train) e "
            "ativar (... activate --referencia ...) antes do passo de anomalias"
        )
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT model_version, status, manifest_sha256, activated_at, "
            " activation_reference FROM "
            f"{TABELA_REGISTRO} WHERE family = 'anomaly' AND status = 'active'"
        ).fetchone()
    except duckdb.CatalogException:
        row = None
    finally:
        con.close()
    if row is None:
        raise RuntimeError(
            "ADR-065: nenhum modelo de anomalia ativo em control.risk_model_registry — "
            "treinar (python -m analytics.anomalies.model train) e ativar "
            "(... activate --referencia ...) antes de executar o passo de anomalias"
        )
    model_version, _status, manifest_sha256, activated_at, referencia_ativacao = row
    caminho = _resolver_store(store_dir) / model_version / "model.joblib"
    if not caminho.exists():
        raise RuntimeError(
            f"artefato {caminho} ausente para o modelo ativo {model_version}"
        )
    conteudo = caminho.read_bytes()
    if _sha256_bytes(conteudo) != manifest_sha256:
        raise ValueError(
            f"sha256 do artefato {caminho} diverge do registro — artefato corrompido"
        )
    modelo = joblib.load(io.BytesIO(conteudo))
    registro = {
        "model_version": model_version,
        "manifest_sha256": manifest_sha256,
        "activated_at": activated_at,
        "activation_reference": referencia_ativacao,
    }
    logger.info(
        "anomalias_modelo_ativo_carregado",
        model_version=model_version,
        manifest_sha256=manifest_sha256,
    )
    return modelo, registro


def ativar_modelo(
    model_version: str,
    *,
    db_path: str | Path,
    referencia: str,
    substituir: bool = False,
    store_dir: str | Path | None = None,
) -> None:
    """Ativa um `candidate` (ou reativa um `retired`) — aprovação humana (ADR-065, item 2).

    No máximo um `active` por família: se já houver um ativo, falha a menos
    que `substituir=True` (aí o ativo vigente vira `retired` — reverter =
    reativar a versão anterior).

    Args:
        model_version: Versão a ativar.
        db_path: DuckDB com o registro.
        referencia: Referência da decisão humana que autoriza (obrigatória).
        substituir: Retira o `active` vigente da família antes de ativar.
        store_dir: Store de artefatos (valida existência do joblib).

    Raises:
        ValueError: versão inexistente, já ativa, ou ativo sem substituição.
    """
    import duckdb

    if not referencia.strip():
        raise ValueError("ativação exige --referencia com a decisão humana (ADR-064, item 4)")
    caminho = _resolver_store(store_dir) / model_version / "model.joblib"
    if not caminho.exists():
        raise ValueError(f"artefato do modelo ausente: {caminho}")

    con = duckdb.connect(str(db_path))
    try:
        _garantir_tabela(con)
        row = con.execute(
            f"SELECT status FROM {TABELA_REGISTRO} WHERE model_version = ?",
            [model_version],
        ).fetchone()
        if row is None:
            raise ValueError(f"model_version {model_version} não registrada")
        if row[0] == "active":
            raise ValueError(f"model_version {model_version} já está ativa")
        ativo = con.execute(
            "SELECT model_version FROM "
            f"{TABELA_REGISTRO} WHERE family = 'anomaly' AND status = 'active'"
        ).fetchone()
        agora = datetime.now(UTC).isoformat()
        if ativo:
            if not substituir:
                raise ValueError(
                    f"já existe modelo ativo na família anomaly: {ativo[0]} — "
                    "use --substituir para retirar (ADR-065, item 2)"
                )
            con.execute(
                f"UPDATE {TABELA_REGISTRO} SET status = 'retired' "
                "WHERE model_version = ?",
                [ativo[0]],
            )
        con.execute(
            f"UPDATE {TABELA_REGISTRO} SET status = 'active', activated_at = ?, "
            "activation_reference = ? WHERE model_version = ?",
            [agora, referencia, model_version],
        )
    finally:
        con.close()
    logger.info(
        "anomalias_modelo_ativado",
        model_version=model_version,
        referencia=referencia,
        substituiu=ativo[0] if ativo else None,
    )


# ── CLI ─────────────────────────────────────────────────────────


def _carregar_valores_janela(db_path: str | Path, anos: list[int]) -> pd.Series:
    """Lê `valor_liquido` de `gold.fact_despesa` para os anos fechados."""
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        marcadores = ",".join("?" for _ in anos)
        return con.execute(
            "SELECT valor_liquido FROM gold.fact_despesa "
            f"WHERE data_sk IS NOT NULL AND data_sk // 10000 IN ({marcadores})",
            list(anos),
        ).fetchdf()["valor_liquido"]
    finally:
        con.close()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: `train` (congelar), `activate` (aprovação) e `diagnose` (deriva)."""
    parser = argparse.ArgumentParser(
        description="Modelo de anomalia de despesas congelado (ADR-065)"
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    p_train = sub.add_parser("train", help="treinar sobre anos fechados e registrar candidate")
    p_train.add_argument("--db", required=True, help="DuckDB (Gold + control.risk_model_registry)")
    p_train.add_argument("--anos", required=True, help="anos fechados separados por vírgula (ex.: 2023,2024,2025)")
    p_train.add_argument("--model-version", default="anomaly-1.0")
    p_train.add_argument("--store-dir", default=None)
    p_act = sub.add_parser("activate", help="ativar candidate/retired com referência humana")
    p_act.add_argument("--db", required=True)
    p_act.add_argument("--model-version", required=True)
    p_act.add_argument("--referencia", required=True, help="referência da decisão humana")
    p_act.add_argument("--substituir", action="store_true")
    p_act.add_argument("--store-dir", default=None)
    p_diag = sub.add_parser(
        "diagnose", help="monitor de deriva informativo — nunca retreina (ADR-065, item 5)"
    )
    p_diag.add_argument("--db", required=True, help="DuckDB (Gold + registro + diagnóstico)")
    p_diag.add_argument("--store-dir", default=None)
    args = parser.parse_args(argv)
    try:
        if args.comando == "train":
            anos = sorted({int(a.strip()) for a in args.anos.split(",") if a.strip()})
            if not anos:
                raise ValueError("--anos sem anos válidos (ex.: 2023,2024,2025)")
            valores = _carregar_valores_janela(args.db, anos)
            congelar_e_registrar(
                valores,
                anos=anos,
                db_path=args.db,
                store_dir=args.store_dir,
                model_version=args.model_version,
            )
        elif args.comando == "activate":
            ativar_modelo(
                args.model_version,
                db_path=args.db,
                referencia=args.referencia,
                substituir=args.substituir,
                store_dir=args.store_dir,
            )
        else:
            from analytics.anomalies.diagnostics import executar_diagnostico

            resultado = executar_diagnostico(db_path=args.db, store_dir=args.store_dir)
            logger.info(
                "anomalias_diagnose_ok", linhas=len(resultado),
                anos=sorted(set(resultado["ano"])) if len(resultado) else [],
            )
    except ValueError as exc:
        logger.error("anomalias_modelo_config_error", error=str(exc))
        return 2
    except (OSError, RuntimeError) as exc:
        logger.error("anomalias_modelo_failed", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
