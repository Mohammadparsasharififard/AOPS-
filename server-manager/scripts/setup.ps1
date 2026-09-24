<#
.SYNOPSIS
    Windows PowerShell setup wrapper for Personal Server Manager.
.DESCRIPTION
    Calls the cross-platform setup.py — works on Windows without bash.
.EXAMPLE
    .\scripts\setup.ps1
#>

$ErrorActionPreference = "Stop"

# Find python (python or python3)
$python = $null
foreach ($candidate in @("python", "python3")) {
    try {
        $version = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$version" -match "Python 3") {
            $python = $candidate
            break
        }
    } catch {
        # continue
    }
}

if (-not $python) {
    Write-Error "Python 3 not found. Install from https://python.org (3.11+ recommended)."
    exit 1
}

Write-Host "Using Python: $python" -ForegroundColor Cyan

$scriptPath = Join-Path $PSScriptRoot "setup.py"
& $python $scriptPath
exit $LASTEXITCODE
