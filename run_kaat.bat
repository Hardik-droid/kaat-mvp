@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo KAAT's virtual environment is missing.
    echo Run: powershell -ExecutionPolicy Bypass -File .\setup.ps1 -DownloadFFmpeg
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Could not activate KAAT's virtual environment. Rerun setup.ps1.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" doctor.py --startup
if errorlevel 1 (
    echo.
    echo KAAT startup checks failed. See the FAIL lines above.
    echo Repair dependencies: powershell -ExecutionPolicy Bypass -File .\setup.ps1 -DownloadFFmpeg
    pause
    exit /b 1
)
if /i "%~1"=="--check" exit /b 0
".venv\Scripts\python.exe" app.py %*
if errorlevel 1 (
    echo.
    echo KAAT stopped with an error. See the error above.
    echo Diagnostics: .venv\Scripts\python.exe doctor.py
    pause
    exit /b 1
)
exit /b 0
