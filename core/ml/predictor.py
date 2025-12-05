import os
import json
import logging
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any

# Import des modules ML existants
try:
    from .prediction_taxi_numpy import predict_knn, charger_donnees
    from .calculate_weights_taxi import get_optimal_weights
    NUMPY_AVAILABLE = True
except ImportError:
    # Fallback si numpy n'est pas dispo (bien que requis par le projet)
    from .prediction_taxi import (
        selection_trajets_a_utiliser, 
        calcul_prix_et_incertitude, 
        standardiser_donnees,
        charger_donnees_taxi as charger_donnees,
        get_optimal_weights
    )
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)

class TaxiFarePredictor:
    """
    Service de prédiction de prix de taxi utilisant l'implémentation KNN existante.
    Charge les données et le modèle une seule fois au démarrage.
    """
    
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.models_dir = self.base_dir / 'models'
        self.csv_path = self.base_dir.parent.parent / 'trajets_taxi.csv'  # À la racine du projet ou ailleurs?
        # Vérifions où est le CSV. S'il n'est pas là, on utilisera un chemin relatif
        if not self.csv_path.exists():
             # Fallback: chercher dans core/ml si présent
             self.csv_path = self.base_dir / 'trajets_taxi.csv'
        
        self.is_ready = False
        self.X_train = None
        self.Y_train = None
        self.weights = None
        self.prix_classes = []
        
        self._load_resources()
        
    def _load_resources(self):
        """Charge les ressources nécessaires (CSV, poids, classes)."""
        try:
            # 1. Charger les classes de prix
            classes_path = self.models_dir / 'prix_classes.json'
            if classes_path.exists():
                with open(classes_path, 'r') as f:
                    self.prix_classes = json.load(f)
            else:
                logger.warning(f"Fichier classes {classes_path} introuvable. Utilisation défaut.")
                self.prix_classes = [100, 150, 200, 250, 300, 350, 400, 450, 500, 
                                   600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000]

            # 2. Charger les données d'entraînement
            if self.csv_path.exists():
                logger.info(f"Chargement données ML depuis {self.csv_path}")
                self.X_train, self.Y_train = charger_donnees(str(self.csv_path))
                
                if self.X_train is not None and len(self.X_train) > 0:
                    # 3. Calculer/Charger les poids
                    logger.info("Calcul des poids optimaux ML...")
                    self.weights = get_optimal_weights(str(self.csv_path))
                    self.is_ready = True
                    logger.info("TaxiFarePredictor initialisé avec succès.")
                else:
                    logger.error("Données d'entraînement vides ou invalides.")
            else:
                logger.warning(f"Fichier CSV {self.csv_path} introuvable. ML désactivé.")
                
        except Exception as e:
            logger.error(f"Erreur initialisation TaxiFarePredictor: {e}")
            self.is_ready = False

    def predict(self, 
                distance: float, 
                heure: str, 
                meteo: int, 
                type_zone: int, 
                congestion: float = 50.0, 
                sinuosite: float = 1.5, 
                nb_virages: int = 0,
                coords_depart: List[float] = None,
                coords_arrivee: List[float] = None,
                duree: float = 0.0) -> Optional[int]:
        """
        Effectue une prédiction de prix.
        
        Args:
            distance: Distance en mètres (sera convertie en km)
            heure: 'matin', 'apres-midi', 'soir', 'nuit'
            meteo: 0-3
            type_zone: 0-2
            congestion: 0-100
            sinuosite: >= 1.0
            nb_virages: int
            coords_depart: [lat, lon]
            coords_arrivee: [lat, lon]
            duree: Durée en minutes (si 0, estimée via distance)
            
        Returns:
            int: Prix prédit (classe valide) ou None si erreur/non prêt
        """
        if not self.is_ready:
            return None
            
        try:
            # 1. Préparation des features (15 dimensions)
            # Mapping heure
            heure_map = {'matin': 0, 'apres-midi': 1, 'soir': 2, 'nuit': 3}
            heure_encoded = heure_map.get(heure, 0)
            
            # Coordonnées (fallback 0.0 si manquantes)
            lat_dep, lon_dep = coords_depart if coords_depart else (0.0, 0.0)
            lat_arr, lon_arr = coords_arrivee if coords_arrivee else (0.0, 0.0)
            
            # Conversions
            dist_km = distance / 1000.0
            duree_min = duree if duree > 0 else (dist_km * 3) # Estimation grossière 20km/h
            
            # Features dérivées (simplifiées pour l'instant)
            force_virages = (nb_virages * 90) / dist_km if dist_km > 0 else 0
            
            # Construction vecteur features (ordre important !)
            # 0:lat_dep, 1:lon_dep, 2:lat_arr, 3:lon_arr (indices CSV: 0,1,3,4)
            # 4:dist, 5:duree (indices CSV: 7,8)
            # 6:sin, 7:nb_vir, 8:force (indices CSV: 9,10,11)
            # 9:congestion (index CSV: 12)
            # 10:meteo, 11:periode, 12:zone (indices CSV: 13,14,15)
            
            features = [
                lat_dep, lon_dep, lat_arr, lon_arr,
                dist_km, duree_min,
                sinuosite, nb_virages, force_virages,
                congestion,
                meteo, # Meteo bin
                0, # Periode bin (TODO: calculer depuis heure)
                type_zone # Zone bin
            ]
            
            # 2. Prédiction
            if NUMPY_AVAILABLE:
                X_new = np.array(features)
                prix_estimes, confiances = predict_knn(
                    self.X_train, self.Y_train, 
                    X_new, self.weights, k=5
                )
                prix_brut = prix_estimes[0]
            else:
                # Fallback Python pur (à implémenter si besoin, mais numpy est là)
                return None
                
            # 3. Arrondi vers classe valide
            classe_proche = min(self.prix_classes, key=lambda x: abs(x - prix_brut))
            
            logger.info(f"Prédiction ML: {prix_brut:.2f} -> Classe {classe_proche} (Confiance: {confiances[0]:.1f}%)")
            return classe_proche
            
        except Exception as e:
            logger.error(f"Erreur lors de la prédiction: {e}")
            return None
