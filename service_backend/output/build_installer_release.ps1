param(
    [string]$PythonExe = "",
    [string]$PackageManager = "",
    [string]$NodeExe = "",
    [string]$NsisExe = "",
    [switch]$SkipDependencies
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Core = Join-Path $Root 'service_core'
$Web = Join-Path $Root 'backend_web'
$Build = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force -Path $Build | Out-Null
if (-not $PythonExe) { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
if (-not $PackageManager) { $PackageManager = (Get-Command npm.cmd -ErrorAction Stop).Source }
if (-not $NsisExe) {
    $nsisCommand = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($nsisCommand) { $NsisExe = $nsisCommand.Source }
    else { $NsisExe = 'C:\Program Files\NSIS\NSIS2.51\Bin\makensis.exe' }
}
if ($NodeExe) { $env:PATH = (Split-Path -Parent $NodeExe) + ';' + $env:PATH }
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" } }
if (-not $SkipDependencies) {
    & $PythonExe -m pip install -r (Join-Path $Core 'requirements.txt')
    Assert-Exit 'Python dependencies'
}
Push-Location $Web
try {
    if (-not $SkipDependencies) {
        if ($PackageManager -match 'pnpm') { & $PackageManager install --frozen-lockfile }
        else { & $PackageManager install }
        Assert-Exit 'Web dependencies'
    }
    & $PackageManager run build
    Assert-Exit 'Vue build'
} finally { Pop-Location }
& $PythonExe -m compileall -q $Core
Assert-Exit 'Python syntax'
& $PythonExe -m PyInstaller --noconfirm --onedir --name TimeTipCore --paths $Root --distpath (Join-Path $Build 'dist') --workpath (Join-Path $Build 'pyinstaller') --specpath $Build (Join-Path $Core 'run_core_bootstrap.py')
Assert-Exit 'Core packaging'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $csc /nologo /target:exe /platform:x64 /optimize+ /reference:System.ServiceProcess.dll ("/out:" + (Join-Path $Build 'TimeTipService.exe')) (Join-Path $Core 'windows_service.cs')
Assert-Exit 'Windows service compilation'
Push-Location $PSScriptRoot
try {
    & $NsisExe 'installer.nsi'
    Assert-Exit 'NSIS installer'
    $installer = Join-Path $PSScriptRoot 'Time-Tip-Service-Setup.exe'
    $hash = Get-FileHash -LiteralPath $installer -Algorithm SHA256
    [IO.File]::WriteAllText("$installer.sha256", $hash.Hash + '  ' + [IO.Path]::GetFileName($installer) + [Environment]::NewLine)
    Get-Item -LiteralPath $installer | Select-Object FullName,Length,LastWriteTime
    $hash | Format-List
} finally { Pop-Location }
