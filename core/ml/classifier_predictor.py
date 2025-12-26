import json
import logging
import math
from pathlib import Path
from typing import Optional, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ✅ IMPORT RELATIF PROPRE
from .features import WeightedStandardScaler


class TaxiFareClassifierPredictor:
    """
    Service de prédiction de prix de taxi utilisant un RandomForestClassifier.
    Le modèle est chargé une seule fois au démarrage.
    """

    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.models_dir = self.base_dir / "models"

        self.is_ready = False
        self.model = None
        self.prix_classes = []

        self._load_resources()

    def _load_resources(self):
        """Charge le modèle et les classes de prix."""
        try:
            import joblib

            model_path = self.models_dir / "classifier_model.pkl"
            if not model_path.exists():
                logger.error(f"Modèle introuvable : {model_path}")
                return

            self.model = joblib.load(model_path)
            logger.info(f"Classifier chargé depuis {model_path}")

            classes_path = self.models_dir / "prix_classes.json"
            if classes_path.exists():
                with open(classes_path, "r") as f:
                    self.prix_classes = json.load(f)
            else:
                logger.warning("Classes manquantes → valeurs par défaut")
                self.prix_classes = [
                    100, 150, 200, 250, 300, 350, 400, 450,
                    500, 600, 700, 800, 900, 1000, 1200,
                    1500, 1700, 2000
                ]

            self.is_ready = True
            logger.info("TaxiFareClassifierPredictor prêt")
            logger.info(f"  - Modèle : {type(self.model).__name__}")
            logger.info(f"  - Classes : {len(self.prix_classes)}")

        except Exception as e:
            logger.exception("Erreur lors du chargement du modèle")
            self.is_ready = False

    @staticmethod
    def _haversine_distance(lat1, lon1, lat2, lon2) -> float:
        """Distance GPS en km."""
        R = 6371
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 2 * R * math.asin(math.sqrt(a))

    def predict(
        self,
        distance: float,
        heure: str,
        meteo: int,
        type_zone: int,
        coords_depart: List[float] = None,
        coords_arrivee: List[float] = None,
        duree: float = None,
        congestion: float = 50.0,
        sinuosite: float = None,
        nb_virages: int = None,
        qualite_trajet: int = None,
    ) -> Optional[int]:

        if not self.is_ready:
            logger.warning("Classifier non prêt")
            return None

        try:
            # --- Bases ---
            dist_km = distance / 1000
            lat_dep, lon_dep = coords_depart or (0.0, 0.0)
            lat_arr, lon_arr = coords_arrivee or (0.0, 0.0)

            dist_vol = self._haversine_distance(lat_dep, lon_dep, lat_arr, lon_arr)

            if duree is None:
                duree = (dist_km / 30) * 60 if dist_km > 0 else 1

            vitesse_kmh = dist_km / (duree / 60)
            vitesse_kmh = max(5, min(vitesse_kmh, 100))

            sinuosite_reelle = (
                max(1.0, min(dist_km / dist_vol, 3.0)) if dist_vol > 0 else 1.5
            )

            if nb_virages is None:
                nb_virages = min(int(dist_km * 2), 100)

            force_virages = (
                min((nb_virages * 90) / dist_km, 500) if dist_km > 0 else 0
            )

            heure_map = {"matin": 0, "apres-midi": 1, "soir": 2, "nuit": 3}
            periode_bin = heure_map.get(heure, 0)

            parametre_culture = qualite_trajet or 5

            # --- Features DataFrame ---
            features = pd.DataFrame([{
                "distance_km": dist_km,
                "duree_min": duree,
                "distance_vol_oiseau": dist_vol,
                "sinuosite_reelle": sinuosite_reelle,
                "vitesse_kmh": vitesse_kmh,
                "congestion_moyen": congestion,
                "meteo_bin": meteo or 0,
                "periode_bin": periode_bin,
                "zone_bin": type_zone or 0,
                "parametre_culture": parametre_culture,
                "sinuosite_indice": sinuosite or sinuosite_reelle,
                "nb_virages": nb_virages,
                "force_virages": force_virages,
            }])

            classe_idx = self.model.predict(features)[0]

            if not 0 <= classe_idx < len(self.prix_classes):
                logger.error(f"Index classe invalide : {classe_idx}")
                return None

            prix = self.prix_classes[classe_idx]
            confiance = self.model.predict_proba(features)[0][classe_idx]

            logger.info(
                f"Prix prédit : {prix} FCFA "
                f"(confiance {confiance * 100:.1f}%)"
            )

            return prix

        except Exception:
            logger.exception("Erreur lors de la prédiction")
            return None
