@echo off
cd /d "%~dp0"

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop n'est pas lance. Lance-le, attends "Engine running", puis relance ce script.
  pause
  exit /b 1
)

docker compose up -d --build
if errorlevel 1 (
  echo Echec du demarrage, voir les erreurs ci-dessus.
  pause
  exit /b 1
)

echo.
echo Sentinel-X est demarre :
echo   Grafana : http://localhost:3000   (admin / admin)
echo   API     : http://localhost:8000/docs
echo   MQTT    : port 8883
echo.
echo Donnees de test : simulate.bat    Arreter : stop.bat
start "" http://localhost:3000
pause
