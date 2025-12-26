"""
Package utils pour intégrations externes et calculs.

Modules :
- calculations : Calculs géographiques (Haversine, sinuosité, tranches horaires)
- mapbox_client : Intégration Mapbox APIs (Directions, Matrix, Isochrone, Search, Map Matching)
- nominatim : Geocoding Nominatim (fallback gratuit)
- openmeteo : Météo OpenMeteo (fallback météo automatique)

Exports :
    Fonctions calculs les plus utilisées
    Clients API (instances singletons)
"""

# Calculs géographiques
from .calculations import (
    haversine_distance,
    calculer_sinuosite_base,
    calculer_virages_par_km,
    calculer_force_virages,
    determiner_tranche_horaire,
    normaliser_angle_virage,
    convertir_meteo_code_vers_label,
    convertir_type_zone_vers_label
)

# Clients API
from .mapbox_client import mapbox_client, MapboxClient
from .nominatim import nominatim_client, NominatimClient
from .openmeteo import openmeteo_client, OpenMeteoClient

__all__ = [
    # Fonctions calculs
    'haversine_distance',
    'calculer_sinuosite_base',
    'calculer_virages_par_km',
    'calculer_force_virages',
    'determiner_tranche_horaire',
    'normaliser_angle_virage',
    'convertir_meteo_code_vers_label',
    'convertir_type_zone_vers_label',
    
    # Clients API (instances)
    'mapbox_client',
    'nominatim_client',
    'openmeteo_client',
    
    # Classes (pour instanciation custom si nécessaire)
    'MapboxClient',
    'NominatimClient',
    'OpenMeteoClient'
]
