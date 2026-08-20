#!/bin/bash
# Executa o pipeline diário do Observatório Parlamentar na VPS Oracle (ADR-034).
#
# Uso: bash scripts/run_pipeline_daily.sh
#
# Comportamento:
#   1. Sobe o perfil `pipeline` (postgres + airflow-scheduler) — o webserver
#      é desnecessário para execução batch (economiza recursos, ADR-007).
#   2. Aguarda o Airflow ficar pronto (healthcheck via `airflow dags
#      list-import-errors`, sem depender de porta HTTP do webserver).
#   3. Despausa o DAG `observatorio_pipeline` (docker-compose define
#      DAGS_ARE_PAUSED_AT_CREATION=True — sem unpause explícito o DAG nunca
#      dispara) e o aciona via `airflow dags trigger --run-id`, com um run_id
#      determinístico (facilita o polling e a rastreabilidade).
#   4. Acompanha o estado da execução via `airflow dags list-runs --output
#      json` até SUCCESS, com timeout duplo (interno configurável + margem do
#      systemd).
#   5. Garante `docker compose --profile pipeline down` ao final (trap
#      EXIT) — containers do perfil não ficam residentes (ADR-007).
#
# Nota de compatibilidade Airflow 2.9: `airflow dags state` espera
# `execution_date` (tipo parsedate), NÃO run_id — por isso o polling usa
# `list-runs --output json` filtrando pelo run_id, que é estável entre
# versões.
#
# Timeouts e intervalos são configuráveis via env vars (ADR-008), sem
# hardcode. Exit code não-zero sinaliza falha (o systemd não faz retry
# automático; a próxima tentativa é o próximo disparo do timer).

set -euo pipefail

# ── Configuração (env vars, ADR-008) ────────────────────────────
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
COMPOSE_PROFILE_ARGS="${COMPOSE_PROFILE_ARGS:---profile pipeline}"

# Tempo máximo para o Airflow ficar pronto (healthcheck do scheduler).
AIRFLOW_READY_TIMEOUT_SEC="${AIRFLOW_READY_TIMEOUT_SEC:-180}"
# Intervalo entre polls do estado da execução.
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-30}"
# Timeout interno da execução do DAG (deve ser menor que o do systemd).
DAG_TIMEOUT_SEC="${DAG_TIMEOUT_SEC:-5400}"

DAG_ID="observatorio_pipeline"

log() {
    echo "[$(date -Iseconds)] $*"
}

# ── Cleanup garantido (ADR-007: perfil não fica residente) ──────
cleanup() {
    log "Finalizando: docker compose ${COMPOSE_PROFILE_ARGS} down"
    cd "$PROJECT_DIR"
    docker compose ${COMPOSE_PROFILE_ARGS} down
}
trap cleanup EXIT

# ── Helpers ─────────────────────────────────────────────────────
airflow_cli() {
    # Roda o CLI do Airflow dentro do container do scheduler.
    docker compose ${COMPOSE_PROFILE_ARGS} exec -T airflow-scheduler airflow "$@"
}

wait_airflow_ready() {
    log "Aguardando o Airflow ficar pronto (timeout ${AIRFLOW_READY_TIMEOUT_SEC}s)..."
    espera=0
    until airflow_cli dags list-import-errors >/dev/null 2>&1; do
        if [ "$espera" -ge "$AIRFLOW_READY_TIMEOUT_SEC" ]; then
            log "ERRO: Airflow não ficou pronto em ${AIRFLOW_READY_TIMEOUT_SEC}s"
            return 1
        fi
        sleep 10
        espera=$((espera + 10))
    done
    log "Airflow pronto."
}

dag_run_state() {
    # Estado do run específico via list-runs --output json (estável entre
    # versões; filtra pelo run_id determinístico disparado).
    airflow_cli dags list-runs --dag-id "$DAG_ID" --output json 2>/dev/null \
        | python3 -c "
import json, sys
run_id = sys.argv[1]
dados = json.load(sys.stdin)
for r in dados:
    if r.get('run_id') == run_id:
        print(r.get('state', 'unknown'))
        break
else:
    print('unknown')
" "$1"
}

# ── Fluxo principal ─────────────────────────────────────────────
cd "$PROJECT_DIR"

log "Subindo perfil pipeline (postgres + airflow-scheduler)..."
docker compose ${COMPOSE_PROFILE_ARGS} up -d postgres airflow-scheduler

wait_airflow_ready || exit 1

log "Despausando DAG ${DAG_ID} (DAGS_ARE_PAUSED_AT_CREATION=True)..."
airflow_cli dags unpause "$DAG_ID" >/dev/null 2>&1 || true

# run_id determinístico e rastreável (o local_client default escreve direto
# no DB — funciona sem webserver).
run_id="daily_$(date -u +%Y%m%dT%H%M%SZ)"
log "Disparando DAG ${DAG_ID} (run_id=${run_id})..."
if ! airflow_cli dags trigger "$DAG_ID" --run-id "$run_id" >/dev/null 2>&1; then
    log "ERRO: falha ao disparar o DAG."
    exit 1
fi

log "Aguardando conclusão (timeout ${DAG_TIMEOUT_SEC}s)..."
inicio=$(date +%s)
while true; do
    estado="$(dag_run_state "$run_id")"
    agora=$(date +%s)
    decorrido=$((agora - inicio))
    case "$estado" in
        success)
            log "DAG ${DAG_ID} concluído com SUCCESS (${decorrido}s)."
            exit 0
            ;;
        failed | upstream_failed | skipped)
            log "ERRO: DAG ${DAG_ID} terminou em estado ${estado} (${decorrido}s)."
            exit 1
            ;;
        *)
            if [ "$decorrido" -ge "$DAG_TIMEOUT_SEC" ]; then
                log "ERRO: timeout de ${DAG_TIMEOUT_SEC}s atingido aguardando o DAG."
                exit 1
            fi
            log "  estado=${estado}, decorrido=${decorrido}s (poll em ${POLL_INTERVAL_SEC}s)"
            sleep "$POLL_INTERVAL_SEC"
            ;;
    esac
done
