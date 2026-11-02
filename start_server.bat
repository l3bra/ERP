@echo off
setlocal

for %%I in ("%~dp0.") do set "PROJECT_DIR=%%~fI"
set "BACKEND_DIR=%PROJECT_DIR%\backend"

if not exist "%BACKEND_DIR%\main.py" (
    echo Missing backend\main.py next to start_server.bat.
    exit /b 1
)

if exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
    set "PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python not found. Install Python or create backend\venv.
        exit /b 1
    )
    set "PYTHON=python"
)

pushd "%BACKEND_DIR%"
"%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port 8000
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
