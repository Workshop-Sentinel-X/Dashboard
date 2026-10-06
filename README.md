# Sentinel-X : stack serveur (Mosquitto + InfluxDB + Grafana)

    docker compose up -d

- Grafana  : http://localhost:3000  (identifiants dans .env)
- InfluxDB : http://localhost:8086
- MQTT     : <IP du serveur>:1883

Test sans ESP :

    docker exec sentinelx-mosquitto mosquitto_pub -t sentinelx/esp01/telemetry -m '{"device_id":"esp01","temp":24.5,"gas":312,"presence":0}'

Requête Flux pour un panneau (champ temp, mesure "telemetry") :

    from(bucket: "telemetry")
      |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
      |> filter(fn: (r) => r._measurement == "telemetry" and r._field == "temp")
