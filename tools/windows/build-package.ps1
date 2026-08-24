$ErrorActionPreference = "Stop"

$Repository = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Repository

Write-Host "Preparing the isolated ChannelOS packaging environment..."

$PackagingPython = Join-Path $Repository ".package-venv\Scripts\python.exe"
if (-not (Test-Path $PackagingPython)) {
    py -3.12 -m venv .package-venv
}

& $PackagingPython -m pip install --upgrade pip
& $PackagingPython -m pip install -r .\packaging\windows\requirements-build.txt
& $PackagingPython -m pip install -e . --no-deps

Write-Host "Running the complete automated test suite..."
& $PackagingPython -m pytest -q

Write-Host "Building and auditing ChannelOS for Windows x64..."
& $PackagingPython .\tools\windows\package_windows.py

Write-Host ""
Write-Host "Package created in:"
Write-Host (Join-Path $Repository "dist\windows")
