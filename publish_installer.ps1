param([string]$PythonExe = "")

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$releaseWorktree = $null

try {
    $versionSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'app\version.py') -Raw
    if ($versionSource -notmatch '(?m)^APP_VERSION\s*=\s*["'']([^"'']+)["'']\s*$') {
        throw '无法从 app/version.py 读取 APP_VERSION。'
    }
    $version = $Matches[1]
    if ($version -notmatch '^\d+(\.\d+)+$') {
        throw "无效版本号：$version"
    }

    & (Join-Path $PSScriptRoot 'build_installer.ps1') -PythonExe $PythonExe
    $installer = Join-Path $PSScriptRoot 'TimeTip-Setup.exe'
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw "打包完成后未找到安装包：$installer"
    }

    & git fetch origin release
    if ($LASTEXITCODE -ne 0) { throw '获取 origin/release 失败。' }

    $releaseWorktree = Join-Path $PSScriptRoot ("build\release-publish-$version")
    if (Test-Path -LiteralPath $releaseWorktree) {
        & git worktree remove --force $releaseWorktree
        if ($LASTEXITCODE -ne 0) { throw "清理旧发布工作区失败：$releaseWorktree" }
    }
    & git worktree add --detach $releaseWorktree origin/release
    if ($LASTEXITCODE -ne 0) { throw '创建 release 临时工作区失败。' }

    # The update service reads APP_VERSION from the release branch, so keep
    # that metadata aligned with the installer built from main.
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app\version.py') -Destination (Join-Path $releaseWorktree 'app\version.py') -Force
    $target = Join-Path $releaseWorktree ("release\TimeTip-Setup-$version.exe")
    Copy-Item -LiteralPath $installer -Destination $target -Force
    & git -C $releaseWorktree add -- "app/version.py" "release/TimeTip-Setup-$version.exe"
    if ($LASTEXITCODE -ne 0) { throw '加入安装包失败。' }

    & git -C $releaseWorktree diff --cached --quiet -- "app/version.py" "release/TimeTip-Setup-$version.exe"
    if ($LASTEXITCODE -ne 0) {
        & git -C $releaseWorktree commit -m $version
        if ($LASTEXITCODE -ne 0) { throw '提交 release 分支失败。' }
    } else {
        Write-Host "release 分支已包含 $version 安装包，跳过重复提交。"
    }

    & git -C $releaseWorktree push origin HEAD:release
    if ($LASTEXITCODE -ne 0) { throw '推送 release 分支失败。' }
    Write-Host "已将 TimeTip-Setup-$version.exe 推送到 origin/release。"
} finally {
    if ($releaseWorktree -and (Test-Path -LiteralPath $releaseWorktree)) {
        & git worktree remove --force $releaseWorktree
    }
    Pop-Location
}
