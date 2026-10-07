@echo off
cd /d "%~dp0"
rem Fake ESP running inside the API container: sends signed frames through the whole chain.
rem "simulate.bat fake" sends forged frames instead (rejected -> CYBER_SPOOFING alert).
rem "simulate.bat anomaly" sends valid frames with a rising temperature (-> ANOMALY alert from IA 2).
echo Ctrl+C pour arreter.
docker compose exec api python simulate.py %1
