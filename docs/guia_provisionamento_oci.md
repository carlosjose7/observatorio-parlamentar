# Guia de Provisionamento de VPS na Oracle Cloud (OCI)
# Observatório Parlamentar — Infraestrutura Always Free

> **Status:** Concluído e validado — Sprint 0B
> **Objetivo:** documentar o passo a passo real de provisionamento da infraestrutura
> Always Free na OCI, incluindo os problemas encontrados e suas soluções, para que
> um terceiro consiga replicar o ambiente do zero.
> **Resultado final:** instância `VM.Standard.A1.Flex` (2 OCPU / 12GB RAM), Ubuntu
> 24.04, Docker instalado, hardening de SSH aplicado, firewall em duas camadas
> (Security List OCI + UFW local), custo R$ 0/mês.

---

## 1. Pré-requisitos

- Conta OCI ativa (cartão de crédito exigido no cadastro; o Always Free Tier não
  cobra se os limites forem respeitados)
- Cliente SSH disponível (nativo no Windows 10/11 via PowerShell)
- Acesso de administrador na máquina local (necessário para alguns passos no Windows)

### Nota sobre o Always Free Tier (mudança relevante em 2026)

A Oracle reduziu a alocação Always Free do shape Ampere `A1.Flex` de
**4 OCPUs / 24GB RAM** para **2 OCPUs / 12GB RAM** em meados de 2026, sem
anúncio formal. Este guia já reflete o novo limite vigente. Se você encontrar
documentação antiga (inclusive interna do seu próprio projeto) citando 4/24,
está desatualizada — o limite gratuito real hoje é 2 OCPUs / 12GB.

⚠️ **Não confundir com `VM.Standard.A2.Flex`** — esse é um shape mais novo,
**não incluso no Always Free**. É cobrado por hora, exceto se você tiver
crédito de Free Trial (US$300/30 dias) ativo. Ver seção 9 para o caso de uso
legítimo (workaround de capacidade) e seus riscos.

---

## 2. Criar o Compartment dedicado

Isolar o projeto em um compartment próprio facilita governança de custo e IAM.

1. Console OCI → ☰ → **Identity & Security → Compartments**
2. **Create Compartment**

| Campo | Valor |
|---|---|
| Name | `observatorio-parlamentar` |
| Description | Compartment dedicado ao projeto Observatório Parlamentar |
| Parent Compartment | root (tenancy) |

3. Na mesma tela, seção **Tags** → **+ Add Tag** → para cada linha abaixo,
   selecione **Tag Namespace: "None (add a free-form tag)"**:

| Key | Value |
|---|---|
| `project` | `observatorio-parlamentar` |
| `environment` | `production` |
| `owner` | `<seu-nome>` |
| `cost-tier` | `always-free` |
| `managed-by` | `manual` |

4. **Create Compartment**

> Aplique o mesmo conjunto de tags em todos os recursos criados nas próximas
> seções (VCN, subnet, instância) para rastreabilidade completa.

---

