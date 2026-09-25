# =============================================================================
# install-all.ps1 — ONE script that sets up EVERYTHING from the repo root
# =============================================================================
# Run from the AOPS- repo root:
#   Right-click → Run with PowerShell
#   OR: powershell -ExecutionPolicy Bypass -File install-all.ps1
#   OR: double-click install-all.bat
# =============================================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerMgr = Join-Path $ProjectRoot "server-manager"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MathVault + Server Manager — Full Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- Step 1: Find Python ---
Write-Host ""
Write-Host "[1/6] Looking for Python 3.11+..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$ver" -match "Python 3\.(\d+)") {
            $minor = [int]$matches[1]
            if ($minor -ge 11) {
                $pythonCmd = $cmd
                Write-Host "  Found: $ver" -ForegroundColor Green
                break
            }
        }
    } catch { }
}
if (-not $pythonCmd) {
    Write-Host "  ERROR: Python 3.11+ not found." -ForegroundColor Red
    Write-Host "  Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

$pythonExe = (Get-Command $pythonCmd -ErrorAction SilentlyContinue).Source

# --- Step 2: Setup server-manager ---
Write-Host ""
Write-Host "[2/6] Setting up Server Manager..." -ForegroundColor Yellow
Push-Location $ServerMgr
try {
    if (-not (Test-Path ".venv")) {
        & $pythonExe -m venv .venv
        Write-Host "  Created .venv" -ForegroundColor Green
    } else {
        Write-Host "  .venv exists" -ForegroundColor Green
    }

    $venvPython = Join-Path $ServerMgr ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "  ERROR: venv python not found at $venvPython" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    & $venvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null

    Write-Host "  Installing Python packages..." -ForegroundColor DarkGray
    & $venvPython -m pip install --quiet `
        "fastapi>=0.110.0" "uvicorn[standard]>=0.27.0" `
        "sqlalchemy>=2.0.25" "paramiko>=3.4.0" `
        "bcrypt>=4.1.2" "pynacl>=1.5.0" `
        "click>=8.1.7" "rich>=13.7.0" `
        "pydantic>=2.6.0" "pydantic-settings>=2.1.0" `
        "python-dotenv>=1.0.1" "python-multipart>=0.0.9" `
        "itsdangerous>=2.1.2" "playwright" 2>&1 | Out-Null
    Write-Host "  Dependencies installed" -ForegroundColor Green

    # Install Chromium for Playwright
    & $venvPython -m playwright install chromium 2>&1 | Out-Null
    Write-Host "  Playwright + Chromium installed" -ForegroundColor Green

    # Copy .env if missing
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "  Created .env" -ForegroundColor Green
    }

    # Init DB
    $env:PYTHONPATH = $ServerMgr
    & $venvPython -c "from database.session import init_db; init_db()"
    Write-Host "  Database initialized" -ForegroundColor Green

    # Check if master password is set
    $envContent = Get-Content ".env" -Raw
    $hasHash = $false
    foreach ($line in ($envContent -split "`n")) {
        if ($line -match "^MASTER_PASSWORD_HASH=(.+)$" -and $matches[1].Trim().Length -gt 0) {
            $hasHash = $true
            break
        }
    }

    if (-not $hasHash) {
        Write-Host ""
        Write-Host "  Master Password Setup" -ForegroundColor Yellow
        Write-Host "  Encrypts ALL SSH credentials. >= 12 chars. NOT recoverable." -ForegroundColor Yellow
        Write-Host ""

        while ($true) {
            $pw1 = Read-Host "  Master password" -AsSecureString
            $pw1Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw1))
            $pw2 = Read-Host "  Confirm" -AsSecureString
            $pw2Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw2))
            if ($pw1Plain -ne $pw2Plain) { Write-Host "  Mismatch." -ForegroundColor Red; continue }
            if ($pw1Plain.Length -lt 12) { Write-Host "  Too short." -ForegroundColor Red; continue }
            break
        }

        $env:PYTHONPATH = $ServerMgr
        $hashOutput = & $venvPython -c "
import sys; sys.path.insert(0, '.')
from crypto import generate_keypair, hash_master_password, save_keypair
sk, pk = generate_keypair('$pw1Plain')
save_keypair(sk, pk, '$pw1Plain')
print(hash_master_password('$pw1Plain'))
" 2>&1

        if ($hashOutput -and "$hashOutput".StartsWith('$2b$')) {
            Add-Content ".env" "`nMASTER_PASSWORD_HASH=$hashOutput"
            Write-Host "  Master password set" -ForegroundColor Green
        } else {
            Write-Host "  WARNING: Could not set hash. Run manually:" -ForegroundColor Yellow
            Write-Host "  cd server-manager; python -m cli.server_manager setup" -ForegroundColor Yellow
        }
        $pw1Plain = $null; $pw2Plain = $null; [GC]::Collect()
    } else {
        Write-Host "  Master password already set" -ForegroundColor Green
    }

    # Seed servers if missing
    $serversJson = "scripts\servers.local.json"
    if (-not (Test-Path $serversJson)) {
        $json = '[{"name":"my-server","host":"192.168.1.150","port":22,"username":"mp","auth_method":"password","password":"Mp13911391!","notes":"Personal Ubuntu server"}]'
        Set-Content -Path $serversJson -Value $json -Encoding UTF8
        Write-Host "  Created servers.local.json" -ForegroundColor Green
    }

} finally {
    Pop-Location
}

# --- Step 3: Setup MathVault root ---
Write-Host ""
Write-Host "[3/6] Setting up MathVault root..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "  Created .env" -ForegroundColor Green
    }

    # Create evidence placeholder
    $evDir = "sources\aops\evidence"
    if (-not (Test-Path $evDir)) { New-Item -ItemType Directory -Path $evDir -Force | Out-Null }
    $evFile = "$evDir\TEST_PLACEHOLDER.txt"
    if (-not (Test-Path $evFile)) {
        Set-Content -Path $evFile -Value "TEST PLACEHOLDER"
        Write-Host "  Created evidence placeholder" -ForegroundColor Green
    }

    # Update SHA-256 in source.yaml
    $hash = (Get-FileHash $evFile -Algorithm SHA256).Hash.ToLower()
    $yamlPath = "sources\aops\source.yaml"
    $yamlContent = Get-Content $yamlPath -Raw
    $yamlContent = $yamlContent -replace "evidence_sha256:\s*\S+", "evidence_sha256: $hash"
    Set-Content -Path $yamlPath -Value $yamlContent -Encoding UTF8
    Write-Host "  Evidence SHA-256: $hash" -ForegroundColor Green

} finally {
    Pop-Location
}

# --- Step 4: Start ---
Write-Host ""
Write-Host "[4/6] Starting the app..." -ForegroundColor Yellow
Write-Host "  API:      http://127.0.0.1:7700" -ForegroundColor Cyan
Write-Host "  Frontend: http://127.0.0.1:3001" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""

Push-Location $ServerMgr
try {
    & $venvPython "scripts\start.py"
} finally {
    Pop-Location
}
