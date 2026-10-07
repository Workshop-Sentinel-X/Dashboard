import hashlib
import hmac
import json
import os

import paho.mqtt.client as mqtt
from fastapi import FastAPI
from contextlib import asynccontextmanager

import db

SECRET = os.getenv("HMAC_SECRET", "dev-secret-change-me").encode()
BROKER = os.getenv("MQTT_HOST", "mosquitto")
PORT = int(os.getenv("MQTT_PORT", "1883"))
# Broker requires a login (dossier technique §4.1); account "api" from the team's mosquitto/acl
MQTT_USER = os.getenv("MQTT_USER", "api")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "api-sx")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to the broker in the background (doesn't crash if it's down, keeps retrying)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(BROKER, PORT)
    client.loop_start()
    yield
    # Shutdown
    client.loop_stop()
    client.disconnect()


app = FastAPI(lifespan=lifespan)


def sign(device_id, timestamp, m):
    # String signed on both sides, e.g. SENTINEL-X-01|1775376120|21.80|44.50|0|142.30
    text = f"{device_id}|{timestamp}|{m['temperature']:.2f}|{m['humidity']:.2f}|{m['motion_detected']}|{m['distance_cm']:.2f}"
    return hmac.new(SECRET, text.encode(), hashlib.sha256).hexdigest()


def send_to_anomaly_model(frame):
    print("VALID ->", frame["metrics"])  # TODO: plug IA 2's model here


def on_message(c, userdata, msg):
    try:
        frame = json.loads(msg.payload)
        valid = hmac.compare_digest(
            sign(frame["device_id"], frame["timestamp"], frame["metrics"]), frame["signature"])
    except Exception:
        valid = False  # malformed frame = rejected too

    if not valid:
        print("REJECTED ->", msg.payload)
        db.save_rejected(msg.payload)
        c.publish("sentinel/alerts", json.dumps({
            "code": "CYBER_SPOOFING",
            "source": "fastapi",
            "severity": "critical",
            "message": "Trame rejetée : signature invalide ou trame malformée",
        }))
        return

    db.save_reading(frame)
    m = frame["metrics"]
    # Flat format from the contract table, read by Telegraf -> Grafana
    c.publish("sentinel/validated", json.dumps({
        "device_id": frame["device_id"],
        "temp": m["temperature"],
        "humidity": m["humidity"],
        "distance": m["distance_cm"],
        "presence": m["motion_detected"],
    }))
    send_to_anomaly_model(frame)


def on_connect(c, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print("Broker refused the connection:", reason_code)  # "Not authorized" = wrong login
        return
    print("Connected to broker as", MQTT_USER)
    c.subscribe("sentinel/telemetry")  # here so it re-subscribes after a broker restart


@app.get("/readings")
def readings(limit: int = 100):
    return db.latest("readings", limit)


@app.get("/rejected")
def rejected(limit: int = 50):
    return db.latest("rejected", limit)
