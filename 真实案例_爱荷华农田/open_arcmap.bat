@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\arcmap_support\launch_arcmap.ps1" -CaseFolder "%~dp0." %*
if errorlevel 1 (
    echo.
    echo ArcMap setup did not complete. See the error above.
    if /I not "%~1"=="-PrepareOnly" pause
    exit /b 1
)
