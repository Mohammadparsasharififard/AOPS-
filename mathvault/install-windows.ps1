# ============================================================================
# install-windows.ps1 — Single-file installer for MathVault + Server Manager
# ============================================================================
# Usage (3 ways — pick one):
#
#   1. Right-click this file in Explorer → "Run with PowerShell"
#
#   2. From a PowerShell window:
#        powershell -ExecutionPolicy Bypass -File install-windows.ps1
#
#   3. From CMD:
#        powershell -ExecutionPolicy Bypass -File install-windows.ps1
#
# What it does:
#   1. Checks Python 3.11+ is installed
#   2. Moves into server-manager/
#   3. Creates virtualenv + installs all Python deps
#   4. Copies .env.example → .env
#   5. Initializes the SQLite database
#   6. Prompts for a master password (used to encrypt SSH credentials)
#   7. Prompts for your server's SSH details (host/user/password)
#   8. Encrypts the SSH password with the master password
#   9. Starts the API + Frontend
#
# At the end, open:  http://127.0.0.1:3001
# ============================================================================

$ErrorActionPreference = "Stop"

# ---- Defaults (press Enter in the prompts to accept) ----
$DefaultName     = "my-server"
$DefaultHost     = "192.168.1.150"
$DefaultPort     = 22
$DefaultUser     = "mp"
$DefaultNotes    = "Personal server on local network"


function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}

function Write-Err($msg) {
    Write-Host "    ERROR: $msg" -ForegroundColor Red
}

function Pause-Exit($code = 1) {
    Write-Host ""
    Write-Host "Press Enter to close..." -ForegroundColor Yellow
    Read-Host | Out-Null
    exit $code
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MathVault + Server Manager — Windows Installer" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan


# ============================================================================
# Step 1: Find Python
# ============================================================================
Write-Step "Step 1/8 — Looking for Python 3.11+"
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py -3")) {
    try {
        $ver = & Invoke-Expression "$cmd --version" 2>&1
        if ($LASTEXITCODE -eq 0 -and "$ver" -match "Python 3\.(\d+)") {
            $minor = [int]$matches[1]
            if ($minor -ge 11) {
                $pythonCmd = $cmd
                Write-OK "Found: $ver"
                break
            }
        }
    } catch { }
}
if (-not $pythonCmd) {
    Write-Err "Python 3.11+ not found."
    Write-Host "    Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "    During install, CHECK the box 'Add python.exe to PATH'." -ForegroundColor Yellow
    Pause-Exit
}

# Get the absolute python path (so we can find venv later)
$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}
if (-not $pythonExe) {
    Write-Err "Could not find python executable path"
    Pause-Exit
}


# ============================================================================
# Step 2: Locate the project directory
# ============================================================================
Write-Step "Step 2/8 — Locating project"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = $PWD.Path }

# If running from server-manager/, the parent has the rest of the repo.
# If running from repo root, server-manager/ is a subdirectory.
if (Test-Path (Join-Path $scriptDir "server-manager")) {
    $projectRoot = $scriptDir
    $smDir = Join-Path $scriptDir "server-manager"
} elseif (Test-Path (Join-Path $scriptDir "scripts\setup.py")) {
    # We're inside server-manager/
    $smDir = $scriptDir
    $projectRoot = Split-Path -Parent $scriptDir
} else {
    Write-Err "Cannot find project. Run this script from the AOPS- repo root."
    Pause-Exit
}
Write-OK "Project root: $projectRoot"
Write-OK "Server Manager dir: $smDir"


# ============================================================================
# Step 3: Git pull (in case there are updates)
# ============================================================================
Write-Step "Step 3/8 — Updating from git"
try {
    Push-Location $projectRoot
    & git pull --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Pulled latest"
    } else {
        Write-Host "    (git pull failed or no remote — continuing)" -ForegroundColor Yellow
    }
    Pop-Location
} catch {
    Write-Host "    (git not available — continuing)" -ForegroundColor Yellow
}


