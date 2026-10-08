#!/bin/sh
# VM (TLS): same as start.sh, plus the Cyber override
cd "$(dirname "$0")" || exit 1
docker compose -f docker-compose.yml -f docker-compose.cyber.yml up -d --build || exit 1
echo
echo "Sentinel-X (TLS) est demarre :"
echo "  Grafana : http://<IP de la VM>:3000"
echo "  API     : http://<IP de la VM>:8000/docs"
echo "  MQTT    : <IP de la VM>:8883 (TLS, certificat CA : sentinel-ca.crt)"
echo
echo "Donnees de test : docker compose exec api python simulate.py [fake|anomaly]"
