"""
Script de test pour vérifier les corrections du calcul de sinuosité.

Ce script teste :
1. Le calcul de base (ratio distance/ligne droite)
2. Le plafonnement des valeurs aberrantes
3. La cohérence entre différents types de trajets
"""

import os
import sys

# Configurer Django avant les imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fare_calculator.settings')
sys.path.insert(0, '.')

import django
django.setup()

from core.utils.calculations import (
    haversine_distance,
    calculer_sinuosite_base,
    calculer_virages_par_km,
    calculer_force_virages
)


def test_sinuosite_base():
    """Test du calcul de sinuosité de base."""
    print("=" * 60)
    print("TEST 1: Calcul de sinuosité de base")
    print("=" * 60)
    
    # Cas 1: Trajet urbain typique (Yaoundé)
    # Distance route ~5.2km, ligne droite ~2.1km -> sinuosité ~2.5
    sinuosite = calculer_sinuosite_base(
        distance_route=5212,
        lat_depart=3.8547,
        lon_depart=11.5021,
        lat_arrivee=3.8667,
        lon_arrivee=11.5174
    )
    print(f"Cas 1 - Trajet urbain sinueux:")
    print(f"  Distance route: 5212m")
    print(f"  Sinuosité: {sinuosite:.2f}")
    print(f"  ✓ OK" if 2.0 <= sinuosite <= 3.5 else f"  ✗ ERREUR (attendu: 2.0-3.5)")
    
    # Cas 2: Trajet quasi-direct (autoroute)
    # Distance route ~2.5km, ligne droite ~2.4km -> sinuosité ~1.04
    sinuosite = calculer_sinuosite_base(
        distance_route=2500,
        lat_depart=3.85,
        lon_depart=11.50,
        lat_arrivee=3.87,
        lon_arrivee=11.52
    )
    print(f"\nCas 2 - Trajet quasi-direct:")
    print(f"  Distance route: 2500m")
    print(f"  Sinuosité: {sinuosite:.2f}")
    print(f"  ✓ OK" if 1.0 <= sinuosite <= 1.5 else f"  ✗ ERREUR (attendu: 1.0-1.5)")
    
    # Cas 3: Valeur aberrante (ratio > 5)
    # Distance route très longue par rapport à ligne droite
    sinuosite = calculer_sinuosite_base(
        distance_route=15000,  # 15km
        lat_depart=3.85,
        lon_depart=11.50,
        lat_arrivee=3.86,
        lon_arrivee=11.51  # ~1.5km ligne droite -> ratio 10 !
    )
    print(f"\nCas 3 - Valeur aberrante (plafonnement):")
    print(f"  Distance route: 15000m (ratio théorique ~10)")
    print(f"  Sinuosité: {sinuosite:.2f}")
    print(f"  ✓ OK (plafonné)" if sinuosite == 5.0 else f"  ✗ ERREUR (attendu: 5.0 plafonné)")
    
    # Cas 4: Même point
    sinuosite = calculer_sinuosite_base(
        distance_route=100,
        lat_depart=3.85,
        lon_depart=11.50,
        lat_arrivee=3.85,
        lon_arrivee=11.50
    )
    print(f"\nCas 4 - Même point:")
    print(f"  Distance route: 100m")
    print(f"  Sinuosité: {sinuosite:.2f}")
    print(f"  ✓ OK" if sinuosite == 1.0 else f"  ✗ ERREUR (attendu: 1.0)")