# ============================================================================
# Step 4: Set up venv + deps
# ============================================================================
Write-Step "Step 4/8 — Setting up Python virtualenv + dependencies"
Push-Location $smDir
try {
    if (-not (Test-Path ".venv")) {
        & $pythonExe -m venv .venv
        if ($LASTEXITCODE -ne 0) { Write-Err "venv creation failed"; Pause-Exit }
        Write-OK "Created .venv"
    } else {
        Write-OK ".venv exists"
    }

    $venvPython = Join-Path $smDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Err "venv python not found at $venvPython"
        Pause-Exit
    }

    # Upgrade pip
    & $venvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null

    # Install deps
    $deps = @(
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.27.0",
        "sqlalchemy>=2.0.25",
        "paramiko>=3.4.0",
        "bcrypt>=4.1.2",
        "pynacl>=1.5.0",
        "click>=8.1.7",
        "rich>=13.7.0",
        "pydantic>=2.6.0",
        "pydantic-settings>=2.1.0",
        "python-dotenv>=1.0.1",
        "python-multipart>=0.0.9",
        "itsdangerous>=2.1.2"
    )
    Write-Host "    Installing Python packages (this takes ~30 seconds)..." -ForegroundColor DarkGray
    & $venvPython -m pip install --quiet $deps 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Dependency installation failed"
        & $venvPython -m pip install $deps
        Pause-Exit
    }
    Write-OK "Dependencies installed"
} finally {
    Pop-Location
}


# ============================================================================
# Step 5: Copy .env.example → .env (if missing)
# ============================================================================
Write-Step "Step 5/8 — Configuring .env"
$envFile = Join-Path $smDir ".env"
$envExample = Join-Path $smDir ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-OK "Created .env from .env.example"
    } else {
        Write-Err ".env.example not found — repo may be incomplete"
        Pause-Exit
    }
} else {
    Write-OK ".env already exists"
}


# ============================================================================
# Step 6: Initialize DB + set master password
# ============================================================================
$env:PYTHONPATH = $smDir

# Initialize DB
Write-Step "Step 6/8 — Initializing database"
& $venvPython -c "from database.session import init_db; init_db()"
if ($LASTEXITCODE -ne 0) {
    Write-Err "DB init failed"
    Pause-Exit
}
Write-OK "Database ready"

# Check if master password is already set
$envContent = Get-Content $envFile -Raw
$hasHash = $false
foreach ($line in ($envContent -split "`n")) {
    if ($line -match "^MASTER_PASSWORD_HASH=(.+)$") {
        if ($matches[1].Trim().Length -gt 0) {
            $hasHash = $true
            break
        }
    }
}

