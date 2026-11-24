@echo off
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
title AgroMask GIS - Local Web Server
echo.
echo AgroMask GIS  ^|  Local Web Workbench
echo.
if exist ".venv\Scripts\python.exe" goto check_deps
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.11 -m venv .venv
    goto venv_ready
)
py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    goto venv_ready
)
python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    goto venv_ready
)
echo Python 3.11 or newer is required. The bundled offline wheels use 64-bit Python 3.11.
goto failed

:venv_ready
if errorlevel 1 goto failed

:check_deps
if exist ".venv\ready.txt" goto launch
echo Installing the Python packages on first launch. Please wait...
if exist "wheels\*.whl" (
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links wheels -r requirements.txt
    if not errorlevel 1 goto installed
)
echo Trying online installation for this Python version...
".venv\Scripts\python.exe" -m pip install --index-url https://pypi.org/simple -r requirements.txt
if errorlevel 1 goto failed

:installed
type nul > ".venv\ready.txt"

:launch
".venv\Scripts\python.exe" app.py %*
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo Could not start AgroMask GIS. Review the message above.
pause
popd
exit /b 1
