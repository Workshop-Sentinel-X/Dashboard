# Sentinel-X : contrat d'interface (à partager avec toute l'équipe)

Broker MQTT : `<IP du serveur>:1883` (Mosquitto, authentification obligatoire).
API HTTP : `http://<IP du serveur>:8000` (documentation interactive : `/docs`).

## 1. Comptes MQTT

| Service | Utilisateur / mot de passe | Lit | Écrit |
|---|---|---|---|
| ESP8266 | esp01 / esp01-sx | | sentinel/telemetry |
| FastAPI | api / api-sx | sentinel/telemetry, sentinel/scores, sentinel/alerts | sentinel/validated, sentinel/alerts |
| IA capteurs | ia / ia-sx | sentinel/validated | sentinel/scores, sentinel/alerts |
| IA vision | vision / vision-sx | | sentinel/alerts |
| Telegraf (dashboard) | telegraf / telegraf-sx | sentinel/validated, sentinel/scores, sentinel/alerts | |

Mots de passe à changer avant la démo (fichier `mosquitto/passwd`, droits dans `mosquitto/acl`).

## 2. Trame de l'ESP8266 (sentinel/telemetry), signée HMAC-SHA256

Une enveloppe JSON à deux champs :

    {"p": "<mesure en JSON, sous forme de chaîne>", "s": "<hmac-sha256 hex de p>"}

- `p` est la chaîne JSON de la mesure, exactement telle qu'elle est signée :
  `{"device_id":"esp01","seq":123456,"temp":24.5,"humidity":50.0,"distance":150,"presence":0}`
- `s` = HMAC-SHA256(clé secrète partagée, octets de `p`), en hexadécimal minuscule.
- `seq` doit changer à chaque trame (par exemple `millis()`), c'est ce qui permet de détecter le rejeu.
- Fréquence : 1 trame par seconde. Clé secrète : variable `HMAC_SECRET` (même valeur sur l'ESP et dans l'API).
- Avec ArduinoJson : sérialiser la mesure dans une chaîne, la signer, puis mettre cette chaîne dans `p` (l'échappement est automatique).

## 3. Topics produits par l'API

**sentinel/validated** (trames dont la signature est valide, lues par le dashboard et l'IA capteurs) :

    {"device_id":"esp01","temp":24.5,"humidity":50.0,"distance":150.0,"presence":0}

**sentinel/scores** (IA capteurs, Isolation Forest) :

    {"device_id":"esp01","score":0.12}

**sentinel/alerts** (API, IA capteurs, IA vision) :

    {"code":"INTRUSION","source":"ia_vision","severity":"high","confidence":0.91,"message":"Intrus detecte"}

| code | publié par | quand |
|---|---|---|
| CYBER_SPOOFING | api | signature invalide, trame illisible ou rejouée |
| INTRUSION | ia vision | intrus localisé sur la webcam |
| ANOMALY | ia capteurs | score au-dessus du seuil |

`code`, `source`, `severity` et `message` sont obligatoires (le dashboard en a besoin). `severity` : low, medium, high, critical.

## 4. Routes HTTP de l'API

| Route | Rôle |
|---|---|
| GET /health | état du service, connexion MQTT, âge de la dernière trame valide |
| GET /api/latest[?device_id=] | dernière mesure validée par capteur, avec son âge et le dernier score |
| GET /api/history?minutes=15[&device_id=] | mesures validées récentes (mémoire du service, max 3600 points) |
| GET /api/alerts?limit=50[&code=] | dernières alertes, les plus récentes d'abord |
| GET /api/stats | compteurs : trames reçues, valides, rejetées, alertes par code |
| POST /api/telemetry | ingestion HTTP d'une trame signée (même enveloppe), 401 si rejetée. Pour les tests |
| POST /api/vision/frame | l'IA vision envoie son image (corps = JPEG brut, en-tête `X-API-Key`) |
| GET /api/vision/latest.jpg | dernière image reçue (pour le dashboard) |
| GET /api/vision/status | une image a-t-elle été reçue, et depuis combien de temps |

## 5. Tests

    python tools/send_test_frames.py valid 20    # trames valides
    python tools/send_test_frames.py forged 3    # fausse signature -> alerte CYBER_SPOOFING
    python tools/send_test_frames.py replay      # rejeu -> alerte CYBER_SPOOFING
    python tools/send_test_frames.py garbage     # contenu illisible -> alerte CYBER_SPOOFING
