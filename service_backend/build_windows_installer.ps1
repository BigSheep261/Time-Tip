param([string]$PythonExe = "")
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not $PythonExe) { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
    & $PythonExe -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '当前 Python 缺少 PyInstaller，请先运行 pip install pyinstaller' }
    & $PythonExe -m PyInstaller --noconfirm --clean --onefile --name TimeTipUpdateService server.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败。' }
    $packageDir = Join-Path $PSScriptRoot 'dist\TimeTipUpdateService-Windows'
    New-Item -ItemType Directory -Force -Path $packageDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dist\TimeTipUpdateService.exe') -Destination $packageDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install_windows.ps1') -Destination $packageDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination $packageDir -Force
    $zip = Join-Path $PSScriptRoot 'TimeTipUpdateService-Windows.zip'
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -Path (Join-Path $packageDir '*') -DestinationPath $zip -CompressionLevel Optimal
    Write-Host "Created $zip"
} finally { Pop-Location }
