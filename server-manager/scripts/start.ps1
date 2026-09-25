<#
.SYNOPSIS
    Windows PowerShell start wrapper for Personal Server Manager.
.DESCRIPTION
    Calls the cross-platform start.py — works on Windows without bash.
.EXAMPLE
    .\scripts\start.ps1
#>

$ErrorActionPreference = "Stop"

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

$scriptPath = Join-Path $PSScriptRoot "start.py"
& $python $scriptPath
exit $LASTEXITCODE
