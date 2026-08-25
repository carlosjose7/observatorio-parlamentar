# Script de deploy para Windows/PowerShell
# Uso: .\scripts\deploy.ps1 <IP_DA_VPS>

param(
    [Parameter(Mandatory=$true)]
    [string]$VpsIp,

    [Parameter(Mandatory=$false)]
    [string]$SshKey = "$env:USERPROFILE\.ssh\observatorio_parlamentar_oci"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "Deploy Observatório Parlamentar → OCI" -ForegroundColor Yellow
Write-Host "IP: $VpsIp" -ForegroundColor Yellow
Write-Host ""

# 1. Verifica conexão SSH
Write-Host "[1/4] Verificando conexão SSH..." -ForegroundColor Yellow
ssh -i "$SshKey" -o StrictHostKeyChecking=accept-new "ubuntu@${VpsIp}" "echo 'SSH OK'"
Write-Host "✓ Conexão SSH estabelecida" -ForegroundColor Green

# 2. Cria diretório na VPS
Write-Host "[2/4] Preparando diretório na VPS..." -ForegroundColor Yellow
ssh -i "$SshKey" "ubuntu@${VpsIp}" "mkdir -p ~/observatorio-parlamentar"
Write-Host "✓ Diretório criado" -ForegroundColor Green

# 3. Sincroniza arquivos (precisa de rsync ou usa scp)
Write-Host "[3/4] Enviando arquivos do projeto..." -ForegroundColor Yellow

$excludeList = @(
    '.git', '.agents', '__pycache__', '*.pyc', '.venv', 'venv',
    '.env', 'node_modules', 'data', 'logs',
    # artefatos dbt (o tar/rsync NAO le .gitignore — excluir explicitamente)
    'pipeline/gold/target', 'pipeline/gold/logs', 'target'
)

# Cria TAR e envia via SSH (funciona no Windows sem rsync)
$tarFile = "$env:TEMP\observatorio-deploy.tar.gz"
$excludeArgs = $excludeList | ForEach-Object { "--exclude=$_" }
tar -czf $tarFile $excludeArgs -C $ProjectDir .

scp -i "$SshKey" $tarFile "ubuntu@${VpsIp}:~/observatorio-parlamentar.tar.gz"
ssh -i "$SshKey" "ubuntu@${VpsIp}" "tar -xzf ~/observatorio-parlamentar.tar.gz -C ~/observatorio-parlamentar && rm ~/observatorio-parlamentar.tar.gz"
Remove-Item $tarFile -Force

Write-Host "✓ Arquivos enviados" -ForegroundColor Green

# 4. Sobe containers
Write-Host "[4/4] Subindo containers Docker..." -ForegroundColor Yellow
ssh -i "$SshKey" "ubuntu@${VpsIp}" @"
    cd ~/observatorio-parlamentar
    if [ ! -f .env ]; then
        cp .env.example .env
        echo 'Arquivo .env criado. Preencha credenciais reais antes de executar novamente.'
        exit 1
    fi
    docker compose build --parallel 2>&1
    docker compose up -d 2>&1
"@

Write-Host ""
Write-Host "=======================================" -ForegroundColor Green
Write-Host "Deploy concluído!" -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Green
Write-Host "Dashboard: http://${VpsIp}" -ForegroundColor Cyan
Write-Host "API Docs:  http://${VpsIp}/docs (desabilitado se API_DOCS_ENABLED=false)" -ForegroundColor Cyan
Write-Host "MinIO:     console NAO exposta — acesso via SSH tunnel (127.0.0.1:9001)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Airflow:   http://${VpsIp}:8080" -ForegroundColor Cyan
Write-Host "           (AIRFLOW_ADMIN_USER/_PASSWORD do .env)" -ForegroundColor Cyan
Write-Host ""
