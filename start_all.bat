@echo off
setlocal

for %%I in ("%~dp0.") do set "PROJECT_DIR=%%~fI"
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "FRONTEND_FILE=%PROJECT_DIR%\frontend\index.html"

if not exist "%BACKEND_DIR%\main.py" (
    echo Missing backend\main.py next to start_all.bat.
    pause
    exit /b 1
)
if not exist "%FRONTEND_FILE%" (
    echo Missing frontend\index.html next to start_all.bat.
    pause
    exit /b 1
)

if exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
    set "PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python not found. Install Python or create backend\venv.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

start "ERP API" /D "%BACKEND_DIR%" "%PYTHON%" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
start "" "%FRONTEND_FILE%"

endlocal
