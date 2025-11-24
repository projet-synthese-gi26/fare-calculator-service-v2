"""
Client pour intégration Nominatim (OpenStreetMap Geocoding) - alternative gratuite.

Utilisé pour :
- Conversion nom/adresse -> coordonnées (si user entre "Carrefour Ekounou" sans coords)
- Fallback si Mapbox Search indisponible ou quota dépassé
- Validation coords (reverse geocoding pour vérifier si coords sont au Cameroun)

Configuration requise dans settings.py :
    NOMINATIM_BASE_URL : https://nominatim.openstreetmap.org
    NOMINATIM_USER_AGENT : taxi-estimator-cameroun/1.0 (OBLIGATOIRE selon TOS Nominatim)

IMPORTANT : Nominatim a rate limit strict (1 requête/seconde gratuit).
Utiliser caching agressif et batch si possible.
"""

import requests
import logging
import time
from typing import Dict, List, Optional
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class NominatimClient:
    """
    Client pour Nominatim geocoding avec respect rate limits.
    
    Usage :
        client = NominatimClient()
        coords = client.search_place("Carrefour Ekounou, Yaoundé, Cameroun")
        if coords:
            lat, lon = coords
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'NOMINATIM_BASE_URL', 'https://nominatim.openstreetmap.org')
        self.user_agent = getattr(settings, 'NOMINATIM_USER_AGENT', 'taxi-estimator/1.0')
        self.rate_limit_delay = 1.0  # Secondes entre requêtes (TOS Nominatim)
        self.last_request_time = 0
        
        if not self.user_agent or 'taxi-estimator' not in self.user_agent.lower():
            logger.warning("NOMINATIM_USER_AGENT devrait identifier l'application (TOS).")
    
    def _rate_limit(self):
        """
        Respect rate limit 1 req/sec : attendre si nécessaire.
        """
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()
    
    def _make_request(self, endpoint: str, params: Dict) -> Optional[Dict]:
        """
        Effectue requête GET vers Nominatim avec rate limiting.
        
        Args:
            endpoint (str): Endpoint relatif (ex. 'search', 'reverse')
            params (Dict): Paramètres query (format=json ajouté auto)
            
        Returns:
            Optional[Dict]: JSON réponse ou None
        """
        self._rate_limit()
        
        url = f"{self.base_url}/{endpoint}"
        params['format'] = 'json'
        
        headers = {
            'User-Agent': self.user_agent
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Erreur requête Nominatim {endpoint}: {e}")
            return None
    
    def search_place(
        self,
        query: str,
        country_codes: str = 'cm',
        limit: int = 1,
        viewbox: Optional[List[float]] = None
    ) -> Optional[List[float]]:
        """
        Recherche lieu par nom/adresse et retourne coordonnées (forward geocoding).
        
        Args:
            query (str): Nom lieu (ex. "Carrefour Ekounou, Yaoundé")
            country_codes (str): Codes pays ISO comma-separated ('cm' pour Cameroun)
            limit (int): Nombre max résultats (1-50)
            viewbox (Optional[List[float]]): Bbox préférence [min_lon, min_lat, max_lon, max_lat]
                Ex. Yaoundé : [11.45, 3.80, 11.60, 3.90]
                
        Returns:
            Optional[List[float]]: [lat, lon] du premier résultat ou None si aucun
            
        Exemples :
            >>> client = NominatimClient()
            >>> coords = client.search_place("Carrefour Ekounou, Yaoundé, Cameroun")
            >>> if coords:
            ...     print(f"Lat: {coords[0]}, Lon: {coords[1]}")
            
        Gestion cache :
            Cache résultats 24h (lieux changent rarement). Clé : f"nominatim:search:{query.lower()}"
            
        Limitations :
            - Couverture Cameroun variable (centre Yaoundé OK, rural limité)
            - Pas de POI détaillés comme Mapbox (fallback sur quartiers)
            - Si résultats vides, suggérer user de renseigner coords manuellement
        """
        # Vérifier cache
        cache_key = f"nominatim:search:{query.lower().strip()}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        params = {
            'q': query,
            'countrycodes': country_codes,
            'limit': limit
        }
        
        if viewbox:
            params['viewbox'] = ','.join(map(str, viewbox))
            params['bounded'] = 1  # Restreindre au viewbox
        
        data = self._make_request('search', params)
        
        if data and len(data) > 0:
            result = data[0]
            coords = [float(result['lat']), float(result['lon'])]
            
            # Cacher 24h
            cache.set(cache_key, coords, 86400)
            
            logger.info(f"Nominatim found: {result.get('display_name')} @ {coords}")
            return coords
        else:
            logger.warning(f"Nominatim no results for: {query}")
            return None
    
    def reverse_geocode(
        self,
        lat: float,
        lon: float,
        zoom: int = 18
    ) -> Optional[Dict]:
        """
        Reverse geocoding : coordonnées -> adresse/lieu.
        
        Args:
            lat, lon (float): Coordonnées décimales
            zoom (int): Niveau détail (3=pays, 10=ville, 18=bâtiment/rue)
                Recommandé 18 pour POI urbains
                
        Returns:
            Optional[Dict]: Informations lieu. Structure :
                {
                    "display_name": "Carrefour Ekounou, Ekounou, Yaoundé II, Yaoundé, Centre, Cameroun",
                    "address": {
                        "road": "Route de Nkolbisson",
                        "suburb": "Ekounou",          # Quartier
                        "city_district": "Yaoundé II", # Arrondissement
                        "city": "Yaoundé",
                        "state": "Centre",
                        "country": "Cameroun",
                        "country_code": "cm"
                    },
                    "lat": "3.8667",
                    "lon": "11.5174"
                }
                
        Exemples :
            >>> info = client.reverse_geocode(3.8667, 11.5174)
            >>> if info:
            ...     quartier = info['address'].get('suburb', 'Inconnu')
            ...     ville = info['address'].get('city', 'Inconnue')
            ...     print(f"Quartier: {quartier}, Ville: {ville}")
            
        Utilisation :
            - Enrichir Points avec metadata administratives (quartier, ville, arrondissement)
            - Valider si coords appartiennent bien au Cameroun (vérifier country_code)
            - Fallback si Mapbox Geocoding indisponible
        """
        # Vérifier cache
        cache_key = f"nominatim:reverse:{lat:.6f},{lon:.6f}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        params = {
            'lat': lat,
            'lon': lon,
            'zoom': zoom,
            'addressdetails': 1
        }
        
        data = self._make_request('reverse', params)
        
        if data and 'address' in data:
            # Cacher 7 jours (adresses changent rarement)
            cache.set(cache_key, data, 604800)
            return data
        else:
            logger.warning(f"Nominatim reverse failed for: {lat}, {lon}")
            return None
    
    def extract_quartier_ville(self, reverse_data: Dict) -> Dict[str, Optional[str]]:
        """
        Extrait quartier, ville, arrondissement depuis réponse reverse geocoding.
        
        Args:
            reverse_data (Dict): JSON reverse_geocode()
            
        Returns:
            Dict: {
                'quartier': str ou None,
                'ville': str ou None,
                'arrondissement': str ou None,
                'departement': str ou None
            }
            
        Mapping champs Nominatim :
            - quartier : 'suburb', 'neighbourhood', ou 'hamlet'
            - ville : 'city', 'town', ou 'village'
            - arrondissement : 'city_district' ou 'municipality'
            - departement : 'county' ou 'state_district'
            
        Exemples :
            >>> reverse_data = {
            ...     'address': {
            ...         'suburb': 'Ekounou',
            ...         'city_district': 'Yaoundé II',
            ...         'city': 'Yaoundé',
            ...         'state': 'Centre'
            ...     }
            ... }
            >>> client.extract_quartier_ville(reverse_data)
            {'quartier': 'Ekounou', 'ville': 'Yaoundé', 'arrondissement': 'Yaoundé II', 'departement': 'Centre'}
            
        Gestion manques :
            Si champs absents, return None pour ce champ (géré par modèle Point nullable).
        """
        address = reverse_data.get('address', {})
        
        return {
            'quartier': address.get('suburb') or address.get('neighbourhood') or address.get('hamlet'),
            'ville': address.get('city') or address.get('town') or address.get('village'),
            'arrondissement': address.get('city_district') or address.get('municipality'),
            'departement': address.get('county') or address.get('state_district') or address.get('state')
        }


# Instance singleton
nominatim_client = NominatimClient()
