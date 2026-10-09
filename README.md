# Sentinel-X : stack serveur (Mosquitto + API FastAPI + Telegraf + InfluxDB + Grafana)

## Démarrage

Prérequis : Docker Desktop lancé ("Engine running").

1. Cloner le repo (branche `dev`)
2. Double-cliquer sur **`start.bat`** (Mac/Linux : `./start.sh`)
3. Grafana s'ouvre sur http://localhost:3000 (admin / admin)

Données de test sans l'ESP : double-cliquer sur **`simulate.bat`**
(`simulate.bat fake` envoie des trames falsifiées -> alerte `CYBER_SPOOFING`,
`simulate.bat anomaly` fait monter la température -> alerte `ANOMALY` de l'IA 2).
Arrêter : **`stop.bat`**.

| Service  | Adresse |
|---|---|
| Grafana  | http://localhost:3000 |
| API      | http://localhost:8000/docs |
| InfluxDB | http://localhost:8086 |
| MQTT     | `<IP du serveur>:8883` |

## Démo locale avec le vrai NodeMCU (branche `demo-locale`)

1. `start.bat` (ou `docker compose up -d --build`)
2. PowerShell **en administrateur** : `powershell -ExecutionPolicy Bypass -File .\demo-reseau.ps1`
   (ouvre le port 8883 et affiche l'IP Wi-Fi du PC)
3. Dashboard du NodeMCU > « Envoi vers l'API » : IP du PC, port 8883, TLS **Non**, `esp01` / `esp01-sx`
4. Vérifier : `docker compose logs -f api` doit afficher `VALID -> {...}` chaque seconde,
   puis Grafana (http://localhost:3000) se remplit avec les vraies mesures.

## Comptes MQTT

Définis dans `mosquitto/passwd` (droits dans `mosquitto/acl`). Mot de passe = `<compte>-sx`,
à changer avant la démo.

| Compte | Usage |
|---|---|
| esp01 | ESP8266 (publie `sentinel/telemetry`) |
| api | API FastAPI |
| ia | IA capteurs |
| vision | IA vision |
| telegraf | Dashboard |

Ajouter ou changer un compte :

    docker compose exec mosquitto mosquitto_passwd -b /mosquitto/config/passwd <compte> <mot de passe>
    docker compose restart mosquitto

## API

L'API (dossier `FastAPI/`) écoute `sentinel/telemetry`, vérifie la signature HMAC, puis publie les mesures
validées sur `sentinel/validated` et les alertes sur `sentinel/alerts`. La clé HMAC (`HMAC_SECRET`) et le mot
de passe MQTT de l'API (`MQTT_API_PASSWORD`) peuvent être surchargés dans un fichier `.env`.

Logs : `docker compose logs -f api`

## Grafana

Requête Flux pour un panneau (champ temp, mesure "telemetry") :

    from(bucket: "telemetry")
      |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
      |> filter(fn: (r) => r._measurement == "telemetry" and r._field == "temp")
