#!/bin/sh
# ADR-066: renderiza o módulo do blackbox_exporter com o domínio vindo
# do `.env` (ADR-008) e inicia o exporter. O arquivo versionado é um
# template; o renderizado fica em /tmp (fora do mount read-only).
set -eu

: "${BLACKBOX_DOMAIN:?BLACKBOX_DOMAIN não definido no .env}"

TEMPLATE=/etc/blackbox_exporter/blackbox.yml.template
RENDERED=/tmp/blackbox.yml

sed "s|\${BLACKBOX_DOMAIN}|${BLACKBOX_DOMAIN}|g" "$TEMPLATE" > "$RENDERED"

exec /bin/blackbox_exporter --config.file="$RENDERED" "$@"
