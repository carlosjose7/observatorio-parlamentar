#!/bin/bash
# Script de deploy para o Observatório Parlamentar na OCI
# Uso: bash scripts/deploy.sh <IP_DA_VPS> [caminho_da_chave_ssh]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ $# -lt 1 ]; then
    echo -e "${RED}Uso: $0 <IP_DA_VPS> [caminho_da_chave_ssh]${NC}"
    echo "Exemplo: $0 123.123.123.123 ~/.ssh/observatorio_parlamentar_oci"
    exit 1
fi

VPS_IP="$1"
SSH_KEY="${2:-$HOME/.ssh/observatorio_parlamentar_oci}"
SSH_DEST="ubuntu@${VPS_IP}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo -e "${YELLOW}┌─────────────────────────────────────────────────────────┐${NC}"
echo -e "${YELLOW}│  Deploy Observatório Parlamentar → OCI                 │${NC}"
echo -e "${YELLOW}│  IP: ${VPS_IP}${NC}"
echo -e "${YELLOW}└─────────────────────────────────────────────────────────┘${NC}"

# ── 1. Verifica conexão SSH ──────────────────────────────────────
echo -e "\n${YELLOW}[1/5] Verificando conexão SSH...${NC}"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$SSH_DEST" "echo 'SSH OK'" || {
    echo -e "${RED}Falha na conexão SSH. Verifique IP e chave.${NC}"
    exit 1
}
echo -e "${GREEN}✓ Conexão SSH estabelecida${NC}"

# ── 2. Cria diretório do projeto na VPS ──────────────────────────
echo -e "\n${YELLOW}[2/5] Preparando diretório na VPS...${NC}"
ssh -i "$SSH_KEY" "$SSH_DEST" "mkdir -p ~/observatorio-parlamentar"
echo -e "${GREEN}✓ Diretório criado${NC}"

# ── 3. Sincroniza arquivos (excluindo desnecessários) ────────────
echo -e "\n${YELLOW}[3/5] Sincronizando arquivos do projeto...${NC}"
rsync -avz --delete \
    --exclude='.git/' \
    --exclude='.agents/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='.env' \
    --exclude='node_modules/' \
    --exclude='data/' \
    --exclude='logs/' \
    -e "ssh -i $SSH_KEY" \
    "$PROJECT_DIR/" \
    "$SSH_DEST:~/observatorio-parlamentar/"
echo -e "${GREEN}✓ Arquivos sincronizados${NC}"

# ── 4. Sobe os containers ────────────────────────────────────────
echo -e "\n${YELLOW}[4/5] Subindo containers Docker...${NC}"
ssh -i "$SSH_KEY" "$SSH_DEST" "
    cd ~/observatorio-parlamentar &&
    cp .env.example .env 2>/dev/null || true
    echo 'AVISO: Edite o .env com suas credenciais reais depois.'
    docker compose build --parallel 2>&1
    docker compose up -d 2>&1
"
echo -e "${GREEN}✓ Containers iniciados${NC}"

# ── 5. Verifica status ──────────────────────────────────────────
echo -e "\n${YELLOW}[5/5] Verificando status dos serviços...${NC}"
sleep 5
ssh -i "$SSH_KEY" "$SSH_DEST" "
    cd ~/observatorio-parlamentar
    echo ''
    docker compose ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'
"

echo -e "\n${GREEN}┌─────────────────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}│  Deploy concluído!                                       │${NC}"
echo -e "${GREEN}│                                                         │${NC}"
echo -e "${GREEN}│  Dashboard: http://${VPS_IP}                            │${NC}"
echo -e "${GREEN}│  API Docs:  http://${VPS_IP}/docs                       │${NC}"
echo -e "${GREEN}│  MinIO:     http://${VPS_IP}/minio                      │${NC}"
echo -e "${GREEN}│                                                         │${NC}"
echo -e "${GREEN}│  Airflow:   http://${VPS_IP}:8080 (profile: pipeline)   │${NC}"
echo -e "${GREEN}│  admin/admin                                             │${NC}"
echo -e "${GREEN}│                                                         │${NC}"
echo -e "${GREEN}│  ⚠️  Não esqueça de editar o .env na VPS:               │${NC}"
echo -e "${GREEN}│  ssh -i ${SSH_KEY} ${SSH_DEST}                          │${NC}"
echo -e "${GREEN}│  nano ~/observatorio-parlamentar/.env                   │${NC}"
echo -e "${GREEN}│  docker compose restart                                 │${NC}"
echo -e "${GREEN}└─────────────────────────────────────────────────────────┘${NC}"
