#!/bin/sh
# Seleciona o config do nginx conforme o estado do TLS (Gate 5).
# - Se o certificado já existe no volume certbot-etc: usa default.conf (HTTP+HTTPS)
# - Caso contrário: usa bootstrap.conf (só porta 80, para o desafio ACME)
# Os configs ficam em /etc/nginx/candidates e SÓ UM é copiado para conf.d —
# evita dois server blocks na mesma porta (erro de servidor duplicado).
CERT_DIR=/etc/letsencrypt/live/observatorio-parlamentar.com.br
rm -f /etc/nginx/conf.d/default.conf
if [ -f "$CERT_DIR/fullchain.pem" ] && [ -f "$CERT_DIR/privkey.pem" ]; then
    echo "TLS ativo: usando default.conf (HTTP + HTTPS)" >&2
    cp /etc/nginx/candidates/default.conf /etc/nginx/conf.d/default.conf
else
    echo "Sem certificado ainda: usando bootstrap.conf (só porta 80 / ACME)" >&2
    cp /etc/nginx/candidates/bootstrap.conf /etc/nginx/conf.d/default.conf
fi