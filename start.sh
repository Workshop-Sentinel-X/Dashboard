#!/bin/sh
# Mac / Linux equivalent of start.bat
cd "$(dirname "$0")" || exit 1
docker compose up -d --build || exit 1
echo
echo "Sentinel-X est demarre :"
echo "  Grafana : http://localhost:3000   (admin / admin)"
echo "  API     : http://localhost:8000/docs"
echo "  MQTT    : port 8883"
echo
echo "Donnees de test : docker compose exec api python simulate.py    Arreter : docker compose down"
