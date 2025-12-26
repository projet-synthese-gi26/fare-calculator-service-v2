#!/usr/bin/env python3
"""
Script d'exemple pour utiliser le modèle classifier_model.pkl
"""
import joblib
import json
import numpy as np
import math
import sys
import os

# Ajouter le chemin du projet
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# === FONCTIONS UTILITAIRES ===

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calcule la distance à vol d'oiseau entre deux points GPS (en km)"""
    R = 6371  # Rayon de la Terre en km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def calculer_features(depart_lat, depart_lon, arrivee_lat, arrivee_lon,
                     distance_km, duree_min=None,
                     meteo='soleil', periode='matin', zone='urbaine',
                     congestion=50.0):
    """
    Calcule les 13 features à partir des données de base
    
    Args:
        depart_lat, depart_lon: Coordonnées GPS départ
        arrivee_lat, arrivee_lon: Coordonnées GPS arrivée
        distance_km: Distance routière en km
        duree_min: Durée en minutes (optionnel, sera estimé si None)
        meteo: 'soleil', 'pluie_legere', 'pluie_forte', 'orage'
        periode: 'matin', 'apres-midi', 'soir', 'nuit'
        zone: 'urbaine', 'mixte', 'rurale'
        congestion: Niveau de congestion 0-100
    
    Returns:
        Liste de 13 features dans l'ordre requis
    """
    
    # 1. Sinuosité
    dist_vol = haversine_distance(depart_lat, depart_lon, arrivee_lat, arrivee_lon)
    sinuosite = distance_km / dist_vol if dist_vol > 0 else 1.0
    sinuosite = max(1.0, min(sinuosite, 3.0))  # Clip entre 1.0 et 3.0
    
    # 2. Virages
    nb_virages = int((distance_km * sinuosite) / 0.5)
    nb_virages = min(nb_virages, 100)  # Max 100 virages
    
    # 3. Force des virages
    force_virages = (nb_virages * 90) / distance_km if nb_virages > 0 and distance_km > 0 else 0.0
    force_virages = min(force_virages, 500)  # Clip max 500
    
    # 4. Durée si manquante (estimation 30 km/h)
    if duree_min is None:
        duree_min = (distance_km / 30) * 60
    
    # 5. Codes binaires
    meteo_map = {'soleil': 0, 'pluie_legere': 1, 'pluie_forte': 2, 'orage': 3}
    periode_map = {'matin': 0, 'apres-midi': 1, 'soir': 2, 'nuit': 3}
    zone_map = {'urbaine': 0, 'mixte': 1, 'rurale': 2}
    
    return [
        depart_lat, depart_lon, arrivee_lat, arrivee_lon,
        distance_km, duree_min,
        sinuosite, nb_virages, force_virages,
        congestion,
        meteo_map.get(meteo, 0),
        periode_map.get(periode, 0),
        zone_map.get(zone, 0)
    ]

# === CHARGEMENT MODÈLE ===

print("Chargement du modèle...")
try:
    model = joblib.load('core/ml/models/classifier_model.pkl')
    with open('core/ml/models/prix_classes.json', 'r') as f:
        PRIX_CLASSES = json.load(f)
    
    print("✅ Modèle chargé avec succès !")
    print(f"   - Type : {type(model).__name__}")
    print(f"   - Features attendues : {model.n_features_in_}")
    print(f"   - Classes : {len(PRIX_CLASSES)} tranches de prix\n")
except Exception as e:
    print(f"❌ Erreur lors du chargement : {e}")
    sys.exit(1)

# === FONCTION DE PRÉDICTION ===

def predire_prix(depart_lat, depart_lon, arrivee_lat, arrivee_lon,
                distance_km, duree_min=None,
                meteo='soleil', periode='matin', zone='urbaine',
                congestion=50.0, verbose=True):
    """
    Prédit le prix d'un trajet
    
    Returns:
        dict avec 'prix_predit', 'confiance', 'top_3'
    """
    # Calculer les features
    features = calculer_features(
        depart_lat, depart_lon, arrivee_lat, arrivee_lon,
        distance_km, duree_min, meteo, periode, zone, congestion
    )
    
    if verbose:
        print(f"Features calculées : {len(features)} features")
        print(f"  Sinuosité : {features[6]:.2f}")
        print(f"  Nb virages : {features[7]}")
        print(f"  Force virages : {features[8]:.2f}")
    
    # Prédire
    X = np.array([features])
    classe_idx = model.predict(X)[0]
    probas = model.predict_proba(X)[0]
    
    # Prix prédit
    prix_predit = PRIX_CLASSES[classe_idx]
    confiance = probas[classe_idx]
    
    # Top 3
    top_3_idx = np.argsort(probas)[-3:][::-1]
    top_3 = [
        {
            'prix': PRIX_CLASSES[idx],
            'probabilite': float(probas[idx])
        }
        for idx in top_3_idx
    ]
    
    return {
        'prix_predit': prix_predit,
        'confiance': float(confiance),
        'top_3': top_3
    }

# === TESTS ===

print("=" * 70)
print("TEST 1 : Trajet court (Polytech → Kennedy, matin, soleil)")
print("=" * 70)

result = predire_prix(
    depart_lat=3.848,
    depart_lon=11.502,
    arrivee_lat=3.867,
    arrivee_lon=11.521,
    distance_km=8.6,
    duree_min=8.7,
    meteo='soleil',
    periode='matin',
    zone='urbaine',
    congestion=20.0
)

print(f"\n🎯 Prix prédit : {result['prix_predit']} FCFA")
print(f"   Confiance : {result['confiance']*100:.1f}%")
print("\n📊 Top 3 prédictions :")
for i, pred in enumerate(result['top_3'], 1):
    print(f"   {i}. {pred['prix']} FCFA : {pred['probabilite']*100:.1f}%")

print("\n" + "=" * 70)
print("TEST 2 : Trajet moyen (Centre-ville → Aéroport, nuit, pluie)")
print("=" * 70)

result = predire_prix(
    depart_lat=3.8667,
    depart_lon=11.5174,
    arrivee_lat=3.7233,
    arrivee_lon=11.5514,
    distance_km=18.5,
    meteo='pluie_legere',
    periode='nuit',
    zone='mixte',
    congestion=35.0
)

print(f"\n🎯 Prix prédit : {result['prix_predit']} FCFA")
print(f"   Confiance : {result['confiance']*100:.1f}%")
print("\n📊 Top 3 prédictions :")
for i, pred in enumerate(result['top_3'], 1):
    print(f"   {i}. {pred['prix']} FCFA : {pred['probabilite']*100:.1f}%")

print("\n" + "=" * 70)
print("TEST 3 : Trajet personnalisé")
print("=" * 70)

# Vous pouvez modifier ces valeurs
result = predire_prix(
    depart_lat=3.85,
    depart_lon=11.50,
    arrivee_lat=3.88,
    arrivee_lon=11.53,
    distance_km=12.0,
    duree_min=15.0,
    meteo='soleil',
    periode='apres-midi',
    zone='urbaine',
    congestion=60.0
)

print(f"\n🎯 Prix prédit : {result['prix_predit']} FCFA")
print(f"   Confiance : {result['confiance']*100:.1f}%")
print("\n📊 Top 3 prédictions :")
for i, pred in enumerate(result['top_3'], 1):
    print(f"   {i}. {pred['prix']} FCFA : {pred['probabilite']*100:.1f}%")

print("\n" + "=" * 70)
print("✅ Tests terminés !")
print("=" * 70)
