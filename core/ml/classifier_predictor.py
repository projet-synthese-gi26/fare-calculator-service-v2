import os
import json
import logging
import numpy as np
import math
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

class TaxiFareClassifierPredictor:
    """
    Service de prédiction de prix de taxi utilisant le RandomForestClassifier.
    Charge le modèle une seule fois au démarrage.
    """
    
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.models_dir = self.base_dir / 'models'
        
        self.is_ready = False
        self.model = None
        self.prix_classes = []
        
        self._load_resources()
        
    def _load_resources(self):
        """Charge le modèle et les classes de prix."""
        try:
            import joblib
            
            # 1. Charger le modèle
            model_path = self.models_dir / 'classifier_model.pkl'
            if model_path.exists():
                self.model = joblib.load(model_path)
                logger.info(f"Classifier chargé depuis {model_path}")
            else:
                logger.error(f"Modèle introuvable : {model_path}")
                return
            
            # 2. Charger les classes de prix
            classes_path = self.models_dir / 'prix_classes.json'
            if classes_path.exists():
                with open(classes_path, 'r') as f:
                    self.prix_classes = json.load(f)
                logger.info(f"Classes de prix chargées : {len(self.prix_classes)} classes")
            else:
                logger.warning(f"Fichier classes {classes_path} introuvable. Utilisation défaut.")
                self.prix_classes = [100, 150, 200, 250, 300, 350, 400, 450, 500, 
                                   600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000]
            
            self.is_ready = True
            logger.info("TaxiFareClassifierPredictor initialisé avec succès.")
            logger.info(f"  - Type modèle : {type(self.model).__name__}")
            logger.info(f"  - Features attendues : {self.model.n_features_in_}")
            logger.info(f"  - Classes : {len(self.prix_classes)}")
            
        except Exception as e:
            logger.error(f"Erreur initialisation TaxiFareClassifierPredictor: {e}")
            self.is_ready = False
    
    def _haversine_distance(self, lat1, lon1, lat2, lon2):
        """Calcule la distance à vol d'oiseau entre deux points GPS (en km)."""
        R = 6371  # Rayon de la Terre en km
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c
    
    def predict(self, 
                distance: float,
                heure: str,
                meteo: int,
                type_zone: int,
                coords_depart: List[float] = None,
                coords_arrivee: List[float] = None,
                duree: float = None,
                congestion: float = 50.0,
                sinuosite: float = None,
                nb_virages: int = None) -> Optional[int]:
        """
        Effectue une prédiction de prix avec le RandomForestClassifier.
        
        Args:
            distance: Distance en mètres (sera convertie en km)
            heure: 'matin', 'apres-midi', 'soir', 'nuit'
            meteo: 0-3 (0=soleil, 1=pluie légère, 2=pluie forte, 3=orage)
            type_zone: 0-2 (0=urbaine, 1=mixte, 2=rurale)
            coords_depart: [lat, lon] optionnel
            coords_arrivee: [lat, lon] optionnel
            duree: Durée en minutes (si None, sera estimée)
            congestion: Niveau congestion 0-100 (défaut 50)
            sinuosite: Indice sinuosité (si None, sera calculé)
            nb_virages: Nombre de virages (si None, sera estimé)
            
        Returns:
            int: Prix prédit (classe valide) ou None si erreur
        """
        if not self.is_ready:
            logger.warning("Classifier non prêt")
            return None
            
        try:
            # 1. Conversion distance en km
            dist_km = distance / 1000.0
            
            # 2. Coordonnées (fallback 0.0 si manquantes)
            lat_dep, lon_dep = coords_depart if coords_depart else (0.0, 0.0)
            lat_arr, lon_arr = coords_arrivee if coords_arrivee else (0.0, 0.0)
            
            # 3. Calcul sinuosité si manquante
            if sinuosite is None and coords_depart and coords_arrivee:
                dist_vol = self._haversine_distance(lat_dep, lon_dep, lat_arr, lon_arr)
                if dist_vol > 0:
                    sinuosite = dist_km / dist_vol
                    sinuosite = max(1.0, min(sinuosite, 3.0))  # Clip 1.0-3.0
                else:
                    sinuosite = 1.5
            elif sinuosite is None:
                sinuosite = 1.5
            
            # 4. Estimation nb_virages si manquant
            if nb_virages is None:
                nb_virages = int((dist_km * sinuosite) / 0.5)
                nb_virages = min(nb_virages, 100)
            
            # 5. Calcul force_virages
            if nb_virages > 0 and dist_km > 0:
                force_virages = (nb_virages * 90) / dist_km
                force_virages = min(force_virages, 500)
            else:
                force_virages = 0.0
            
            # 6. Durée si manquante (estimation 30 km/h)
            if duree is None:
                duree = (dist_km / 30) * 60
            
            # 7. Mapping heure vers periode_bin
            heure_map = {'matin': 0, 'apres-midi': 1, 'soir': 2, 'nuit': 3}
            periode_bin = heure_map.get(heure, 0) if heure else 0
            
            # 8. Construction vecteur features (13 features dans l'ordre)
            features = np.array([[
                lat_dep, lon_dep, lat_arr, lon_arr,
                dist_km, duree,
                sinuosite, nb_virages, force_virages,
                congestion,
                meteo if meteo is not None else 0,
                periode_bin,
                type_zone if type_zone is not None else 0
            ]])
            
            # 9. Prédiction
            classe_idx = self.model.predict(features)[0]
            
            # 10. Vérification index valide
            if classe_idx < 0 or classe_idx >= len(self.prix_classes):
                logger.error(f"Index classe invalide : {classe_idx}")
                return None
            
            # 11. Conversion index -> prix
            prix_predit = self.prix_classes[classe_idx]
            
            # 12. (Optionnel) Probabilités pour logging
            probas = self.model.predict_proba(features)[0]
            confiance = probas[classe_idx]
            
            logger.info(f"Classifier prédit : {prix_predit} FCFA (confiance {confiance*100:.1f}%)")
            logger.debug(f"  Features : dist={dist_km:.2f}km, sinuo={sinuosite:.2f}, virages={nb_virages}")
            
            return prix_predit
            
        except Exception as e:
            logger.error(f"Erreur lors de la prédiction Classifier : {e}")
            return None
