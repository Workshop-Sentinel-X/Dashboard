# Fake ESP8266. Run: python simulate.py           -> valid frames (normal readings)
#                    python simulate.py fake      -> forged frames (wrong key) -> CYBER_SPOOFING
#                    python simulate.py anomaly   -> valid frames, temperature rising +0.3 °C/s -> ANOMALY
import json
import os
import random
import sys
import time

import paho.mqtt.client as mqtt

import main

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
if mode == "fake":
    main.SECRET = b"wrong-key"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
main.configure(client)  # same TLS settings as the API (MQTT_CA_CERT)
# ...but logs in as the ESP's account, since it plays the ESP
client.username_pw_set(os.getenv("SIM_USER", "esp01"), os.getenv("SIM_PASSWORD", "esp01-sx"))
client.connect(os.getenv("MQTT_HOST", "localhost"), main.PORT)
client.loop_start()  # background thread: keeps the connection alive

i = 0
while True:
    ts = int(time.time())
    # Same "normal" as the data IA 2's model was trained on (anomaly_detector.generate_demo_data)
    metrics = {
        "temperature": round(random.gauss(22, 0.1), 2),
        "humidity": round(random.gauss(45, 0.5), 2),
        "motion_detected": 0,
        "distance_cm": round(random.gauss(150, 1), 2),
    }
    if mode == "anomaly" and i >= 15:  # 15 s of normal readings first, then the fire starts
        metrics["temperature"] = round(22 + 0.3 * (i - 15), 2)
    frame = {"device_id": "SENTINEL-X-01", "timestamp": ts, "metrics": metrics,
             "signature": main.sign("SENTINEL-X-01", ts, metrics)}
    client.publish("sentinel/telemetry", json.dumps(frame))
    print(frame)
    i += 1
    time.sleep(1)
