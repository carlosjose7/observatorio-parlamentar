#!/bin/bash
# Emissão inicial do certificado TLS (Gate 5) — rodar UMA VEZ após o DNS
# apontar para o IP da VPS. Uso:
#   bash scripts/issue_certbot.sh <IP_DA_VPS> [caminho_da_chave_ssh]
# Pré-requisitos:
#   - docker-compose.yml com o serviço certbot (deploy já aplicado)
#   - domínio resolvendo para o IP (registro A no Registro.br)
set -euo pipefail

VPS_IP="${1:?Use: $0 <IP_DA_VPS> [chave_ssh]}"
SSH_KEY="${2:-$HOME/.ssh/observatorio_parlamentar_oci}"
SSH_DEST="opc@${VPS_IP}"

echo "Verificando resolução DNS de observatorio-parlamentar.com.br..."
RESOLVED=$(getent hosts observatorio-parlamentar.com.br | awk '{print $1}' | head -1)
if [ -z "$RESOLVED" ]; then
    echo "ERRO: domínio não resolve (getent hosts). Confirme o registro A no Registro.br."
    exit 1
fi
echo "  → observatorio-parlamentar.com.br = $RESOLVED"
if [ "$RESOLVED" != "$VPS_IP" ]; then
    echo "ERRO: domínio aponta para $RESOLVED, mas a VPS é $VPS_IP."
    echo "  Aguarde a propagação (TTL 900) ou corrija o registro A."
    exit 1
fi
echo "  ✓ DNS OK"

echo "Verificando acesso HTTP externo (porta 80) para o desafio ACME..."
if ! timeout 10 bash -c "echo > /dev/tcp/${VPS_IP}/80"; then
    echo "ERRO: porta 80 fechada. Confira Security List (0.0.0.0/0:80) e firewalld."
    exit 1
fi
echo "  ✓ Porta 80 acessível"

echo "Subindo o container certbot para emissão inicial..."
ssh -i "$SSH_KEY" "$SSH_DEST" "
    set -e
    cd ~/observatorio-parlamentar
    docker compose run --rm certbot certonly \\
        --webroot -w /var/www/certbot \\
        -d observatorio-parlamentar.com.br -d www.observatorio-parlamentar.com.br \\
        --email admin@observatorio-parlamentar.com.br \\
        --agree-tos --no-eff-email
"

echo "Recarregando o nginx para ativar HTTPS..."
ssh -i "$SSH_KEY" "$SSH_DEST" "docker compose exec nginx nginx -s reload"

echo ""
echo "Concluído! Valide: https://observatorio-parlamentar.com.br"