# Testes dos bancos de dados do Codeck no Windows — o mesmo runner do macOS (tests/db/run_tests.py), com os plugins .exe.
#
#   powershell -ExecutionPolicy Bypass -File testar-bancos.ps1              tudo (bancos em Docker, se o Docker Desktop estiver ligado)
#   powershell -ExecutionPolicy Bypass -File testar-bancos.ps1 -SemDocker   só os testes que não precisam de servidor
#
# Roda a partir do pacote gerado no Mac (scripts/windows/preparar-teste-windows.sh → codeck-teste-windows.zip):
# backend\, tests\db\, plugins\ (os codeck-db-*.exe) e este script, na mesma pasta.
#
# Confere: senha no cofre (DPAPI), cada plugin .exe, o fluxo completo pela API (produção travada, Confirmar/Desfazer,
# edições, cancelar), consultas salvas, imagem na área de transferência (troca o que está nela), importar do
# DBeaver/Tabularis/Beekeeper (só lê), instalação de plugin conferida pelo hash, MCP dos agentes com um cliente de
# verdade, banco do app Flutter (formatos), túnel SSH (validação) e se algum processo abre janela de console.
# Usa uma pasta de dados temporária (%APPDATA%\Codeck fica intocada) e apaga as senhas de teste no fim.
# Relatório: codeck-teste-bancos.txt na Área de trabalho — mande para o Claude no Codeck.
param([switch]$SemDocker, [switch]$SemAreaDeTransferencia)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $here 'tests\db\run_tests.py'))) {
  Write-Host "✗ Rode de dentro da pasta do pacote (precisa de backend\, tests\db\ e plugins\ ao lado deste script)." -ForegroundColor Red
  exit 1
}

# Python: o embutido do Codeck instalado; senão o do sistema
$pyArgs = @()
$python = Join-Path $env:LOCALAPPDATA 'Programs\Codeck\python\python.exe'
if (-not (Test-Path $python)) {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { $python = $py.Source; $script:pyLauncher = $true } else {
    $p = Get-Command python -ErrorAction SilentlyContinue
    if (-not $p) { Write-Host "✗ Sem Python: instale o Codeck (ele traz um) ou o Python 3.9+." -ForegroundColor Red; exit 1 }
    $python = $p.Source
  }
}
if ($script:pyLauncher) { $pyArgs = @('-3') }
Write-Host "▸ Python: $python" -ForegroundColor Cyan
& $python @pyArgs -c "import sys, sqlite3; print('  ', sys.version.split()[0], 'sqlite', sqlite3.sqlite_version)"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host "  – sem git: os testes de projeto (consultas salvas, MCP) serão pulados" -ForegroundColor Yellow }

# bancos de verdade no Docker Desktop (opcional)
$targets = @{}
$containers = @()
function Wait-Until([string]$what, [int]$secs, [scriptblock]$probe) {
  for ($i = 0; $i -lt $secs; $i++) { try { if (& $probe) { return $true } } catch {} ; Start-Sleep 1 }
  Write-Host "  – $what não ficou pronto em ${secs}s" -ForegroundColor Yellow; return $false
}
$docker = $null
if (-not $SemDocker) { $docker = Get-Command docker -ErrorAction SilentlyContinue }
if ($docker) { docker info *> $null; if ($LASTEXITCODE -ne 0) { $docker = $null; Write-Host "  – Docker instalado mas desligado: bancos reais pulados" -ForegroundColor Yellow } }
try {
  if ($docker) {
    Write-Host "▸ Bancos de teste no Docker" -ForegroundColor Cyan
    $containers = 'codeck-wtest-pg', 'codeck-wtest-mysql', 'codeck-wtest-mongo', 'codeck-wtest-redis'
    docker rm -f @containers *> $null
    docker run -d --name codeck-wtest-pg -e 'POSTGRES_PASSWORD=Pg!pass1' -p 65432:5432 postgres:17 -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key | Out-Null
    docker run -d --name codeck-wtest-mysql -e 'MYSQL_ROOT_PASSWORD=My!pass1' -e MYSQL_DATABASE=loja -p 63306:3306 mysql:8.4 | Out-Null
    docker run -d --name codeck-wtest-mongo -e MONGO_INITDB_ROOT_USERNAME=root -e 'MONGO_INITDB_ROOT_PASSWORD=Mo!pass1' -p 63017:27017 mongo:7 | Out-Null
    docker run -d --name codeck-wtest-redis -p 63379:6379 redis:7-alpine redis-server --requirepass 'Re!pass1' | Out-Null
    if (Wait-Until 'Postgres' 120 { docker exec codeck-wtest-pg pg_isready -U postgres *> $null; $LASTEXITCODE -eq 0 }) {
      Start-Sleep 2
      $targets.postgres = @{ engine = 'postgres'; env = @{ host = '127.0.0.1'; port = 65432; database = 'postgres'; user = 'postgres'; password = 'Pg!pass1'; tls = @{ mode = 'pin' } } }
    }
    if (Wait-Until 'MySQL' 180 { docker exec codeck-wtest-mysql mysql -uroot '-pMy!pass1' -e 'select 1' *> $null; $LASTEXITCODE -eq 0 }) {
      Start-Sleep 3
      $targets.mysql = @{ engine = 'mysql'; env = @{ host = '127.0.0.1'; port = 63306; database = 'loja'; user = 'root'; password = 'My!pass1'; tls = @{ mode = 'pin' } } }
    }
    if (Wait-Until 'MongoDB' 120 { docker exec codeck-wtest-mongo mongosh --quiet -u root -p 'Mo!pass1' --eval 'db.runCommand({ping:1})' *> $null; $LASTEXITCODE -eq 0 }) {
      $targets.mongodb = @{ engine = 'mongodb'; env = @{ host = '127.0.0.1'; port = 63017; database = 'loja'; user = 'root'; password = 'Mo!pass1'; tls = @{ mode = 'off'; offAck = $true } } }
    }
    if (Wait-Until 'Redis' 60 { docker exec codeck-wtest-redis redis-cli -a 'Re!pass1' ping *> $null; $LASTEXITCODE -eq 0 }) {
      $targets.redis = @{ engine = 'redis'; env = @{ host = '127.0.0.1'; port = 63379; database = '0'; password = 'Re!pass1'; tls = @{ mode = 'off'; offAck = $true } } }
    }
  }

  $work = Join-Path $env:TEMP "codeck-teste-bancos-$([DateTime]::Now.ToString('yyyyMMdd-HHmmss'))"
  New-Item -ItemType Directory -Force $work | Out-Null
  $targetsFile = Join-Path $work 'alvos.json'
  # sem BOM: o Set-Content -Encoding utf8 do PowerShell 5.1 põe BOM no começo do arquivo
  [IO.File]::WriteAllText($targetsFile, ($targets | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
  $report = Join-Path ([Environment]::GetFolderPath('Desktop')) 'codeck-teste-bancos.txt'
  $env:PYTHONIOENCODING = 'utf-8'
  $env:CODECK_ROOT = $here
  $runArgs = @('-I', (Join-Path $here 'tests\db\run_tests.py'), '--plugins', (Join-Path $here 'plugins'), '--targets', $targetsFile, '--report', $report)
  if ($SemAreaDeTransferencia) { $runArgs += '--no-clipboard' }
  Write-Host "▸ Testes" -ForegroundColor Cyan
  & $python @pyArgs @runArgs
  $code = $LASTEXITCODE
} finally {
  if ($containers.Count) { docker rm -f @containers *> $null }
  if ($work) { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue }
}
Write-Host ""
Write-Host "Relatório: $report" -ForegroundColor Cyan
exit $code
