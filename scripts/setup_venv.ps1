# Creates the project virtual environment (.venv) inside this folder on Windows.
# Usage (from the project root, in PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (Test-Path ".venv") {
    Write-Host ".venv already exists - skipping creation."
} else {
    $exe = "python"; $verArgs = @()
    foreach ($v in @("3.12", "3.11")) {
        & py "-$v" --version *> $null
        if ($LASTEXITCODE -eq 0) { $exe = "py"; $verArgs = @("-$v"); break }
    }
    Write-Host "Creating .venv with: $exe $verArgs"
    & $exe @verArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if (Test-Path "requirements.txt") {
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}
Write-Host ""
Write-Host "Done. Activate with:  .\.venv\Scripts\Activate.ps1"
