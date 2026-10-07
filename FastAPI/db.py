import sqlite3
import threading
import time
import os

# One shared connection; the lock is needed because MQTT messages and API requests run on different threads
conn = sqlite3.connect(os.getenv("DB_PATH", "sentinel.db"), check_same_thread=False)
conn.row_factory = sqlite3.Row
lock = threading.Lock()

conn.executescript("""
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    received_at INTEGER,
    device_id TEXT,
    timestamp INTEGER,
    temperature REAL,
    humidity REAL,
    motion_detected INTEGER,
    distance_cm REAL
);
CREATE TABLE IF NOT EXISTS rejected (
    id INTEGER PRIMARY KEY,
    received_at INTEGER,
    payload TEXT
);
""")


def save_reading(frame):
    m = frame["metrics"]
    with lock:
        conn.execute(
            "INSERT INTO readings (received_at, device_id, timestamp, temperature, humidity, motion_detected, distance_cm)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(time.time()), frame["device_id"], frame["timestamp"],
             m["temperature"], m["humidity"], m["motion_detected"], m["distance_cm"]))
        conn.commit()


def save_rejected(payload: bytes):
    with lock:
        conn.execute("INSERT INTO rejected (received_at, payload) VALUES (?, ?)",
                     (int(time.time()), payload.decode(errors="replace")))
        conn.commit()


def latest(table, limit):
    with lock:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
