"""
Sentinel-X - IA 2 : détection d'anomalies en temps réel, pour le backend.

Le backend FastAPI (Dev 2) appelle process() pour chaque trame de
sentinel/telemetry, APRÈS avoir vérifié la signature HMAC (Cyber 1) :
une trame pirate ne doit jamais atteindre l'IA.

    from detecteur_temps_reel import SentinelAnomalyDetector

    detector = SentinelAnomalyDetector()          # une seule fois, au démarrage
    ...
    alert = detector.process(trame)               # à chaque trame valide
    if alert is not None:
        mqtt_client.publish("sentinel/alerts", json.dumps(alert))
"""

import math
from collections import deque
from pathlib import Path

import joblib
import pandas as pd

from anomaly_detector import (
    CONFIRMATION,
    FEATURES,
    INCIDENT_GAP,
    MODEL_PATH,
    SENSOR_LIMITS,
    SMOOTH_WINDOW,
    TREND_WINDOW,
    detect,
)

# Assez de mesures pour calculer la tendance des 3 dernières (confirmation)
HISTORY_SIZE = TREND_WINDOW + SMOOTH_WINDOW + CONFIRMATION

# Message affiché à l'opérateur selon le capteur qui s'écarte le plus du normal
RECOMMENDED_ACTIONS = {
    "distance_cm": "Approche suspecte : vérifier la caméra du secteur",
    "motion_detected": "Objet au contact du boîtier : vérifier la caméra du secteur",
    "temperature": "Dérive thermique : inspecter le local (risque d'incendie)",
    "humidity": "Mesure d'humidité incohérente : vérifier le capteur DHT22",
}


def check_metrics(metrics: dict) -> dict[str, float]:
    """Renvoie les 4 mesures en nombres, ou lève ValueError si l'une est absente,
    vide (NaN) ou physiquement impossible. Une mesure refusée n'entre jamais
    dans l'historique : elle ne peut donc pas fausser les mesures suivantes."""
    checked = {}
    for feature, (low, high) in SENSOR_LIMITS.items():
        if feature not in metrics:
            raise ValueError(f"{feature} absente")
        value = float(metrics[feature])
        if not math.isfinite(value):
            raise ValueError(f"{feature} vide (lecture ratée du capteur)")
        if not low <= value <= high:
            raise ValueError(f"{feature} = {value} impossible (plage du capteur : {low} à {high})")
        checked[feature] = value
    return checked


class SentinelAnomalyDetector:
    """Reçoit les mesures une par une et renvoie une alerte au début de
    chaque incident, None le reste du temps."""

    def __init__(self, model_path: str = MODEL_PATH) -> None:
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Modèle introuvable ({path}) : lance 'python anomaly_detector.py train mesures.csv'"
            )
        self.model = joblib.load(path)
        if self.model.get("features") != FEATURES:
            raise ValueError("Modèle obsolète : relance 'python anomaly_detector.py train mesures.csv'")
        self.history: deque[dict] = deque(maxlen=HISTORY_SIZE)
        self.in_incident = False
        self.calm_count = 0
        self.alert_count = 0
        self.last_score = None

    def process(self, telemetry: dict) -> dict | None:
        """telemetry : la trame JSON de sentinel/telemetry, déjà décodée en dict."""
        # Valider AVANT d'ajouter à l'historique : une mesure impossible (ValueError)
        # ne doit pas fausser les analyses des secondes suivantes
        self.history.append(check_metrics(telemetry["metrics"]))

        last = detect(pd.DataFrame(self.history), self.model).iloc[-1]
        self.last_score = round(float(last["score"]), 3)  # exposed for sentinel/scores

        if not last["alerte"]:
            if self.in_incident:
                self.calm_count += 1
                if self.calm_count > INCIDENT_GAP:
                    self.in_incident = False
            return None

        self.calm_count = 0
        if self.in_incident:
            return None  # incident déjà signalé : on n'inonde pas le dashboard
        self.in_incident = True
        return self._build_alert(telemetry, last)

    def _build_alert(self, telemetry: dict, last: pd.Series) -> dict:
        """Format du contrat d'interface, topic sentinel/alerts (§7.2)."""
        self.alert_count += 1
        sensor = last["capteur_en_cause"]
        return {
            "alert_id": f"ANO-2050-{self.alert_count:03d}",
            "timestamp": telemetry["timestamp"],
            "source": "IA_ANOMALY_ENGINE",
            "threat_level": "HIGH",
            "event_type": "SENSOR_ANOMALY",
            "details": {
                "device_id": telemetry.get("device_id"),
                "capteur_en_cause": sensor,
                "anomaly_score": round(float(last["score"]), 2),
                "metrics": {feature: telemetry["metrics"][feature] for feature in FEATURES},
            },
            "recommended_action": RECOMMENDED_ACTIONS[sensor],
        }