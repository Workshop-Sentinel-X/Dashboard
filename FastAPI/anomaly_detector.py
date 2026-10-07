"""
Sentinel-X - IA 2 : détection d'anomalies sur les capteurs.

Modèle non supervisé (Local Outlier Factor) : il mémorise ce qu'est un
fonctionnement "normal", puis signale toute mesure trop éloignée de ses
voisines normales. Pas besoin d'étiqueter les données, et aucun seuil fixe.

Pourquoi pas Isolation Forest : il ne place ses coupes qu'entre le minimum et
le maximum vus à l'entraînement, donc une valeur jamais vue (incendie à 30 °C)
reçoit le même score que la valeur normale la plus haute. LOF mesure une
distance : plus on s'éloigne du normal, plus c'est suspect.

Usage :
    python anomaly_detector.py demo                     # génère des données fictives et teste
    python anomaly_detector.py exemple                  # crée mesures.csv et nouvelles.csv de test
    python anomaly_detector.py train mesures.csv        # entraîne et sauvegarde le modèle
    python anomaly_detector.py detect nouvelles.csv     # détecte les anomalies
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Mêmes noms que le champ "metrics" du contrat d'interface (topic sentinel/telemetry).
# motion_detected vient du capteur d'obstacle infrarouge : 1 = objet à moins de ~20 cm.
FEATURES = ["temperature", "humidity", "motion_detected", "distance_cm"]
MODEL_PATH = "anomaly_model.joblib"

# Capteurs à valeur continue : on suit leur niveau ET leur tendance
CONTINUOUS = ["temperature", "humidity", "distance_cm"]

# Une mesure par seconde : la tendance compare à il y a 10 mesures (10 s)
TREND_WINDOW = 10
# Moyenne sur 3 mesures pour lisser le bruit avant de calculer la tendance
SMOOTH_WINDOW = 3

# Nombre de mesures normales voisines comparées à chaque nouvelle mesure
NEIGHBORS = 35
# Proportion de mesures d'entraînement qu'on accepte de juger anormales (1 %)
CONTAMINATION = 0.01

# Une alerte n'est levée qu'après 3 mesures anormales de suite (3 s) :
# un capteur qui "tousse" une seule fois ne déclenche rien
CONFIRMATION = 3
# Moins de 10 s de calme entre deux alertes = toujours le même incident.
# Même durée que la tendance : le retour à la normale fait lui aussi bouger
# la tendance pendant 10 s, ce n'est pas un nouvel incident
INCIDENT_GAP = TREND_WINDOW


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute ce que l'IA doit voir en plus des valeurs brutes :
    - la tendance sur 10 s : un incendie monte de +3 °C en 10 s, alors que le
      bruit du capteur fait à peine 0,1 °C ; seconde par seconde, on ne voit rien
    - le capteur IR moyenné sur 3 s : un déclenchement isolé par erreur pèse peu,
      un objet qui reste devant le boîtier pèse beaucoup"""
    out = df.copy()
    for col in CONTINUOUS:
        smooth = out[col].rolling(SMOOTH_WINDOW, min_periods=1).mean()
        out[f"{col}_tendance"] = (smooth - smooth.shift(TREND_WINDOW)).fillna(0)
    out["motion_persistant"] = out["motion_detected"].rolling(SMOOTH_WINDOW, min_periods=1).mean()
    return out


def feature_columns() -> list[str]:
    return [*CONTINUOUS, *[f"{c}_tendance" for c in CONTINUOUS], "motion_persistant"]


def train(df: pd.DataFrame) -> dict:
    """L'entraînement mémorise les mesures normales (après mise à l'échelle)."""
    data = add_features(df)
    detector = Pipeline([
        ("scaler", StandardScaler()),
        ("lof", LocalOutlierFactor(
            n_neighbors=NEIGHBORS,
            contamination=CONTAMINATION,
            novelty=True,  # obligatoire pour juger de NOUVELLES mesures
        )),
    ])
    detector.fit(data[feature_columns()])
    model = {"detector": detector, "features": FEATURES}
    joblib.dump(model, MODEL_PATH)
    print(f"Modèle entraîné sur {len(df)} mesures -> {MODEL_PATH}")
    return model


def detect(df: pd.DataFrame, model: dict | None = None) -> pd.DataFrame:
    """Seule l'IA décide. La colonne capteur_en_cause n'est qu'une explication
    pour l'opérateur : la variable la plus éloignée de son comportement normal."""
    if model is None:
        model = joblib.load(MODEL_PATH)
    detector = model["detector"]
    X = add_features(df)[feature_columns()]
    result = df.copy()

    # score < 0 = anormal ; plus il est bas, plus la mesure est loin du normal
    result["score"] = detector.decision_function(X)
    result["anomalie"] = detector.predict(X) == -1

    ecarts = pd.DataFrame(
        np.abs(detector.named_steps["scaler"].transform(X)), columns=X.columns, index=X.index
    )
    en_cause = ecarts.idxmax(axis=1).str.replace("_tendance", "").str.replace("_persistant", "_detected")
    result["capteur_en_cause"] = en_cause.where(result["anomalie"], "")

    # Alerte confirmée : cette mesure ET les 2 précédentes sont anormales
    suite = result["anomalie"].astype(int).rolling(CONFIRMATION).sum()
    result["alerte"] = suite == CONFIRMATION
    return result