## 3. Gerar o par de chaves SSH (máquina local, Windows)

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh"
ssh-keygen -t ed25519 -C "observatorio-parlamentar-oci" -f "$env:USERPROFILE\.ssh\observatorio_parlamentar_oci"
```

- Use o **caminho completo** (`$env:USERPROFILE\...`), não `~` — o `ssh-keygen`
  no Windows pode falhar ao expandir `~` (erro `Saving key ... failed: No such
  file or directory`)
- Passphrase: pode deixar em branco (Enter/Enter) para simplicidade, ou definir
  uma senha para camada extra de segurança

Copiar a chave pública para a área de transferência (útil no próximo passo):

```powershell
Get-Content "$env:USERPROFILE\.ssh\observatorio_parlamentar_oci.pub" | Set-Clipboard
```

---


## 4. Criar VCN + Subnet + Instância de Computação

### 4.1 Shape e imagem

Console OCI → **Compute → Instances → Create Instance**

| Campo | Valor |
|---|---|
| Name | `instance-<gerado-automaticamente>` (ou nome customizado) |
| Compartment | `observatorio-parlamentar` |
| Image | Canonical Ubuntu 24.04 (Minimal, aarch64) |
| Shape | `VM.Standard.A1.Flex` |
| OCPUs | 2 |
| Memória | 12 GB |

### 4.2 Rede (VNIC)

| Campo | Valor |
|---|---|
| Nome da VNIC | `observatorio-parlamentar-vnic-01` |
| Rede principal | "Criar uma nova rede virtual na nuvem" (se ainda não existir) |
| Subnet | "Criar uma nova sub-rede pública" |

⚠️ **Passo crítico — não pule este:**
Na seção **"Designação de endereço IPv4"**, marque:
```
☑ Designar endereço IPv4 público automaticamente
```
Sem isso, a instância sobe **sem IP público** (`public-ip: null`) e fica
inacessível pela internet — inclusive para o primeiro SSH. É o erro mais comum
desse fluxo. Se você já criou a instância sem marcar essa opção, veja a
seção 8 (como corrigir depois, sem recriar a instância).

Nesta mesma tela, adicione as tags (VCN e Subnet) — mesmo conjunto da seção 2.

### 4.3 Script de inicialização (cloud-init)

Cole no campo **"Script de inicialização da nuvem"**:

```yaml
#cloud-config
package_update: true
package_upgrade: true
runcmd:
  - curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  - sh /tmp/get-docker.sh
  - usermod -aG docker ubuntu
  - apt install -y ufw
  - ufw allow 22/tcp
  - ufw allow 80/tcp
  - ufw allow 443/tcp
  - ufw --force enable
  - sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
  - sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
  - systemctl restart ssh
```

> ⚠️ **Nota importante (lição aprendida):** este script pode falhar
> silenciosamente na prática (ver seção 7 — Troubleshooting). Os motivos mais
> comuns: (1) a rede da instância ainda não está 100% estável no momento exato
> em que o `runcmd` roda, fazendo o `curl` do Docker dar timeout; (2) a imagem
> Ubuntu **Minimal** não vem com `ufw` pré-instalado — por isso a linha
> `apt install -y ufw` foi adicionada aqui (no processo original ela estava
> ausente e causou falha); (3) o nome correto do serviço SSH no Ubuntu é `ssh`,
> não `sshd` (erro comum vindo de experiência prévia com Red Hat/CentOS).
> **Sempre valide manualmente após o primeiro boot** (seção 7).

### 4.4 Autenticação, Disponibilidade e Agentes

| Seção | Configuração |
|---|---|
| Adicionar chaves SSH | "Colar chave pública" → colar conteúdo do `.pub` gerado na seção 3 |
| Preemptible instance | **NÃO marcar** (não é Always Free e pode ser encerrada a qualquer momento) |
| Recovery action | `Restore instance` (padrão) |
| Oracle Cloud Agent — Monitoring | Ativado |
| Oracle Cloud Agent — Run Command | Ativado |
| Oracle Cloud Agent — Bastion | Recomendado ativar (SSH sem expor porta 22 publicamente) |
| Atributos de segurança (ZPR) | Deixar em branco — desnecessário para instância única |

### 4.5 Revisão antes de criar

Checklist final antes de clicar em **Create**:

- [ ] Compartment correto (`observatorio-parlamentar`)
- [ ] Shape `VM.Standard.A1.Flex`, 2 OCPU / 12GB
- [ ] **Endereço IPv4 público: marcado** (não deixe como "Não")
- [ ] Bloco CIDR da subnet válido (ex: `10.0.0.0/24` — nunca `/00`, que é
      inválido e às vezes aparece como bug de exibição na tela de revisão)
- [ ] Chave SSH colada corretamente
- [ ] Tags aplicadas
- [ ] Cloud-init colado

---

## 5. Erro comum: "Capacidade insuficiente" (Out of host capacity)

```
Erro de API
Capacidade insuficiente para a forma VM.Standard.A1.Flex no domínio de
disponibilidade AD-1.
```

Isso **não é erro de configuração** — é limitação real de capacidade
Always Free na região, especialmente comum em `sa-saopaulo-1` (que tem apenas
1 AD, portanto não há domínio alternativo para tentar).

### Opções, da mais simples à mais trabalhosa

1. **Tentar novamente em horários diferentes** (madrugada/fim de semana costuma
   ter mais sucesso, sem garantia)
2. **Reduzir a alocação** (ex: 1 OCPU/6GB) e fazer resize depois quando a
   capacidade normalizar
3. **Workaround não oficial:** criar a instância como `VM.Standard.A2.Flex`
   (shape mais novo, geralmente com mais capacidade disponível) e depois
   redimensionar (resize) para `A1.Flex` — ver seção 9

---

## 6. Instalar e configurar o OCI CLI (Windows)

Necessário para operações que a interface web não cobre bem, como resize de
shape.

### 6.1 Instalação

```powershell
cd $env:USERPROFILE
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
Invoke-WebRequest https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.ps1 -OutFile install.ps1
.\install.ps1
```

⚠️ **Armadilhas comuns:**
- Rode `cd $env:USERPROFILE` **antes** de baixar o instalador — se você
  estiver em `C:\WINDOWS\System32` (comum ao abrir PowerShell como
  Administrador), o download falha por falta de permissão de escrita
- Cole os comandos **um de cada vez**, nunca colados/grudados na mesma linha
- Se aparecer erro de `execution of scripts is disabled`, rode o
  `Set-ExecutionPolicy` acima primeiro

### 6.2 Erro: "No such file or directory" durante instalação de pacotes (Long Path)

```
ERROR: Could not install packages due to an OSError: [Errno 2] No such file
or directory: '...\text\cmdref\database-management\...'
HINT: enable Windows Long Path support
```

O pacote `oci_cli` contém arquivos com caminhos que excedem o limite padrão de
260 caracteres do Windows. Solução:

```powershell
# Em PowerShell como Administrador:
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

