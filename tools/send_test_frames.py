"""Envoie des trames de test signées HMAC sur sentinel/telemetry (comme le ferait l'ESP8266).

Usage :
  pip install paho-mqtt
  python tools/send_test_frames.py valid 20      # 20 trames valides
  python tools/send_test_frames.py forged 3      # mauvaise signature -> CYBER_SPOOFING
  python tools/send_test_frames.py replay        # même trame valide envoyée 2 fois -> rejeu
  python tools/send_test_frames.py garbage       # contenu illisible -> CYBER_SPOOFING
Variables : MQTT_HOST (localhost), HMAC_SECRET (doit être celui de l'API).
"""
import hashlib, hmac, json, os, random, sys, time
import paho.mqtt.client as mqtt

HOST = os.getenv("MQTT_HOST", "localhost")
SECRET = os.getenv("HMAC_SECRET", "change-me-hmac-secret").encode()
TOPIC = "sentinel/telemetry"


def frame(secret=SECRET):
    payload = json.dumps({
        "device_id": "esp01",
        "seq": int(time.time() * 1000) + random.randint(0, 999),
        "temp": round(random.uniform(20, 26), 1),
        "humidity": round(random.uniform(40, 60), 1),
        "distance": random.randint(100, 200),
        "presence": random.randint(0, 1),
    }, separators=(",", ":"))
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return json.dumps({"p": payload, "s": sig})


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "valid"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set("esp01", "esp01-sx")
    c.connect(HOST, 8883)
    c.loop_start()

    def send(msg):
        c.publish(TOPIC, msg, qos=1).wait_for_publish()

    if mode == "valid":
        for _ in range(n):
            send(frame()); time.sleep(1)
    elif mode == "forged":
        for _ in range(n):
            send(frame(b"mauvais-secret")); time.sleep(3)
    elif mode == "replay":
        f = frame(); send(f); time.sleep(1); send(f)
    elif mode == "garbage":
        send("pas du json"); 
    print("termine :", mode)
    c.loop_stop(); c.disconnect()


main()