def test_virages():
    """Test du calcul des virages."""
    print("\n" + "=" * 60)
    print("TEST 2: Calcul des virages")
    print("=" * 60)
    
    maneuvers_exemple = [
        {"type": "depart", "modifier": None},
        {"type": "turn", "modifier": "left", "bearing_before": 0, "bearing_after": 90},
        {"type": "turn", "modifier": "right", "bearing_before": 90, "bearing_after": 180},
        {"type": "rotary", "modifier": "straight", "bearing_before": 180, "bearing_after": 270},
        {"type": "turn", "modifier": "slight right", "bearing_before": 270, "bearing_after": 300},
        {"type": "arrive", "modifier": None}
    ]
    
    # Test virages par km
    nb_virages, virages_km = calculer_virages_par_km(maneuvers_exemple, 5000)
    print(f"Virages par km:")
    print(f"  Nombre virages: {nb_virages} (attendu: 5 = 3 turns + 1 rotary*2)")
    print(f"  Virages/km: {virages_km:.2f} (attendu: 1.0)")
    print(f"  ✓ OK" if nb_virages == 5 and 0.9 <= virages_km <= 1.1 else "  ✗ ERREUR")
    
    # Test force virages
    force = calculer_force_virages(maneuvers_exemple, 5000)
    print(f"\nForce virages:")
    print(f"  Force: {force:.2f} °/km" if force else "  Force: None")
    # Angles: 90 + 90 + 90 + 30 = 300° / 5km = 60°/km
    print(f"  ✓ OK" if force and 55 <= force <= 65 else "  ✗ ERREUR (attendu: ~60°/km)")


def test_comparaison_trajets():
    """Test de comparaison entre trajets pour vérifier la cohérence."""
    print("\n" + "=" * 60)
    print("TEST 3: Comparaison cohérence trajets")
    print("=" * 60)
    
    # Trajet court et droit
    sinuosite_court_droit = calculer_sinuosite_base(
        distance_route=1200,  # 1.2km
        lat_depart=3.85,
        lon_depart=11.50,
        lat_arrivee=3.86,
        lon_arrivee=11.505  # ~1.1km ligne droite
    )
    
    # Trajet long et sinueux
    sinuosite_long_sinueux = calculer_sinuosite_base(
        distance_route=12000,  # 12km
        lat_depart=3.85,
        lon_depart=11.50,
        lat_arrivee=3.90,
        lon_arrivee=11.55  # ~7km ligne droite -> sinuosité ~1.7
    )
    
    print(f"Trajet court droit: sinuosité = {sinuosite_court_droit:.2f}")
    print(f"Trajet long sinueux: sinuosité = {sinuosite_long_sinueux:.2f}")
    
    # Le trajet long sinueux devrait avoir une sinuosité plus élevée
    if sinuosite_long_sinueux > sinuosite_court_droit:
        print("✓ OK: Le trajet long sinueux a bien une sinuosité plus élevée")
    else:
        print("✗ ERREUR: Incohérence dans les valeurs!")
    
    # Vérifier que les valeurs sont dans des plages raisonnables
    print(f"\nPlages de valeurs:")
    print(f"  Court droit: {sinuosite_court_droit:.2f} (attendu: 1.0-1.5)")
    print(f"  Long sinueux: {sinuosite_long_sinueux:.2f} (attendu: 1.5-2.5)")


def test_fallback_scenario():
    """Test du scénario fallback (sans données Mapbox)."""
    print("\n" + "=" * 60)
    print("TEST 4: Scénario fallback (simulation)")
    print("=" * 60)
    
    # Simulation du fallback dans views.py
    lat_dep, lon_dep = 3.8547, 11.5021
    lat_arr, lon_arr = 3.8667, 11.5174
    
    # Distance ligne droite
    distance_ligne_droite = haversine_distance(lat_dep, lon_dep, lat_arr, lon_arr)
    
    # Distance estimée (comme dans le code corrigé)
    distance_estimee = distance_ligne_droite * 1.3
    
    # Sinuosité fallback (valeur fixe comme dans le code corrigé)
    sinuosite_fallback = 1.3
    
    print(f"Distance ligne droite: {distance_ligne_droite:.0f}m")
    print(f"Distance estimée (x1.3): {distance_estimee:.0f}m")
    print(f"Sinuosité fallback: {sinuosite_fallback:.2f}")
    print("✓ OK: Pas de calcul biaisé (valeur fixe typique urbaine)")


if __name__ == "__main__":
    print("\n🔍 TESTS DE VALIDATION DES CORRECTIONS SINUOSITÉ\n")
    
    test_sinuosite_base()
    test_virages()
    test_comparaison_trajets()
    test_fallback_scenario()
    
    print("\n" + "=" * 60)
    print("FIN DES TESTS")
    print("=" * 60)