**Reinicie o computador** (obrigatório — reabrir o terminal não é suficiente).
Depois:

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\lib\oracle-cli" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:USERPROFILE\bin" -ErrorAction SilentlyContinue
cd $env:USERPROFILE
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

### 6.3 Configurar autenticação

```powershell
oci setup config
```

| Prompt | Resposta |
|---|---|
| Local do config | Enter (padrão) |
| User OCID | Console → ícone de perfil → **My Profile** → campo OCID |
| Tenancy OCID | Console → perfil → **Tenancy: `<nome>`** → campo OCID |
| Região | `sa-saopaulo-1` (buscar o número correspondente na lista exibida) |
| Gerar novo par de chaves? | `Y` |
| Diretório / nome da chave | Enter (padrão) |
| Passphrase | Ver observação abaixo |

⚠️ **Se o prompt de passphrase entrar em loop** (`Repeat for confirmation:`
repetindo indefinidamente, ou não aceitando input), cancele com `Ctrl+C` e
gere a chave manualmente:

```powershell
mkdir "$env:USERPROFILE\.oci" -Force

& "$env:USERPROFILE\lib\oracle-cli\Scripts\python.exe" -c "
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption()
)
public_pem = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)
with open(r'$env:USERPROFILE\.oci\oci_api_key.pem', 'wb') as f:
    f.write(private_pem)
with open(r'$env:USERPROFILE\.oci\oci_api_key_public.pem', 'wb') as f:
    f.write(public_pem)
print('Chaves geradas com sucesso.')
"
```

Depois, rode `oci setup config` de novo e, na pergunta sobre gerar novo par de
chaves, responda **`n`** e informe o caminho da chave já gerada:
`C:\Users\<usuario>\.oci\oci_api_key.pem`.

### 6.4 Cadastrar a chave pública no console

```powershell
Get-Content "$env:USERPROFILE\.oci\oci_api_key_public.pem" | Set-Clipboard
```

Console OCI → perfil → **My Profile** → **API Keys** → **Add API Key** →
**Paste Public Key** → colar → **Add**.

Confirme que o fingerprint exibido no console bate com o impresso no terminal
durante o `oci setup config`.

### 6.5 Corrigir permissões de arquivo (aviso de segurança)

```powershell
oci setup repair-file-permissions --file "$env:USERPROFILE\.oci\config"
oci setup repair-file-permissions --file "$env:USERPROFILE\.oci\oci_api_key.pem"
```

### 6.6 Testar

```powershell
oci iam region list
```

Deve retornar uma lista JSON de regiões.

### 6.7 Erro: "NotAuthenticated" (401) mesmo com config correto

