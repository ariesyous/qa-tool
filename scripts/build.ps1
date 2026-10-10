param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
$originalBuildPath = $env:PATH
$originalPyInstallerCache = $env:PYINSTALLER_CONFIG_DIR
try {
    # Do not collect unrelated DLLs from tools (Poppler, Qt SDKs, etc.) on PATH.
    $env:PATH = (Join-Path $PWD '.venv\Scripts') + ';' + (Join-Path $env:SystemRoot 'System32') + ';' + $env:SystemRoot
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PWD '.validation\pyinstaller-cache'
    & '.\.venv\Scripts\python.exe' -m PyInstaller --clean --noconfirm --distpath $OutputDirectory QANarrator.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    Write-Host "Built $OutputDirectory\QANarrator\QANarrator.exe. Distribute the entire QANarrator folder."
} finally {
    $env:PATH = $originalBuildPath
    $env:PYINSTALLER_CONFIG_DIR = $originalPyInstallerCache
    Pop-Location
}

