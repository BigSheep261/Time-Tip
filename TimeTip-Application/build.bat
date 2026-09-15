@echo off
setlocal
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_installer.ps1"
set "buildResult=%errorlevel%"
popd
echo.
if not "%buildResult%"=="0" (
  echo Build failed. See the error above.
) else (
  echo Created TimeTip-Setup.exe. Run it to install or upgrade.
)
pause
exit /b %buildResult%