def incidents(result: pd.DataFrame) -> pd.DataFrame:
    """Regroupe les alertes confirmées en incidents : le dashboard reçoit une
    seule alerte par incident, au lieu d'une par seconde."""
    alertes = result[result["alerte"]]
    if alertes.empty:
        return pd.DataFrame(columns=["debut", "fin", "nb_alertes", "capteur_en_cause", "score_min"])
    # Un nouvel incident commence quand plus de INCIDENT_GAP mesures séparent deux alertes
    numero = (alertes.index.to_series().diff() > INCIDENT_GAP).cumsum()
    return pd.DataFrame([
        {
            "debut": groupe["timestamp"].iloc[0],
            "fin": groupe["timestamp"].iloc[-1],
            "nb_alertes": len(groupe),
            "capteur_en_cause": groupe["capteur_en_cause"].mode().iloc[0],
            "score_min": groupe["score"].min(),
        }
        for _, groupe in alertes.groupby(numero)
    ])


def generate_demo_data(n: int = 1800, seed: int = 0) -> pd.DataFrame:
    """Imite le boîtier au repos : une mesure par seconde pendant 30 minutes."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-10-01", periods=n, freq="s"),
        "temperature": 22 + rng.normal(0, 0.1, n),
        "humidity": 45 + rng.normal(0, 0.5, n),
        # Le capteur IR se déclenche très rarement par erreur (0,2 % du temps)
        "motion_detected": (rng.random(n) < 0.002).astype(int),
        # Distance jusqu'au mur en face du boîtier
        "distance_cm": 150 + rng.normal(0, 1, n),
    })
    return df


def inject_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Les 3 scénarios de la démo, placés loin les uns des autres."""
    df = df.copy()

    # 1. Approche suspecte : quelqu'un avance de 150 cm à 10 cm en 11 secondes,
    #    le capteur IR passe à 1 dès qu'il est à moins de 20 cm
    df.loc[500:510, "distance_cm"] = np.linspace(150, 10, 11)
    df.loc[500:510, "motion_detected"] = (df.loc[500:510, "distance_cm"] < 20).astype(int)

    # 2. Échauffement : +0,3 °C par seconde pendant 30 secondes (début d'incendie)
    df.loc[1000:1029, "temperature"] = 22 + 0.3 * np.arange(30)

    # 3. Capteur qui décroche : le DHT22 renvoie 0 % d'humidité pendant 5 secondes
    df.loc[1500:1504, "humidity"] = 0
    return df


def load_csv(path: str) -> pd.DataFrame | None:
    if not Path(path).exists():
        print(f"Fichier introuvable : {path}")
        print("Lance d'abord 'python anomaly_detector.py exemple' pour créer des fichiers de test,")
        print("ou place ici un CSV avec les colonnes : timestamp, " + ", ".join(FEATURES))
        return None
    df = pd.read_csv(path)
    missing = [c for c in FEATURES if c not in df.columns]
    if missing:
        print(f"Colonnes manquantes dans {path} : {', '.join(missing)}")
        print(f"Colonnes trouvées : {', '.join(df.columns)}")
        print("Adapte la liste FEATURES en haut du script.")
        return None
    return df


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "demo":
        normal = generate_demo_data()
        model = train(normal)
        test = inject_anomalies(generate_demo_data(seed=1))
        result = detect(test, model)
        print(f"\nMesures analysées          : {len(result)}")
        print(f"Mesures jugées anormales   : {result['anomalie'].sum()}")
        print(f"Dont alertes confirmées    : {result['alerte'].sum()} (au moins {CONFIRMATION} de suite)")
        found = incidents(result)
        print(f"\n{len(found)} incident(s) envoyé(s) au dashboard :\n")
        print(found.to_string(index=False, float_format="%.2f"))

    elif command == "exemple":
        generate_demo_data().to_csv("mesures.csv", index=False)
        inject_anomalies(generate_demo_data(seed=1)).to_csv("nouvelles.csv", index=False)
        print("Fichiers créés : mesures.csv (normal) et nouvelles.csv (avec pannes)")

    elif command == "train" and len(sys.argv) == 3:
        df = load_csv(sys.argv[2])
        if df is not None:
            train(df)

    elif command == "detect" and len(sys.argv) == 3:
        df = load_csv(sys.argv[2])
        if df is None:
            return
        if not Path(MODEL_PATH).exists():
            print(f"Modèle introuvable : lance d'abord la commande train.")
            return
        result = detect(df)
        result.to_csv("resultats_anomalies.csv", index=False)
        print(f"{len(incidents(result))} incident(s) -> resultats_anomalies.csv")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()