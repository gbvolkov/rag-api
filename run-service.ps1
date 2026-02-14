param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$NoReload,
    [switch]$InstallDeps,
    [string]$EnvFile = ".env",
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

function Resolve-Python {
    param([string]$VirtualEnvPath)

    $venvPython = Join-Path $VirtualEnvPath "Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCmd) {
        throw "Python executable not found. Install Python or create a venv at '$VirtualEnvPath'."
    }
    return "python"
}

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Host "Env file '$Path' not found. Continuing with current environment."
        return
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            return
        }

        $name = $parts[0].Trim()
        $value = $parts[1].Trim()

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

$python = Resolve-Python -VirtualEnvPath $VenvPath
Import-DotEnv -Path $EnvFile

if ($InstallDeps) {
    Write-Host "Installing dependencies..."
    & $python -m pip install --upgrade pip
    & $python -m pip install -e ".[dev]"
}

$uvicornArgs = @(
    "-m", "uvicorn",
    "app.main:app",
    "--host", $BindHost,
    "--port", "$Port"
)

if (-not $NoReload) {
    $uvicornArgs += "--reload"
}

Write-Host "Starting service at http://$BindHost`:$Port"
& $python @uvicornArgs
