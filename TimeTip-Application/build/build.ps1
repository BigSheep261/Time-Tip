param([string]$PythonExe)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$work = Join-Path $PSScriptRoot 'work'
$dist = Join-Path $project 'dist'

if (-not $PythonExe) {
    $candidates = @()
    if ($env:CONDA_PREFIX -and (Split-Path -Leaf $env:CONDA_PREFIX) -eq 'timetip') {
        $candidates += Join-Path $env:CONDA_PREFIX 'python.exe'
    }
    $candidates += @(
        "$env:USERPROFILE\miniconda3\envs\timetip\python.exe",
        "$env:USERPROFILE\.conda\envs\timetip\python.exe",
        "$env:ProgramData\miniconda3\envs\timetip\python.exe"
    )
    $PythonExe = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $PythonExe) {
    throw "Conda environment 'timetip' was not found. Run conda env create -f `"$(Join-Path $project 'environment.yml')`" or pass -PythonExe."
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
$pythonRoot = Split-Path -Parent $PythonExe
$compiler = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw 'The 64-bit Windows .NET Framework 4.x C# compiler is required.'
}

$originalPath = $env:PATH
Push-Location $project
try {
    $env:PATH = @(
        $pythonRoot, "$pythonRoot\Library\bin", "$pythonRoot\Scripts",
        "$env:SystemRoot\System32", $env:SystemRoot
    ) -join ';'
    & $PythonExe -c 'from PyQt6 import QtWidgets; import PyInstaller, jmcomic, fitz, pyzipper'
    if ($LASTEXITCODE -ne 0) {
        throw "Missing build dependencies in $PythonExe. Update the environment using environment.yml."
    }
    & $PythonExe -m PyInstaller --noconfirm --clean --workpath (Join-Path $work 'pyinstaller') --distpath $dist (Join-Path $PSScriptRoot 'TimeTip.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    $portable = Join-Path $dist 'TimeTip'
    $exe = Join-Path $portable 'TimeTip.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Missing $exe" }
    $payload = Join-Path $work 'TimeTip.zip'
    if (Test-Path -LiteralPath $payload) { Remove-Item -LiteralPath $payload }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($portable, $payload, [IO.Compression.CompressionLevel]::Optimal, $false)

    $temporarySetup = Join-Path $work 'TimeTip-Setup.exe'
    $icon = Join-Path $project 'assets\timetip.ico'
    & $compiler /nologo /target:winexe /platform:x64 /codepage:65001 /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll "/win32icon:$icon" "/resource:$payload,TimeTip.Payload.zip" "/out:$temporarySetup" (Join-Path $PSScriptRoot 'TimeTipSetup.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    $setup = Join-Path $dist 'TimeTip-Setup.exe'
    Move-Item -LiteralPath $temporarySetup -Destination $setup -Force
    Write-Host "Created $exe"
    Write-Host "Created $setup"
} finally {
    Pop-Location
    $env:PATH = $originalPath
}