Se `oci iam region list` funcionar mas operações de escrita (`update`, `create`)
falharem com `401 NotAuthenticated`, verifique o **relógio do sistema** — a
OCI rejeita requisições assinadas com timestamp fora de janela de tolerância:

```powershell
w32tm /query /status
```

Se mostrar `Indicador de Salto: 3 (não sincronizado)` ou fonte
`Local CMOS Clock`:

```powershell
# Em PowerShell como Administrador:
w32tm /resync /force
```

---

## 7. Validar o primeiro acesso e o cloud-init

```powershell
ssh -i "$env:USERPROFILE\.ssh\observatorio_parlamentar_oci" ubuntu@<IP_PUBLICO>
```

Na primeira conexão, confirme o fingerprint com `yes`.

### Checklist de validação pós-boot

```bash
# Status geral do cloud-init
cloud-init status --long

# Log completo (identifica exatamente o que falhou, se algo falhou)
sudo cat /var/log/cloud-init-output.log

# Docker
docker --version
sudo systemctl status docker --no-pager

# Hardening SSH
sudo grep -E "^PermitRootLogin|^PasswordAuthentication" /etc/ssh/sshd_config
```

### Se o Docker não foi instalado (cloud-init falhou)

Sintoma comum: `docker: command not found`, log mostrando
`curl: (28) Failed to connect ... Timeout`. Instale manualmente:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu
exit
# reconecte via SSH para o grupo docker ser aplicado à sessão
```

### Se o UFW não foi instalado

Sintoma: `ufw: not found` no log. A imagem Ubuntu Minimal não traz `ufw` por
padrão:

```bash
sudo apt update
sudo apt install -y ufw
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

### Se o restart do SSH falhou

Sintoma: `Failed to restart sshd.service: Unit sshd.service not found`. No
Ubuntu/Debian o serviço se chama **`ssh`**, não `sshd`:

```bash
sudo systemctl restart ssh
```

### Validar tudo de uma vez

```bash
docker run hello-world
sudo ufw status
```

---

## 8. Corrigir instância sem IP público (se necessário)

Se você criou a instância sem marcar "Designar endereço IPv4 público
automaticamente" (ver alerta na seção 4.2), não é necessário recriar:

**Via Console (mais simples):**
1. **Compute → Instances** → clique na instância
2. Aba **"Attached VNICs"** → clique na VNIC
3. Seção **"IPv4 Addresses"** → "..." ao lado do IP privado → **Edit** /
   **Assign Public IP Address**
4. Escolha **"Ephemeral Public IP"** → **Update**

**Via CLI:**
```powershell
oci network private-ip list --vnic-id <OCID_DA_VNIC>
# copie o "id" do private IP retornado

oci network public-ip create --compartment-id <OCID_DO_COMPARTMENT> --lifetime EPHEMERAL --private-ip-id <OCID_DO_PRIVATE_IP>
```

Confirme com:
```powershell
oci compute instance list-vnics --instance-id <OCID_DA_INSTANCIA>
```
O campo `"public-ip"` deve deixar de ser `null`.

---

## 9. Redimensionar de A2.Flex para A1.Flex (se usou o workaround da seção 5)

⚠️ **Só use `VM.Standard.A2.Flex` se tiver crédito de Free Trial ativo** —
esse shape não é Always Free e gera cobrança direta fora do trial. Ao usá-lo
como workaround de capacidade, redimensione para A1.Flex assim que possível:

```powershell
'{"ocpus": 2, "memory-in-gbs": 12}' | Out-File -FilePath "$env:USERPROFILE\shape-config.json" -Encoding ascii -NoNewline

oci compute instance update --instance-id <OCID_DA_INSTANCIA> --shape "VM.Standard.A1.Flex" --shape-config file://$env:USERPROFILE/shape-config.json
```

> **Nota de sintaxe PowerShell:** nunca use `\"` para escapar aspas dentro de
> JSON inline no PowerShell — o parser interpreta literalmente e quebra o
> comando. Prefira sempre um arquivo `.json` com `file://` (mais confiável)
> ou aspas simples por fora (`'{"chave": "valor"}'`).

⚠️ **Este update substitui tags existentes por vazio** se `--freeform-tags`
não for informado explicitamente (a CLI avisa isso antes de confirmar).
Reaplique as tags depois do resize:

