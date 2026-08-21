#!/bin/bash
# scripts/run_hml_e2e.sh — Teste E2E do pipeline no ambiente HML (homologação).
#
# Valida o fluxo completo Bronze→Silver→Gold com JANELA CURTA (2 meses, modo
# validacao) e o comportamento do watermark em duas execuções:
#   1ª execução: backfill da janela (watermark vazio → varre `limite_periodos`).
#   2ª execução: incremental (período seguinte ao watermark consolidado).
#
# Isolamento do PRD (mesma VPS, projeto separado):
#   - overlay compose: -f docker-compose.yml -f docker-compose.hml.yml
#   - projeto: -p hml  → volumes/rede/containers com prefixo hml_
#   - env: --env-file .env.hml (credenciais próprias, nunca .env do PRD)
#   - config: ./config.hml (validacao.habilitado: true, limite_periodos: 2)
#   - dados: ./data.hml (DuckDB/Parquet isolados)
#
# Uso (na VPS, raiz do repo):
#   bash scripts/run_hml_e2e.sh
#
# Exit 0 = sucesso (ambas as execuções SUCCESS); não-zero = falha.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT_DIR"

HML_ENV_FILE="${HML_ENV_FILE:-.env.hml}"
COMPOSE_BASE="-f docker-compose.yml -f docker-compose.hml.yml"
COMPOSE_ARGS="--env-file ${HML_ENV_FILE} -p hml ${COMPOSE_BASE}"

DAG_ID="observatorio_pipeline"
# Tempo curto: janela de 2 meses não demora mais que ~10-15 min.
DAG_TIMEOUT_SEC="${DAG_TIMEOUT_SEC:-1800}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-15}"

log() { echo "[$(date -Iseconds)] $*"; }

cleanup() {
    log "Finalizando: removendo containers do perfil pipeline HML"
    docker compose ${COMPOSE_ARGS} --profile pipeline stop postgres airflow-scheduler minio api >/dev/null 2>&1 || true
    docker compose ${COMPOSE_ARGS} --profile pipeline rm -f postgres airflow-scheduler minio api >/dev/null 2>&1 || true
}
trap cleanup EXIT

airflow_cli() {
    docker compose ${COMPOSE_ARGS} exec -T airflow-scheduler airflow "$@"
}

wait_airflow_ready() {
    log "Aguardando o Airflow HML ficar pronto (timeout ${AIRFLOW_READY_TIMEOUT_SEC:-180}s)..."
    espera=0
    until airflow_cli dags list-import-errors >/dev/null 2>&1; do
        if [ "$espera" -ge "${AIRFLOW_READY_TIMEOUT_SEC:-180}" ]; then
            log "ERRO: Airflow HML não ficou pronto."
            return 1
        fi
        sleep 10
        espera=$((espera + 10))
    done
    log "Airflow HML pronto."
}

dag_run_state() {
    airflow_cli dags list-runs --dag-id "$DAG_ID" --output json 2>/dev/null \
        | python3 -c "
import json, sys
run_id = sys.argv[1]
for r in json.load(sys.stdin):
    if r.get('run_id') == run_id:
        print(r.get('state', 'unknown'))
        break
else:
    print('unknown')
" "$1"
}

wait_dag() {
    local run_id="$1" inicio agora decorrido estado
    inicio=$(date +%s)
    while true; do
        estado="$(dag_run_state "$run_id")"
        agora=$(date +%s)
        decorrido=$((agora - inicio))
        case "$estado" in
            success) log "  [${run_id}] SUCCESS (${decorrido}s)"; return 0 ;;
            failed | upstream_failed | skipped)
                log "  [${run_id}] ERRO: estado ${estado} (${decorrido}s)"
                return 1 ;;
            *)
                if [ "$decorrido" -ge "$DAG_TIMEOUT_SEC" ]; then
                    log "  [${run_id}] ERRO: timeout de ${DAG_TIMEOUT_SEC}s."
                    return 1
                fi
                log "  [${run_id}] estado=${estado}, decorrido=${decorrido}s"
                sleep "$POLL_INTERVAL_SEC"
                ;;
        esac
    done
}

# ── Fluxo ──────────────────────────────────────────────────────
log "Subindo perfil pipeline HML (postgres + airflow-scheduler + minio + api)..."
docker compose ${COMPOSE_ARGS} --profile pipeline up -d postgres airflow-scheduler minio api

wait_airflow_ready || exit 1

log "Despausando DAG ${DAG_ID}..."
airflow_cli dags unpause "$DAG_ID" >/dev/null 2>&1 || true

# ── 1ª execução: backfill da janela (watermark vazio) ──────────
RUN1="hml_backfill_$(date -u +%Y%m%dT%H%M%SZ)"
log "1ª execução (backfill janela 2 meses): run_id=${RUN1}"
airflow_cli dags trigger "$DAG_ID" --run-id "$RUN1" >/dev/null 2>&1 \
    || { log "ERRO: falha ao disparar run 1."; exit 1; }
wait_dag "$RUN1" || exit 1

log "Conferindo watermark após 1ª execução..."
airflow_cli variables get "validacao:watermark_camara_despesas" 2>/dev/null \
    && airflow_cli variables get "validacao:watermark_senado" 2>/dev/null \
    || log "  (watermarks não visíveis via CLI — conferir em DB se necessário)"

# ── 2ª execução: incremental (mês seguinte ao watermark) ───────
RUN2="hml_incremental_$(date -u +%Y%m%dT%H%M%SZ)"
log "2ª execução (incremental): run_id=${RUN2}"
airflow_cli dags trigger "$DAG_ID" --run-id "$RUN2" >/dev/null 2>&1 \
    || { log "ERRO: falha ao disparar run 2."; exit 1; }
wait_dag "$RUN2" || exit 1

log "E2E HML concluído com SUCCESS (backfill + incremental)."
log "Validar: http://127.0.0.1:18000/docs (API HML) e ./data.hml/silver/observatorio.duckdb"
exit 0