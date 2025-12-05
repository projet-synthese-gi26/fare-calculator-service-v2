import os
import django
import sys

# Configuration Django
sys.path.append('/home/gates/Documents/Niveau5/GesTrafic/fare-calculator-service-v2')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fare_calculator.settings')
django.setup()

from core.apps import taxi_predictor

print("--- Test Intégration ML ---")

if taxi_predictor and taxi_predictor.is_ready:
    print("✅ TaxiFarePredictor chargé et prêt.")
    
    # Test prédiction
    prix = taxi_predictor.predict(
        distance=5000,
        heure='matin',
        meteo=0,
        type_zone=0,
        congestion=20.0,
        sinuosite=1.2,
        nb_virages=5
    )
    
    if prix:
        print(f"✅ Prédiction réussie : {prix} CFA")
    else:
        print("❌ Prédiction a retourné None")
else:
    print("❌ TaxiFarePredictor non prêt ou non chargé.")