```powershell
'{"project": "observatorio-parlamentar", "environment": "production", "owner": "<seu-nome>", "cost-tier": "always-free", "managed-by": "manual"}' | Out-File -FilePath "$env:USERPROFILE\freeform-tags.json" -Encoding ascii -NoNewline

oci compute instance update --instance-id <OCID_DA_INSTANCIA> --freeform-tags file://$env:USERPROFILE/freeform-tags.json
```

Acompanhe o resultado (o resize é assíncrono — a instância passa por
`STOPPING` → `STARTING` → `RUNNING`):

```powershell
oci compute instance get --instance-id <OCID_DA_INSTANCIA>
```

Verifique `"shape": "VM.Standard.A1.Flex"` e `"lifecycle-state": "RUNNING"`.

---

## 10. Restringir acesso SSH ao seu IP (defesa em profundidade)

Por padrão, tanto a Security List quanto o `ufw` liberam a porta 22 para
`0.0.0.0/0` (qualquer origem). Restrinja em duas camadas.

### 10.1 Descobrir seu IP público atual

```powershell
(Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content
```

> Nota: se sua conexão usa IP dinâmico (comum em provedores residenciais no
> Brasil), essa regra pode precisar ser atualizada no futuro caso o IP mude.

### 10.2 Camada 1 — Security List (OCI)

1. **Networking → Virtual Cloud Networks** → sua VCN → **Security Lists** →
   Default Security List
2. Aba **Ingress Rules** → editar a regra da porta 22
3. Trocar **Source CIDR** de `0.0.0.0/0` para `<SEU_IP>/32`
4. **Save Changes**

### 10.3 Camada 2 — UFW (dentro da instância)

```bash
sudo ufw delete allow 22/tcp
sudo ufw allow from <SEU_IP> to any port 22 proto tcp
sudo ufw status numbered
```

⚠️ **Não feche a sessão SSH atual antes de testar.** Abra um segundo terminal
e valide a nova conexão antes de encerrar a primeira — isso evita ficar
trancado para fora caso a regra tenha sido configurada incorretamente:

```powershell
ssh -i "$env:USERPROFILE\.ssh\observatorio_parlamentar_oci" ubuntu@<IP_PUBLICO>
```

Se a segunda sessão conectar normalmente, a configuração está validada.

---

## 11. Checklist final de infraestrutura

| Item | Validação |
|---|---|
| Compartment dedicado | `observatorio-parlamentar`, tagueado |
| VCN + Subnet | criadas, CIDR válido (ex: `/24`) |
| Instância `VM.Standard.A1.Flex` | 2 OCPU / 12GB, `RUNNING`, Always Free |
| IP público | atribuído e acessível |
| Security List | porta 22 restrita ao IP de administração |
| UFW | ativo, porta 22 restrita, 80/443 liberadas |
| SSH hardening | `PermitRootLogin no`, `PasswordAuthentication no` |
| Docker | instalado, testado com `docker run hello-world` |
| Tags | aplicadas em compartment, VCN, subnet e instância |
| Chave SSH | funcional, sem depender de senha |

---

## 12. Referências

- [OCI Always Free FAQ](https://www.oracle.com/cloud/free/faq.html)
- [Gerenciamento de chaves SSH na OCI](https://docs.cloud.oracle.com/iaas/Content/Compute/Tasks/managingkeypairs.htm)
- [Gerenciamento de VNICs](https://docs.cloud.oracle.com/iaas/Content/Network/Tasks/managingVNICs.htm)
- [Gerenciamento de endereços IPv4 públicos](https://docs.cloud.oracle.com/iaas/Content/Network/Tasks/managingpublicIPs.htm)
- [OCI CLI — instalação e configuração](https://github.com/oracle/oci-cli/blob/master/scripts/install/README.rst)
- [Windows Long Path support (pip)](https://pip.pypa.io/warnings/enable-long-paths)

---

*Documento gerado a partir do processo real de provisionamento executado na
Sprint 0B do Observatório Parlamentar. Mantido como artefato de apoio técnico
— não substitui `PROJECT_CONTEXT.md §4`, que é a fonte da verdade sobre a
decisão arquitetural de infraestrutura.*
