param([int]$Port = 8767, [switch]$NoInstall)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($NoInstall) { throw 'Create .venv or run the launcher without -NoInstall.' }
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
}
if (-not $NoInstall) {
    $wheels = Join-Path $PSScriptRoot 'wheelhouse'
    if (Test-Path -LiteralPath (Join-Path $wheels 'pypdf-6.13.0-py3-none-any.whl')) {
        & $venvPython -m pip install --no-index --find-links $wheels -e .
    } else {
        & $venvPython -m pip install -e .
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See docs/RELEASE_GUIDE.md.' }
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
Write-Host "AXIOM: http://127.0.0.1:$Port"
Write-Host 'Open Saved demos for examples that make no model requests. Press Ctrl+C to stop.'
& $venvPython -m axiom serve --port $Port
exit $LASTEXITCODE
