#!/bin/sh
# Seleciona o config do nginx conforme o estado do TLS (Gate 5).
# - Se o certificado já existe no volume certbot-etc: usa default.conf (HTTP+HTTPS)
# - Caso contrário: usa bootstrap.conf (só porta 80, para o desafio ACME)
# Os configs ficam em /etc/nginx/candidates e SÓ UM é copiado para conf.d —
# evita dois server blocks na mesma porta (erro de servidor duplicado).
#
# ADR-067: com o TLS ativo, inicia o loop de reload condicional. O loop
# roda em background; o entrypoint oficial termina com `exec nginx`, então
# o nginx continua como PID 1.
CERT_DIR=/etc/letsencrypt/live/observatorio-parlamentar.com.br
STATE_FILE=/run/nginx-cert-reload.sha256
INTERVAL="${NGINX_CERT_RELOAD_INTERVAL_SECONDS:-21600}"

# Falha no start (não 6h depois) se o intervalo for inválido.
case "$INTERVAL" in
    ''|*[!0-9]*)
        echo "NGINX_CERT_RELOAD_INTERVAL_SECONDS inválido: '$INTERVAL' (inteiro > 0)" >&2
        exit 1
        ;;
esac
# Normaliza zeros à esquerda (ex.: 021600) antes da comparação numérica.
INTERVAL="$(printf '%s' "$INTERVAL" | sed 's/^0*//')"
[ -n "$INTERVAL" ] || INTERVAL=0
if [ "$INTERVAL" -le 0 ]; then
    echo "NGINX_CERT_RELOAD_INTERVAL_SECONDS inválido: '$INTERVAL' (inteiro > 0)" >&2
    exit 1
fi

log_event() {
    printf '{"event":"nginx_cert_reload","action":"%s","detail":"%s"}\n' "$1" "$2" >&2
}

cert_hash() {
    sha256sum "$CERT_DIR/fullchain.pem" "$CERT_DIR/privkey.pem" |
        awk '{print $1}' |
        sha256sum |
        awk '{print $1}'
}

reload_loop() {
    last_hash=""
    if [ -f "$CERT_DIR/fullchain.pem" ] && [ -f "$CERT_DIR/privkey.pem" ]; then
        last_hash="$(cert_hash)"
    fi
    printf '%s\n' "$last_hash" > "$STATE_FILE"
    log_event "loop_started" "interval=${INTERVAL}s hash=${last_hash}"

    while :; do
        sleep "$INTERVAL"
        if [ ! -f "$CERT_DIR/fullchain.pem" ] || [ ! -f "$CERT_DIR/privkey.pem" ]; then
            continue
        fi
        new_hash="$(cert_hash)"
        if [ "$new_hash" = "$last_hash" ]; then
            continue
        fi
        if nginx -t; then
            if nginx -s reload; then
                last_hash="$new_hash"
                printf '%s\n' "$new_hash" > "$STATE_FILE"
                log_event "reload_ok" "hash=${new_hash}"
            else
                log_event "reload_failed" "hash=${new_hash}"
            fi
        else
            log_event "config_test_failed" "hash=${new_hash}"
        fi
    done
}

rm -f /etc/nginx/conf.d/default.conf
if [ -f "$CERT_DIR/fullchain.pem" ] && [ -f "$CERT_DIR/privkey.pem" ]; then
    echo "TLS ativo: usando default.conf (HTTP + HTTPS)" >&2
    cp /etc/nginx/candidates/default.conf /etc/nginx/conf.d/default.conf
    reload_loop &
else
    echo "Sem certificado ainda: usando bootstrap.conf (só porta 80 / ACME)" >&2
    cp /etc/nginx/candidates/bootstrap.conf /etc/nginx/conf.d/default.conf
fi
