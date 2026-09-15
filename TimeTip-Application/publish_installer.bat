@echo off
setlocal
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_installer.ps1"
set "publishResult=%errorlevel%"
popd
echo.
if not "%publishResult%"=="0" (
  echo Publish failed. See the error above.
) else (
  echo Installer published to the release branch.
)
pause
exit /b %publishResult%