if (-not $hasHash) {
    Write-Step "Step 6b/8 — Set master password"
    Write-Host "    The master password encrypts ALL SSH credentials stored by this app." -ForegroundColor Yellow
    Write-Host "    It must be at least 12 characters and is NOT recoverable if lost." -ForegroundColor Yellow
    Write-Host "    (This is NOT your SSH password — pick something different.)" -ForegroundColor Yellow
    Write-Host ""

    while ($true) {
        $mp1 = Read-Host "    Master password" -AsSecureString
        $mp1Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($mp1)
        )
        $mp2 = Read-Host "    Confirm master password" -AsSecureString
        $mp2Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($mp2)
        )
        if ($mp1Plain -ne $mp2Plain) {
            Write-Host "    Passwords don't match. Try again." -ForegroundColor Red
            continue
        }
        if ($mp1Plain.Length -lt 12) {
            Write-Host "    Must be at least 12 characters." -ForegroundColor Red
            continue
        }
        break
    }

    # Use the CLI's setup command to generate keypair + write hash
    # We pass the master password via stdin to the CLI's interactive prompt
    $mpInput = "$mp1Plain`n$mp2Plain`n"
    $env:PYTHONPATH = $smDir
    Push-Location $smDir
    try {
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo.FileName = $venvPython
        $proc.StartInfo.Arguments = "-c `"from cli.server_manager import cli; cli(['setup'])`""
        $proc.StartInfo.UseShellExecute = $false
        $proc.StartInfo.RedirectStandardInput = $true
        $proc.StartInfo.RedirectStandardOutput = $true
        $proc.StartInfo.RedirectStandardError = $true
        $proc.StartInfo.EnvironmentVariables["PYTHONPATH"] = $smDir
        $proc.Start() | Out-Null
        $proc.StandardInput.Write($mpInput)
        $proc.StandardInput.Close()
        $proc.WaitForExit()
        if ($proc.ExitCode -ne 0) {
            Write-Err "Master password setup failed"
            Write-Host $proc.StandardError.ReadToEnd()
            Pause-Exit
        }
    } finally {
        Pop-Location
    }
    Write-OK "Master password set"

    # Clear plaintext from memory
    $mp1Plain = $null
    $mp2Plain = $null
    [GC]::Collect()
} else {
    Write-OK "Master password already set"
}


# ============================================================================
# Step 7: Ask for SSH details + create servers.local.json + seed
# ============================================================================
Write-Step "Step 7/8 — Configure your server"

# Check if servers.local.json already exists
$serversJsonPath = Join-Path $smDir "scripts\servers.local.json"
$existingServer = $null
if (Test-Path $serversJsonPath) {
    try {
        $existingData = Get-Content $serversJsonPath -Raw | ConvertFrom-Json
        if ($existingData -is [array] -and $existingData.Count -gt 0) {
            $existingServer = $existingData[0]
        }
    } catch { }
}

# Use existing values as defaults, otherwise use the static defaults
if ($existingServer) {
    $DefaultName = $existingServer.name
    $DefaultHost = $existingServer.host
    $DefaultPort = $existingServer.port
    $DefaultUser = $existingServer.username
    if ($existingServer.notes) { $DefaultNotes = $existingServer.notes }
}

Write-Host "    Press Enter to accept defaults shown in [brackets]." -ForegroundColor DarkGray
$name = Read-Host "    Server name [$DefaultName]"
if (-not $name) { $name = $DefaultName }

$host = Read-Host "    Host (IP or domain) [$DefaultHost]"
if (-not $host) { $host = $DefaultHost }

$portStr = Read-Host "    Port [$DefaultPort]"
if (-not $portStr) { $portStr = $DefaultPort }
$port = [int]$portStr

$user = Read-Host "    Username [$DefaultUser]"
if (-not $user) { $user = $DefaultUser }

$pwSecure = Read-Host "    SSH password" -AsSecureString
$pwPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwSecure)
)

# Write servers.local.json
$json = @"
[
  {
    "name": "$name",
    "host": "$host",
    "port": $port,
    "username": "$user",
    "auth_method": "password",
    "password": "$pwPlain",
    "notes": "$DefaultNotes"
  }
]
"@
Set-Content -Path $serversJsonPath -Value $json -Encoding UTF8
Write-OK "Wrote scripts/servers.local.json (gitignored — never committed)"

# Clear plaintext password from memory
$pwPlain = $null
[GC]::Collect()


# ============================================================================
# Step 8: Seed + Start
# ============================================================================
Write-Step "Step 8/8 — Seeding server (will ask for master password)"
$env:PYTHONPATH = $smDir
Push-Location $smDir
try {
    # Pass master password via stdin
    $mpForSeed = Read-Host "    Enter your master password (for seed)" -AsSecureString
    $mpForSeedPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($mpForSeed)
    )

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo.FileName = $venvPython
    $proc.StartInfo.Arguments = "scripts\seed-servers.py"
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.RedirectStandardInput = $true
    $proc.StartInfo.RedirectStandardOutput = $true
    $proc.StartInfo.RedirectStandardError = $true
    $proc.StartInfo.WorkingDirectory = $smDir
    $proc.StartInfo.EnvironmentVariables["PYTHONPATH"] = $smDir
    $proc.Start() | Out-Null

    # Stream output
    while (-not $proc.StandardOutput.EndOfStream) {
        $line = $proc.StandardOutput.ReadLine()
        Write-Host $line
    }

    $proc.StandardInput.Write("$mpForSeedPlain`n")
    $proc.StandardInput.Close()
    $proc.WaitForExit()

    if ($proc.ExitCode -ne 0) {
        Write-Err "Seed failed"
        Write-Host $proc.StandardError.ReadToEnd()
        Pause-Exit
    }
    Write-OK "Server registered"

    $mpForSeedPlain = $null
    [GC]::Collect()

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  Setup complete!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Starting the app now..." -ForegroundColor Cyan
    Write-Host "  API:       http://127.0.0.1:7700" -ForegroundColor Cyan
    Write-Host "  Frontend:  http://127.0.0.1:3001" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Press Ctrl+C in this window to stop." -ForegroundColor Yellow
    Write-Host "  (Don't close this window while using the app.)" -ForegroundColor Yellow
    Write-Host ""

    # Start the app (foreground)
    & $venvPython "scripts\start.py"
} finally {
    Pop-Location
}
