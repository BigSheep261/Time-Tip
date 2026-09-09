param([string]$PythonExe = "")
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$originalPath = $env:PATH
$originalDebug = $env:TIMETIP_DEBUG_BUILD
try {
    if (-not $PythonExe) {
        # Prefer the project-managed environments. A system Python may exist
        # but still miss the Qt/PyInstaller build dependencies.
        $pythonCandidates = @(
            (Join-Path $PSScriptRoot '.conda-build\python.exe'),
            (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
        )
        $PythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $PythonExe) { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
    }
    # Normalize relative paths before deriving the Conda layout.
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
    $pythonDir = Split-Path $PythonExe
    # Conda keeps native runtime DLLs (for example ffi-8.dll and OpenSSL)
    # under Library\bin rather than beside python.exe. Include that directory
    # while PyInstaller resolves dependencies, otherwise the packaged app can
    # fail before the Qt event loop starts.
    $condaLibraryBin = Join-Path $pythonDir 'Library\bin'
    & $PythonExe -c "import PyQt6, PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        throw "构建环境缺少 PyQt6 或 PyInstaller（当前 Python：$PythonExe）。请运行：$PythonExe -m pip install -r requirements-dev.txt"
    }
    & $PythonExe -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no package was produced.' }
    # Prevent unrelated tools on PATH from contributing incompatible Qt DLLs.
    $pathParts = @($pythonDir, "$pythonDir\Scripts")
    if (Test-Path -LiteralPath $condaLibraryBin) { $pathParts += $condaLibraryBin }
    $pathParts += @("$env:SystemRoot\System32", $env:SystemRoot)
    $env:PATH = ($pathParts -join ';')
    $env:TIMETIP_DEBUG_BUILD = $null
    & $PythonExe -m PyInstaller --noconfirm --clean TimeTip.build.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    $distDir = Join-Path $PSScriptRoot 'dist\TimeTip'
    if (-not (Test-Path -LiteralPath (Join-Path $distDir 'TimeTip.exe'))) { throw 'Missing application executable.' }
    $buildDir = Join-Path $PSScriptRoot 'build\installer'
    New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
    $csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $csc)) { throw 'Windows .NET Framework 4.x compiler is required.' }
    $stubPath = Join-Path $buildDir 'stub.exe'
    $sourcePath = Join-Path $PSScriptRoot 'installer_stub.cs'
    & $csc /nologo /target:winexe /platform:x64 /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /codepage:65001 /win32icon:assets\timetip.ico "/out:$stubPath" $sourcePath
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zipPath = Join-Path $buildDir 'payload.zip'
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath }
    [IO.Compression.ZipFile]::CreateFromDirectory($distDir, $zipPath, [IO.Compression.CompressionLevel]::Optimal, $false)
    $sha = [Security.Cryptography.SHA256]::Create()
    $zip = [IO.File]::OpenRead($zipPath)
    $stub = [IO.File]::OpenRead($stubPath)
    $outputPath = Join-Path $PSScriptRoot 'TimeTip-Setup.exe'
    $temporaryOutput = Join-Path $buildDir 'TimeTip-Setup.new.exe'
    $output = [IO.File]::Create($temporaryOutput)
    try {
        $hash = $sha.ComputeHash($zip)
        $zip.Position = 0
        $stub.CopyTo($output)
        $zip.CopyTo($output)
        $magic = [Text.Encoding]::ASCII.GetBytes('TTIPZIP2')
        $length = [BitConverter]::GetBytes([Int64]$zip.Length)
        $output.Write($magic, 0, 8)
        $output.Write($length, 0, 8)
        $output.Write($hash, 0, 32)
    } finally {
        $output.Dispose()
        $stub.Dispose()
        $zip.Dispose()
        $sha.Dispose()
    }
    Move-Item -LiteralPath $temporaryOutput -Destination $outputPath -Force
    & $PythonExe tests\verify_package.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaged integration checks failed.' }
    Write-Host "Created $outputPath"
} finally {
    $env:PATH = $originalPath
    $env:TIMETIP_DEBUG_BUILD = $originalDebug
    Pop-Location
}

