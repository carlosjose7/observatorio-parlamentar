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
SSH_DEST="opc@${VPS_IP}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo -e "${YELLOW}┌─────────────────────────────────────────────────────────┐${NC}"
echo -e "${YELLOW}│  Deploy Observatório Parlamentar → OCI                 │${NC}"
echo -e "${YELLOW}│  IP: ${VPS_IP}${NC}"
echo -e "${YELLOW}└─────────────────────────────────────────────────────────┘${NC}"

# ── 1. Verifica conexão SSH ──────────────────────────────────────
echo -e "\n${YELLOW}[1/6] Verificando conexão SSH...${NC}"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$SSH_DEST" "echo 'SSH OK'" || {
    echo -e "${RED}Falha na conexão SSH. Verifique IP e chave.${NC}"
    exit 1
}
echo -e "${GREEN}✓ Conexão SSH estabelecida${NC}"

# ── 2. Cria diretório do projeto na VPS ──────────────────────────
echo -e "\n${YELLOW}[2/6] Preparando diretório na VPS...${NC}"
ssh -i "$SSH_KEY" "$SSH_DEST" "mkdir -p ~/observatorio-parlamentar"
echo -e "${GREEN}✓ Diretório criado${NC}"

# ── 3. Sincroniza arquivos (excluindo desnecessários) ────────────
echo -e "\n${YELLOW}[3/6] Sincronizando arquivos do projeto...${NC}"
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

# ── 4. Instala/atualiza as units systemd do pipeline (ADR-034) ───
echo -e "\n${YELLOW}[4/6] Instalando units systemd do pipeline...${NC}"
ssh -i "$SSH_KEY" "$SSH_DEST" "
    set -e
    sudo cp ~/observatorio-parlamentar/infra/observatorio-pipeline.service /etc/systemd/system/
    sudo cp ~/observatorio-parlamentar/infra/observatorio-pipeline.timer /etc/systemd/system/
    # Garante o bit de execução do script (o systemd invoca o ExecStart sem
    # prefixo `bash`; sem +x o start falha com status=203/EXEC Permission denied).
    chmod +x ~/observatorio-parlamentar/scripts/run_pipeline_daily.sh
    sudo systemctl daemon-reload
    sudo systemctl enable observatorio-pipeline.timer
    sudo systemctl start observatorio-pipeline.timer
    systemctl list-timers observatorio-pipeline.timer --no-pager
"
echo -e "${GREEN}✓ Units systemd instaladas${NC}"

# ── 5. Sobe os containers ────────────────────────────────────────
echo -e "\n${YELLOW}[5/6] Subindo containers Docker...${NC}"
ssh -i "$SSH_KEY" "$SSH_DEST" "
    cd ~/observatorio-parlamentar &&
    if [ ! -f .env ]; then
        cp .env.example .env
        echo 'Arquivo .env criado. Preencha credenciais reais antes de executar novamente.'
        exit 1
    fi
    docker compose build --parallel 2>&1
    docker compose up -d 2>&1
"
echo -e "${GREEN}✓ Containers iniciados${NC}"

# ── 6. Verifica status ──────────────────────────────────────────
echo -e "\n${YELLOW}[6/6] Verificando status dos serviços...${NC}"
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
echo -e "${GREEN}│  credenciais: AIRFLOW_ADMIN_USER/_PASSWORD do .env       │${NC}"
echo -e "${GREEN}│                                                         │${NC}"
echo -e "${GREEN}└─────────────────────────────────────────────────────────┘${NC}"
