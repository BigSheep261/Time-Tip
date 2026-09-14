param(
    [string]$InstallDir = "$env:ProgramFiles\TimeTipUpdateService",
    [string]$DataDir = "$env:ProgramData\TimeTipUpdateService",
    [string]$RepoUrl = "https://github.com/BigSheep261/Time-Tip.git",
    [string]$PublicBaseUrl = "http://47.116.193.23:8787",
    [int]$Port = 8787
)
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell window.'
}
$sourceExe = Join-Path $PSScriptRoot 'TimeTipUpdateService.exe'
if (-not (Test-Path -LiteralPath $sourceExe)) { throw "Missing $sourceExe. Build the package first." }
# Stop any previous installation before replacing the executable.
$service = Get-Service -Name 'TimeTipUpdateService' -ErrorAction SilentlyContinue
if ($service) { Stop-Service $service -Force -ErrorAction SilentlyContinue; sc.exe delete TimeTipUpdateService | Out-Null }
$oldTask = Get-ScheduledTask -TaskName 'TimeTipUpdateService' -ErrorAction SilentlyContinue
if ($oldTask) { Stop-ScheduledTask -TaskName 'TimeTipUpdateService' -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName 'TimeTipUpdateService' -Confirm:$false }
Get-Process -Name 'TimeTipUpdateService' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
New-Item -ItemType Directory -Force -Path $InstallDir, $DataDir | Out-Null
$targetExe = Join-Path $InstallDir 'TimeTipUpdateService.exe'
Copy-Item -LiteralPath $sourceExe -Destination $targetExe -Force
[Environment]::SetEnvironmentVariable('TIMETIP_UPDATE_ROOT', $DataDir, 'Machine')
[Environment]::SetEnvironmentVariable('TIMETIP_REPO_URL', $RepoUrl, 'Machine')
[Environment]::SetEnvironmentVariable('TIMETIP_RELEASE_BRANCH', 'release', 'Machine')
[Environment]::SetEnvironmentVariable('TIMETIP_PUBLIC_BASE_URL', $PublicBaseUrl.TrimEnd('/'), 'Machine')
[Environment]::SetEnvironmentVariable('TIMETIP_HOST', '0.0.0.0', 'Machine')
[Environment]::SetEnvironmentVariable('TIMETIP_PORT', "$Port", 'Machine')
# A PyInstaller console executable is not a native SCM service. Remove an
# older failed service installation and run the executable through Task
# Scheduler instead; this still starts at boot and can restart on failure.
$action = New-ScheduledTaskAction -Execute $targetExe -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'TimeTipUpdateService' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'TimeTip update service' -Force | Out-Null
if (-not (Get-NetFirewallRule -DisplayName 'TimeTip Update Service' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName 'TimeTip Update Service' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
}
Start-ScheduledTask -TaskName 'TimeTipUpdateService'
Write-Host "TimeTip update task installed and started. Admin page: $($PublicBaseUrl.TrimEnd('/'))/admin"
