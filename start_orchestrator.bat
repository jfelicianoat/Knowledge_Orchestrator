@echo off
setlocal

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

set "PYTHONPATH=%APP_DIR%src"

if exist "%APP_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Iniciando Knowledge Orchestrator...
echo Directorio: %APP_DIR%
echo.

"%PYTHON_EXE%" -m knowledge_orchestrator.app --ui

if errorlevel 1 (
    echo.
    echo La aplicacion se cerro con error.
    echo Comprueba que las dependencias esten instaladas:
    echo   python -m pip install -e .
    echo.
    pause
)

endlocal
