@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
set "result=%errorlevel%"
if not "%result%"=="0" (
    echo Build failed. See the error above.
) else (
    echo Created dist\TimeTip\TimeTip.exe and dist\TimeTip-Setup.exe.
)
if not defined TIMETIP_BUILD_NO_PAUSE pause
exit /b %result%
