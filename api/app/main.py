"""Sentinel-X : service FastAPI (passerelle de confiance).

MQTT  : lit sentinel/telemetry (trames signées HMAC), vérifie, republie sur sentinel/validated,
        lève CYBER_SPOOFING sur sentinel/alerts. Écoute aussi sentinel/scores et sentinel/alerts.
HTTP  : routes de lecture (latest, history, alerts, stats), ingestion de test, image webcam.
"""
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Optional

import paho.mqtt.client as mqtt
from fastapi import FastAPI, Header, HTTPException, Request, Response

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "api")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "api-sx")
HMAC_SECRET = os.getenv("HMAC_SECRET", "change-me-hmac-secret").encode()
VISION_API_KEY = os.getenv("VISION_API_KEY", "vision-key-change-me")
ALERT_MIN_INTERVAL = float(os.getenv("ALERT_MIN_INTERVAL", "2"))  # anti-spam par code d'alerte (s)
MAX_FRAME_BYTES = 2 * 1024 * 1024

T_TELEMETRY = "sentinel/telemetry"
T_VALIDATED = "sentinel/validated"
T_SCORES = "sentinel/scores"
T_ALERTS = "sentinel/alerts"

log = logging.getLogger("sentinelx.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

lock = threading.Lock()
history = deque(maxlen=3600)          # mesures validées
alerts = deque(maxlen=200)            # alertes reçues sur sentinel/alerts
latest = {}                           # device_id -> dernière mesure validée
scores = {}                           # device_id -> dernier score IA
sig_order = deque(maxlen=500)         # signatures récentes (anti-rejeu)
sig_set = set()
last_alert_at = {}
stats = {"frames_received": 0, "frames_valid": 0, "frames_rejected": 0, "alerts": {}}
vision = {"jpeg": None, "ts": None}

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sentinelx-api")


# ---------- vérification des trames ----------
def is_replay(sig: str) -> bool:
    with lock:
        if sig in sig_set:
            return True
        if len(sig_order) == sig_order.maxlen:
            sig_set.discard(sig_order[0])
        sig_order.append(sig)
        sig_set.add(sig)
    return False


def verify_envelope(raw: bytes):
    """Enveloppe attendue : {"p": "<json de la mesure, en chaîne>", "s": "<hmac-sha256 hex de p>"}.
    Retourne (mesure, None, None) si OK, sinon (None, raison, type)."""
    try:
        env = json.loads(raw)
        payload, sig = env["p"], env["s"]
        if not isinstance(payload, str) or not isinstance(sig, str):
            raise ValueError("types")
    except Exception:
        return None, "Trame illisible ou enveloppe invalide", "spoof"

    expected = hmac.new(HMAC_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig.lower()):
        return None, "Signature HMAC invalide, trame rejetee", "spoof"
    if is_replay(expected):
        return None, "Trame rejouee (signature deja vue)", "spoof"

    try:
        d = json.loads(payload)
        clean = {
            "device_id": str(d["device_id"]),
            "temp": float(d["temp"]),
            "humidity": float(d["humidity"]),
            "distance": float(d["distance"]),
            "presence": int(d["presence"]),
        }
    except Exception:
        return None, "Signature valide mais champs manquants ou mal formes", "malformed"
    return clean, None, None


def raise_alert(code: str, source: str, severity: str, message: str):
    now = time.time()
    with lock:
        if now - last_alert_at.get(code, 0) < ALERT_MIN_INTERVAL:
            return
        last_alert_at[code] = now
    payload = {"code": code, "source": source, "severity": severity, "message": message}
    client.publish(T_ALERTS, json.dumps(payload), qos=1)
    log.warning("ALERTE %s : %s", code, message)


def process_frame(raw: bytes) -> dict:
    with lock:
        stats["frames_received"] += 1
    data, reason, kind = verify_envelope(raw)
    if data is None:
        with lock:
            stats["frames_rejected"] += 1
        if kind == "spoof":
            raise_alert("CYBER_SPOOFING", "fastapi", "critical", reason)
        else:
            log.warning("Trame rejetee : %s", reason)
        return {"accepted": False, "reason": reason}

    client.publish(T_VALIDATED, json.dumps(data), qos=0)  # -> Telegraf, IA capteurs
    rec = {**data, "ts": time.time()}
    with lock:
        stats["frames_valid"] += 1
        latest[data["device_id"]] = rec
        history.append(rec)
    return {"accepted": True}


# ---------- MQTT ----------
def on_connect(c, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        log.error("Connexion MQTT refusee : %s", reason_code)
        return
    log.info("MQTT connecte (%s:%s)", MQTT_HOST, MQTT_PORT)
    c.subscribe([(T_TELEMETRY, 1), (T_SCORES, 0), (T_ALERTS, 1)])


def on_message(c, userdata, msg):
    try:
        if msg.topic == T_TELEMETRY:
            process_frame(msg.payload)
        elif msg.topic == T_SCORES:
            d = json.loads(msg.payload)
            with lock:
                scores[str(d.get("device_id", "esp01"))] = {"score": d.get("score"), "ts": time.time()}
        elif msg.topic == T_ALERTS:
            d = json.loads(msg.payload)
            with lock:
                alerts.appendleft({**d, "ts": time.time()})
                code = str(d.get("code", "UNKNOWN"))
                stats["alerts"][code] = stats["alerts"].get(code, 0) + 1
    except Exception:
        log.exception("Erreur de traitement sur %s", msg.topic)


client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.reconnect_delay_set(min_delay=1, max_delay=10)
client.on_connect = on_connect
client.on_message = on_message


@asynccontextmanager
async def lifespan(app: FastAPI):
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    yield
    client.loop_stop()
    client.disconnect()


app = FastAPI(title="Sentinel-X API", version="1.0", lifespan=lifespan)


# ---------- routes HTTP ----------
@app.get("/health")
def health():
    with lock:
        ages = [time.time() - r["ts"] for r in latest.values()]
    return {"status": "ok", "mqtt_connected": client.is_connected(),
            "last_valid_frame_age_s": round(min(ages), 1) if ages else None}


@app.get("/api/latest")
def api_latest(device_id: Optional[str] = None):
    """Dernière mesure validée par capteur, avec son âge et le dernier score IA."""
    now = time.time()
    with lock:
        out = {d: {**r, "age_s": round(now - r["ts"], 1), "score": scores.get(d, {}).get("score")}
               for d, r in latest.items() if not device_id or d == device_id}
    if device_id and not out:
        raise HTTPException(404, "capteur inconnu")
    return out


@app.get("/api/history")
def api_history(minutes: int = 15, device_id: Optional[str] = None):
    """Mesures validées des N dernières minutes (mémoire du service, max 3600 points)."""
    since = time.time() - minutes * 60
    with lock:
        return [r for r in history if r["ts"] >= since and (not device_id or r["device_id"] == device_id)]


@app.get("/api/alerts")
def api_alerts(limit: int = 50, code: Optional[str] = None):
    """Dernières alertes (cyber, intrusion, anomalie), les plus récentes d'abord."""
    with lock:
        items = [a for a in alerts if not code or a.get("code") == code]
    return items[:limit]


@app.get("/api/stats")
def api_stats():
    with lock:
        return {**stats, "alerts": dict(stats["alerts"])}


@app.post("/api/telemetry")
async def api_telemetry(request: Request):
    """Ingestion HTTP d'une trame signée (même enveloppe que MQTT). Pratique pour tester sans ESP."""
    raw = await request.body()
    result = process_frame(raw)
    if not result["accepted"]:
        raise HTTPException(401, result["reason"])
    return result


@app.post("/api/vision/frame")
async def vision_post(request: Request, x_api_key: Optional[str] = Header(None)):
    """L'IA vision envoie ici sa dernière image (corps = JPEG brut, en-tête X-API-Key)."""
    if not x_api_key or not hmac.compare_digest(x_api_key, VISION_API_KEY):
        raise HTTPException(401, "cle API invalide")
    body = await request.body()
    if not body or len(body) > MAX_FRAME_BYTES:
        raise HTTPException(413, "image vide ou trop volumineuse")
    with lock:
        vision["jpeg"], vision["ts"] = body, time.time()
    return {"stored": True, "bytes": len(body)}


@app.get("/api/vision/latest.jpg")
def vision_latest():
    with lock:
        jpeg = vision["jpeg"]
    if jpeg is None:
        raise HTTPException(404, "aucune image recue")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/vision/status")
def vision_status():
    with lock:
        ts = vision["ts"]
    return {"has_frame": ts is not None, "age_s": round(time.time() - ts, 1) if ts else None}
