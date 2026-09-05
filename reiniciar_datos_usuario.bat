@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\reiniciar_datos_usuario.ps1"
if errorlevel 1 (
    echo.
    echo No se ha realizado la limpieza. Revisa el mensaje anterior.
    pause
)
endlocal
