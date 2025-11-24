"""
Client pour intégration OpenMeteo API - météo gratuite sans token.

Utilisé pour :
- Fallback météo si user n'indique pas lors ajout trajet
- Conversion conditions météo -> code 0-3 (soleil/pluie légère/pluie forte/orage)
- Prévisions horaires pour estimation prix (si trajet futur)

Configuration requise dans settings.py :
    OPENMETEO_BASE_URL : https://api.open-meteo.com/v1

Avantages OpenMeteo :
- Gratuit, sans token, pas de rate limit strict
- Couverture mondiale incluant Cameroun
- Données actuelles + prévisions 7 jours
- Format JSON simple
"""

import requests
import logging
from typing import Dict, Optional, List
from datetime import datetime
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class OpenMeteoClient:
    """
    Client pour OpenMeteo API avec conversion vers codes projet.
    
    Usage :
        client = OpenMeteoClient()
        code_meteo = client.get_current_weather_code(lat=3.8547, lon=11.5021)
        # code_meteo : 0-3 (soleil, pluie légère, pluie forte, orage)
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'OPENMETEO_BASE_URL', 'https://api.open-meteo.com/v1')
    
    def get_current_weather(
        self,
        lat: float,
        lon: float,
        current_params: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        Récupère météo actuelle pour coordonnées données.
        
        Args:
            lat, lon (float): Coordonnées
            current_params (Optional[List[str]]): Variables météo à récupérer.
                Par défaut : ['weathercode', 'precipitation', 'rain', 'temperature_2m']
                
        Returns:
            Optional[Dict]: JSON OpenMeteo. Structure :
                {
                    "latitude": 3.85,
                    "longitude": 11.50,
                    "current": {
                        "time": "2023-11-05T14:00",
                        "weathercode": 61,  # Code WMO (0-99)
                        "precipitation": 2.5,  # mm/h
                        "rain": 2.5,
                        "temperature_2m": 28.0  # °C
                    },
                    "timezone": "Africa/Douala"
                }
                
        Codes WMO météo (weather code) :
            0 : Ciel dégagé
            1-3 : Partiellement nuageux
            45-48 : Brouillard
            51-57 : Bruine
            61-65 : Pluie légère à modérée
            66-67 : Pluie verglaçante
            71-77 : Neige (rare Cameroun)
            80-82 : Averses pluie
            85-86 : Averses neige
            95-99 : Orages (avec grêle)
            
        Exemples :
            >>> client = OpenMeteoClient()
            >>> weather = client.get_current_weather(3.8547, 11.5021)
            >>> if weather:
            ...     code_wmo = weather['current']['weathercode']
            ...     precipitation = weather['current']['precipitation']
            ...     print(f"Code WMO: {code_wmo}, Précipitations: {precipitation}mm/h")
        """
        if current_params is None:
            current_params = ['weathercode', 'precipitation', 'rain', 'temperature_2m']
        
        endpoint = f"{self.base_url}/forecast"
        params = {
            'latitude': lat,
            'longitude': lon,
            'current': ','.join(current_params),
            'timezone': 'Africa/Douala'  # Fuseau Cameroun
        }
        
        # Cache 15 minutes (météo change rapidement)
        cache_key = f"openmeteo:current:{lat:.4f},{lon:.4f}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            cache.set(cache_key, data, 900)  # 15 min
            return data
            
        except requests.RequestException as e:
            logger.error(f"Erreur OpenMeteo API: {e}")
            return None
    
    def convert_wmo_to_project_code(self, wmo_code: int, precipitation: float = 0.0) -> int:
        """
        Convertit code WMO OpenMeteo (0-99) vers code projet (0-3).
        
        Mapping :
            0 : Soleil (WMO 0-3 : ciel dégagé/peu nuageux)
            1 : Pluie légère (WMO 51-65 : bruine/pluie modérée, ou précip < 5mm/h)
            2 : Pluie forte (WMO 66-82 : pluie intense/averses, ou précip 5-15mm/h)
            3 : Orage (WMO 95-99 : orages, ou précip > 15mm/h)
            
        Args:
            wmo_code (int): Code WMO (0-99)
            precipitation (float): Précipitations mm/h (pour affiner si code ambigu)
            
        Returns:
            int: Code projet 0-3
            
        Exemples :
            >>> client = OpenMeteoClient()
            >>> client.convert_wmo_to_project_code(0, 0.0)
            0  # Soleil
            
            >>> client.convert_wmo_to_project_code(61, 3.0)
            1  # Pluie légère
            
            >>> client.convert_wmo_to_project_code(82, 8.0)
            2  # Pluie forte
            
            >>> client.convert_wmo_to_project_code(95, 20.0)
            3  # Orage
            
        Gestion edge cases :
            - Si WMO inconnu (ex. 100+), log warning et return 0 (default soleil)
            - Si WMO nuageux (45-48 brouillard) sans pluie, return 0
        """
        # Mapping WMO -> Projet avec précipitations comme affinement
        
        # Orages (priorité haute)
        if 95 <= wmo_code <= 99:
            return 3
        
        # Pluie forte / Averses intenses
        if 66 <= wmo_code <= 82 or precipitation > 10.0:
            return 2
        
        # Pluie légère / Bruine
        if 51 <= wmo_code <= 65 or 5.0 < precipitation <= 10.0:
            return 1
        
        # Pluie très légère (précip faible mais présente)
        if 0 < precipitation <= 5.0:
            return 1
        
        # Soleil / Nuageux sans pluie
        if 0 <= wmo_code <= 48:  # Inclut ciel dégagé, nuageux, brouillard
            return 0
        
        # Default fallback (codes inconnus)
        logger.warning(f"Code WMO inconnu: {wmo_code}. Fallback soleil (0).")
        return 0
    
    def get_current_weather_code(self, lat: float, lon: float) -> Optional[int]:
        """
        Récupère et convertit météo actuelle en code projet (0-3).
        
        Méthode raccourci combinant get_current_weather + convert_wmo_to_project_code.
        Utilisée dans serializers/views pour fallback météo automatique.
        
        Args:
            lat, lon (float): Coordonnées point (départ ou arrivée, ou moyenne)
            
        Returns:
            Optional[int]: Code météo 0-3 ou None si API échoue
            
        Exemples :
            >>> client = OpenMeteoClient()
            >>> code = client.get_current_weather_code(3.8547, 11.5021)
            >>> if code is not None:
            ...     labels = ['Soleil', 'Pluie légère', 'Pluie forte', 'Orage']
            ...     print(f"Météo actuelle: {labels[code]}")
            
        Gestion manques :
            Si API échoue (connexion, timeout), return None et logger error.
            Caller doit gérer None (ex. ne pas stocker météo ou utiliser default code 0).
        """
        weather = self.get_current_weather(lat, lon)
        if not weather or 'current' not in weather:
            return None
        
        wmo_code = weather['current'].get('weathercode', 0)
        precipitation = weather['current'].get('precipitation', 0.0)
        
        return self.convert_wmo_to_project_code(wmo_code, precipitation)
    
    def get_hourly_forecast(
        self,
        lat: float,
        lon: float,
        start_date: str,
        end_date: str,
        hourly_params: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        Récupère prévisions horaires (jusqu'à 7 jours) pour planning trajets futurs.
        
        Args:
            lat, lon (float): Coordonnées
            start_date, end_date (str): Dates ISO format 'YYYY-MM-DD'
            hourly_params (Optional[List[str]]): Variables horaires
                Par défaut : ['weathercode', 'precipitation', 'temperature_2m']
                
        Returns:
            Optional[Dict]: JSON avec arrays horaires. Structure :
                {
                    "hourly": {
                        "time": ["2023-11-05T00:00", "2023-11-05T01:00", ...],
                        "weathercode": [0, 0, 1, 61, 95, ...],
                        "precipitation": [0.0, 0.0, 0.1, 2.5, 15.0, ...],
                        "temperature_2m": [22.0, 21.5, 21.0, 20.0, 19.5, ...]
                    }
                }
                
        Utilisation :
            Pour estimations trajets planifiés (user veut savoir prix demain matin 8h).
            Extraire météo heure spécifique, convertir vers code projet.
            
        Exemples :
            >>> from datetime import date, timedelta
            >>> tomorrow = (date.today() + timedelta(days=1)).isoformat()
            >>> forecast = client.get_hourly_forecast(3.85, 11.50, tomorrow, tomorrow)
            >>> if forecast:
            ...     times = forecast['hourly']['time']
            ...     codes = forecast['hourly']['weathercode']
            ...     for t, c in zip(times, codes):
            ...         if '08:00' in t:  # Trouver 8h du matin
            ...             project_code = client.convert_wmo_to_project_code(c)
            ...             print(f"Météo demain 8h: code {project_code}")
        """
        if hourly_params is None:
            hourly_params = ['weathercode', 'precipitation', 'temperature_2m']
        
        endpoint = f"{self.base_url}/forecast"
        params = {
            'latitude': lat,
            'longitude': lon,
            'start_date': start_date,
            'end_date': end_date,
            'hourly': ','.join(hourly_params),
            'timezone': 'Africa/Douala'
        }
        
        try:
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Erreur OpenMeteo forecast: {e}")
            return None


# Instance singleton
openmeteo_client = OpenMeteoClient()
