@echo off
setlocal
cd /d "%~dp0"

title QeiVision Auditoria

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No se encontro el entorno Python local en .venv.
  echo Ejecutar: python -m venv .venv
  echo Luego: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo ========================================================
echo   Iniciando QeiVision Auditoria (Morado Oscuro)
echo ========================================================

tasklist /FI "IMAGENAME eq SmartPSSLite.exe" /NH | find /I "SmartPSSLite.exe" >nul
if errorlevel 1 (
  if exist "C:\Program Files\SmartPSSLite\SmartPSSLite.exe" (
    echo [INFO] Abriendo SmartPSS Lite y esperando que conecten los DVRs...
    start "" /min "C:\Program Files\SmartPSSLite\SmartPSSLite.exe"
    ping -n 7 127.0.0.1 >nul
  )
)

echo [INFO] Abriendo consola en el navegador: http://localhost:8080
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 1; Start-Process 'http://localhost:8080'"

".venv\Scripts\python.exe" server.py --port 8080
if errorlevel 1 (
  echo.
  echo [ERROR] El servidor finalizo con codigo de error %errorlevel%.
  pause
)

endlocal
