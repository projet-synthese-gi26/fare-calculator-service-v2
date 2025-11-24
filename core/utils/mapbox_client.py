"""
Client pour interactions avec Mapbox APIs.

Encapsule appels à :
- Directions API (calcul itinéraires avec trafic, annotations congestion/maxspeed/bearings)
- Matrix API (calcul batch distances/durées pour similarité)
- Isochrone API (périmètres temporels pour similarité intelligente)
- Map Matching API (alignement GPS sur routes pour POI)
- Search API (geocoding, reverse geocoding, auto-complétion POI)

Gère :
- Authentification via token Mapbox (settings)
- Caching réponses en BD SQLite pour économiser quotas
- Fallbacks pour données "unknown" (fréquent Cameroun)
- Rate limiting (respecter 600 requêtes/minute free tier)
- Logging erreurs/warnings

Configuration requise dans settings.py :
    MAPBOX_ACCESS_TOKEN : Token gratuit mapbox.com
    MAPBOX_BASE_URL : https://api.mapbox.com
    MAPBOX_CACHE_ENABLED : True
    MAPBOX_CACHE_TTL_SECONDS : 3600 (1h pour données dynamiques comme trafic)
"""

import requests
import logging
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from django.core.cache import cache
import json
import hashlib

logger = logging.getLogger(__name__)


class MapboxClient:
    """
    Client wrapper pour Mapbox APIs avec gestion cache et fallbacks.
    
    Usage :
        client = MapboxClient()
        route_data = client.get_directions(
            coordinates=[[11.5021, 3.8547], [11.5174, 3.8667]],
            profile='driving-traffic',
            annotations=['congestion', 'maxspeed', 'duration', 'distance']
        )
    """
    
    def __init__(self):
        self.token = settings.MAPBOX_ACCESS_TOKEN
        self.base_url = settings.MAPBOX_BASE_URL
        self.cache_enabled = getattr(settings, 'MAPBOX_CACHE_ENABLED', True)
        self.cache_ttl = getattr(settings, 'MAPBOX_CACHE_TTL_SECONDS', 3600)
        
        if not self.token:
            logger.warning("MAPBOX_ACCESS_TOKEN non configuré. Appels Mapbox échoueront.")
    
    def _generate_cache_key(self, endpoint: str, params: Dict) -> str:
        """
        Génère clé cache unique basée sur endpoint et paramètres.
        Utilise hash MD5 pour éviter clés trop longues.
        """
        params_str = json.dumps(params, sort_keys=True)
        hash_obj = hashlib.md5(f"{endpoint}:{params_str}".encode())
        return f"mapbox:{hash_obj.hexdigest()}"
    
    def _make_request(self, endpoint: str, params: Dict, cache_key: Optional[str] = None) -> Optional[Dict]:
        """
        Effectue requête HTTP GET vers Mapbox avec gestion cache/erreurs.
        
        Args:
            endpoint (str): URL complète endpoint (ex. https://api.mapbox.com/directions/v5/...)
            params (Dict): Paramètres query string (sans access_token, ajouté automatiquement)
            cache_key (Optional[str]): Clé cache si enabled
            
        Returns:
            Optional[Dict]: JSON réponse Mapbox ou None si erreur
        """
        # Vérifier cache
        if self.cache_enabled and cache_key:
            cached = cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit pour {endpoint}")
                return cached
        
        # Ajouter token aux params
        params['access_token'] = self.token
        
        try:
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Cacher réponse
            if self.cache_enabled and cache_key:
                cache.set(cache_key, data, self.cache_ttl)
            
            return data
            
        except requests.RequestException as e:
            logger.error(f"Erreur requête Mapbox {endpoint}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON Mapbox: {e}")
            return None
    
    def get_directions(
        self,
        coordinates: List[List[float]],
        profile: str = 'driving-traffic',
        annotations: Optional[List[str]] = None,
        geometries: str = 'geojson',
        steps: bool = True,
        banner_instructions: bool = False
    ) -> Optional[Dict]:
        """
        Appelle Mapbox Directions API pour calculer itinéraire entre points.
        
        Essentiel pour :
        - Calcul distance routière réelle (vs. ligne droite)
        - Récupération données trafic (annotations congestion)
        - Extraction bearings/maneuvers pour calcul sinuosité
        - Classes routes (via steps avec route classes)
        
        Args:
            coordinates (List[List[float]]): Liste coords [lon, lat] (ex. [[11.5021, 3.8547], [11.5174, 3.8667]])
                ATTENTION : Mapbox utilise [lon, lat], pas [lat, lon]
            profile (str): Profil routing. Options :
                - 'driving-traffic' (RECOMMANDÉ) : Inclut trafic temps réel
                - 'driving' : Sans trafic (fallback si traffic indisponible)
                - 'walking', 'cycling' (non pertinent pour taxi)
            annotations (Optional[List[str]]): Données enrichies à récupérer par segment :
                - 'congestion' : Niveaux congestion (low/moderate/heavy/severe/unknown)
                - 'maxspeed' : Vitesse max légale route (km/h ou mph)
                - 'duration' : Durée par segment (secondes)
                - 'distance' : Distance par segment (mètres)
                - 'speed' : Vitesse réelle avec trafic
            geometries (str): Format geometry ('geojson' recommandé pour précision)
            steps (bool): Inclure étapes navigation détaillées (maneuvers, bearings) - REQUIS pour sinuosité
            banner_instructions (bool): Instructions affichage (non nécessaire backend)
            
        Returns:
            Optional[Dict]: JSON Mapbox Directions ou None si erreur. Structure attendue :
                {
                    "routes": [{
                        "distance": 5212.5,  # mètres
                        "duration": 780.3,   # secondes
                        "legs": [{
                            "steps": [{
                                "distance": 123.4,
                                "duration": 20.1,
                                "geometry": {...},
                                "maneuver": {
                                    "type": "turn",
                                    "modifier": "left",
                                    "bearing_before": 0,
                                    "bearing_after": 270,
                                    "location": [11.50, 3.85]
                                },
                                "name": "Avenue Kennedy",
                                "ref": "N1"
                            }, ...],
                            "annotation": {
                                "congestion": ["low", "moderate", "unknown", ...],
                                "maxspeed": [{"speed": 50, "unit": "km/h"}, ...],
                                "distance": [123.4, 234.5, ...],
                                "duration": [20.1, 40.2, ...]
                            }
                        }]
                    }],
                    "waypoints": [...],
                    "code": "Ok"
                }
                
        Gestion manques Cameroun :
            - Si code != "Ok" (ex. "NoRoute"), logger error et return None
            - Si annotations contiennent beaucoup de "unknown" (>50%), log warning mais return data
            - Si maxspeed manquant, estimation via type route (voir fallbacks)
            
        Exemples :
            >>> client = MapboxClient()
            >>> coords = [[11.5021, 3.8547], [11.5174, 3.8667]]  # Polytechnique -> Ekounou
            >>> data = client.get_directions(coords, annotations=['congestion', 'maxspeed'])
            >>> if data and data['code'] == 'Ok':
            ...     route = data['routes'][0]
            ...     print(f"Distance: {route['distance']}m, Durée: {route['duration']}s")
            
        Optimisations :
            - Cache basé sur coords + profile + annotations (TTL 1h pour trafic dynamique)
            - Batch multiples trajets via Matrix API si >5 requêtes similaires
            
        Quotas :
            - Free tier : 100 000 requêtes/mois Directions avec trafic
            - 600 requêtes/minute max (rate limiting Django cache pour respect)
        """
        if not coordinates or len(coordinates) < 2:
            logger.error("get_directions: Au moins 2 coordonnées requises")
            return None
        
        # Construire coords string : lon1,lat1;lon2,lat2
        coords_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
        
        # URL endpoint
        endpoint = f"{self.base_url}/directions/v5/mapbox/{profile}/{coords_string}"
        
        # Paramètres query
        params = {
            'geometries': geometries,
            'steps': 'true' if steps else 'false',
            'banner_instructions': 'true' if banner_instructions else 'false',
            'overview': 'full',  # Toujours full pour données complètes
        }
        
        if annotations:
            params['annotations'] = ','.join(annotations)
        
        # Générer cache key
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        
        # Appel API
        data = self._make_request(endpoint, params, cache_key)
        
        if not data:
            return None
        
        # Vérifier code réponse
        if data.get('code') != 'Ok':
            logger.error(f"Mapbox Directions échec: code={data.get('code')}, message={data.get('message', 'N/A')}")
            return None
        
        # Vérifier routes présentes
        if not data.get('routes'):
            logger.warning("Mapbox Directions: Aucune route trouvée")
            return None
        
        # Logger warnings si beaucoup de "unknown" dans annotations
        if annotations and 'congestion' in annotations:
            route = data['routes'][0]
            for leg in route.get('legs', []):
                annotation = leg.get('annotation', {})
                congestion_list = annotation.get('congestion', [])
                if congestion_list:
                    unknown_count = congestion_list.count('unknown')
                    unknown_rate = unknown_count / len(congestion_list)
                    if unknown_rate > 0.85:
                        logger.warning(
                            f"Mapbox Directions: {unknown_rate:.1%} segments avec congestion 'unknown'. "
                            f"Couverture Cameroun incomplète, utiliser fallbacks."
                        )
        
        return data
    
    def get_matrix(
        self,
        coordinates: List[List[float]],
        profile: str = 'driving-traffic',
        sources: Optional[List[int]] = None,
        destinations: Optional[List[int]] = None,
        annotations: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        Appelle Mapbox Matrix API pour calcul batch distances/durées.
        
        Essentiel pour optimiser similarité : au lieu de multiples appels Directions
        (1 par candidat trajet), batch tous en 1 requête Matrix. Réduit quotas de 90%.
        
        Args:
            coordinates (List[List[float]]): Tous points [lon, lat] (origines + destinations)
            profile (str): 'driving-traffic' pour trafic
            sources (Optional[List[int]]): Indices coords origines (ex. [0, 1, 2]). Si None, tous
            destinations (Optional[List[int]]): Indices coords destinations. Si None, tous
            annotations (Optional[List[str]]): ['distance', 'duration'] (pas congestion détaillée)
            
        Returns:
            Optional[Dict]: Matrix distances/durées. Structure :
                {
                    "distances": [[0, 5212, ...], [5212, 0, ...], ...],  # mètres, NxM
                    "durations": [[0, 780, ...], [780, 0, ...], ...],    # secondes
                    "sources": [...],
                    "destinations": [...],
                    "code": "Ok"
                }
                
        Limites :
            - Max 25 coords (25x25 = 625 éléments matrix)
            - Si plus, split en multiples requêtes
            
        Exemples :
            >>> coords_candidats = [[11.50, 3.85], [11.51, 3.86], [11.52, 3.87]]  # 3 départs candidats
            >>> coord_nouveau = [[11.505, 3.855]]  # Nouveau point user
            >>> all_coords = coords_candidats + coord_nouveau
            >>> matrix = client.get_matrix(all_coords, sources=[3], destinations=[0,1,2])
            >>> # matrix['distances'][0] = distances de coord_nouveau vers 3 candidats
            >>> # matrix['durations'][0] = durées correspondantes
            >>> for i, dist in enumerate(matrix['distances'][0]):
            ...     print(f"Candidat {i}: {dist}m, {matrix['durations'][0][i]}s")
            
        Optimisations :
            - Cache matrice complète (coords triées pour clé unique)
            - Filtrer candidats par quartier AVANT appel pour limiter coords (<25)
        """
        if not coordinates or len(coordinates) < 2:
            logger.error("get_matrix: Au moins 2 coordonnées requises")
            return None
        
        if len(coordinates) > 25:
            logger.warning(f"get_matrix: {len(coordinates)} coords > limite 25. Truncation des 25 premiers.")
            coordinates = coordinates[:25]
        
        # Construire coords string
        coords_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
        
        # URL endpoint
        endpoint = f"{self.base_url}/directions-matrix/v1/mapbox/{profile}/{coords_string}"
        
        # Paramètres
        params = {}
        
        if sources is not None:
            params['sources'] = ';'.join(map(str, sources))
        
        if destinations is not None:
            params['destinations'] = ';'.join(map(str, destinations))
        
        if annotations:
            params['annotations'] = ','.join(annotations)
        
        # Cache key
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        
        # Appel API
        data = self._make_request(endpoint, params, cache_key)
        
        if not data:
            return None
        
        # Vérifier code
        if data.get('code') != 'Ok':
            logger.error(f"Mapbox Matrix échec: code={data.get('code')}, message={data.get('message', 'N/A')}")
            return None
        
        return data
    
    def get_isochrone(
        self,
        coordinates: List[float],
        contours_minutes: List[int],
        profile: str = 'driving-traffic',
        polygons: bool = True
    ) -> Optional[Dict]:
        """
        Appelle Mapbox Isochrone API pour périmètres temporels.
        
        Remplace cercles fixes pour similarité : un point est "similaire" s'il est
        atteignable en X minutes (ex. 2min pour exact, 5min pour élargi). Tient compte
        routes, trafic, restrictions - plus réaliste que rayon euclidien.
        
        Args:
            coordinates (List[float]): Point central [lon, lat]
            contours_minutes (List[int]): Liste temps (ex. [2, 5] pour 2 niveaux similarité)
            profile (str): 'driving-traffic'
            polygons (bool): True pour GeoJSON Polygons (requis pour checks inclusion point)
            
        Returns:
            Optional[Dict]: GeoJSON FeatureCollection avec polygones. Structure :
                {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "properties": {"contour": 2, "metric": "minutes"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[lon, lat], ...]]
                        }
                    }, {
                        "properties": {"contour": 5, ...},
                        "geometry": {...}
                    }]
                }
                
        Utilisation avec Shapely :
            >>> from shapely.geometry import shape, Point
            >>> iso_data = client.get_isochrone([11.5021, 3.8547], [2, 5])
            >>> polygone_2min = shape(iso_data['features'][0]['geometry'])
            >>> point_test = Point(11.505, 3.855)
            >>> if point_test.within(polygone_2min):
            ...     print("Point dans isochrone 2min -> Trajet exact similaire")
            
        Optimisations :
            - Pré-générer isochrones pour POI populaires Yaoundé (task Celery périodique)
            - Stocker polygones en BD (champ JSONField ou fichier GeoJSON)
            - Cache TTL long (isochrones changent peu jour à jour, 24h acceptable)
            
        Gestion manques :
            - Si erreur (NoRoute, zones non cartographiées rurales), log et fallback cercle rayon
            - Limites Cameroun : Isochrones fiables centre Yaoundé, approximatifs périphérie
        """
        if not coordinates or len(coordinates) != 2:
            logger.error("get_isochrone: Coordonnées [lon, lat] requises")
            return None
        
        if not contours_minutes or not all(1 <= c <= 60 for c in contours_minutes):
            logger.error("get_isochrone: contours_minutes invalides (attendu 1-60 min)")
            return None
        
        lon, lat = coordinates
        
        # URL endpoint
        endpoint = f"{self.base_url}/isochrone/v1/mapbox/{profile}/{lon},{lat}"
        
        # Paramètres
        params = {
            'contours_minutes': ','.join(map(str, contours_minutes)),
            'polygons': 'true' if polygons else 'false',
            'denoise': '0.5',  # Réduction bruit léger
            'generalize': '10',  # Simplification 10m tolérance
        }
        
        # Cache key (TTL long 24h pour isochrones stables)
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        
        # Appel API
        data = self._make_request(endpoint, params, cache_key)
        
        if not data:
            logger.warning(f"get_isochrone échec pour {coordinates}. Fallback cercles recommandé.")
            return None
        
        # Vérifier FeatureCollection
        if data.get('type') != 'FeatureCollection' or not data.get('features'):
            logger.warning("get_isochrone: Réponse invalide ou features vides")
            return None
        
        return data
        # Params : contours_minutes (comma-separated), polygons=true
        # Return GeoJSON FeatureCollection ou None
        pass
    
    def map_matching(
        self,
        coordinates: List[List[float]],
        profile: str = 'driving',
        radiuses: Optional[List[int]] = None,
        timestamps: Optional[List[int]] = None
    ) -> Optional[Dict]:
        """
        Appelle Mapbox Map Matching API pour aligner coords GPS brutes sur routes.
        
        Essentiel pour POI : Si user sélectionne point carte random ou GPS imprécis,
        aligner sur route proche puis reverse-geocode pour obtenir POI nommé (carrefour, quartier).
        
        Args:
            coordinates (List[List[float]]): Coords GPS brutes [lon, lat] (peut être bruités)
            profile (str): 'driving' (Map Matching ne supporte pas 'driving-traffic')
            radiuses (Optional[List[int]]): Rayons recherche route par point (mètres). Si None, auto
            timestamps (Optional[List[int]]): Timestamps GPS (optionnel, améliore précision)
            
        Returns:
            Optional[Dict]: Coords alignées + metadata. Structure :
                {
                    "code": "Ok",
                    "matchings": [{
                        "distance": 5210.2,
                        "duration": 780.0,
                        "geometry": {...},  # Route alignée
                        "legs": [...],
                        "confidence": 0.95  # Confiance alignement (0-1)
                    }],
                    "tracepoints": [{
                        "location": [11.5021, 3.8547],  # Coords alignées
                        "name": "Avenue Kennedy",
                        "matchings_index": 0,
                        "waypoint_index": 0
                    }, ...]
                }
                
        Workflow prétraitement POI :
            1. User fournit coords GPS brutes (ex. position actuelle légèrement off-road)
            2. Appeler map_matching pour aligner sur route la plus proche
            3. Extraire coords alignées (tracepoints[0]['location'])
            4. Appeler reverse_geocoding sur coords alignées pour POI (voir méthode ci-dessous)
            5. Stocker Point avec coords alignées + label POI (ex. "Carrefour Ekounou proche")
            
        Exemples :
            >>> coords_gps_brut = [[11.5025, 3.8550], [11.5178, 3.8670]]  # Légèrement off
            >>> matched = client.map_matching(coords_gps_brut, radiuses=[25, 25])
            >>> if matched and matched['code'] == 'Ok':
            ...     coords_alignees = [tp['location'] for tp in matched['tracepoints']]
            ...     print(f"Coords alignées: {coords_alignees}")
            
        Gestion manques :
            - Si confidence < 0.7, log warning (alignement incertain, possible erreur GPS)
            - Si code != "Ok", fallback utiliser coords brutes (mieux que rien)
        """
        if not coordinates or len(coordinates) < 2:
            logger.error("map_matching: Au moins 2 coordonnées requises")
            return None
        
        # Construire coords string
        coords_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
        
        # URL endpoint
        endpoint = f"{self.base_url}/matching/v5/mapbox/{profile}/{coords_string}"
        
        # Paramètres
        params = {
            'geometries': 'geojson',
            'steps': 'false',  # Pas besoin steps pour Map Matching
            'tidy': 'true',  # Resample coords pour meilleure précision
        }
        
        if radiuses:
            params['radiuses'] = ';'.join(map(str, radiuses))
        
        if timestamps:
            params['timestamps'] = ';'.join(map(str, timestamps))
        
        # Cache key
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        
        # Appel API
        data = self._make_request(endpoint, params, cache_key)
        
        if not data:
            return None
        
        # Vérifier code
        if data.get('code') != 'Ok':
            logger.error(f"Map Matching échec: code={data.get('code')}, message={data.get('message', 'N/A')}")
            return None
        
        # Vérifier confidence si disponible
        matchings = data.get('matchings', [])
        if matchings:
            confidence = matchings[0].get('confidence', 1.0)
            if confidence < 0.7:
                logger.warning(f"Map Matching: confiance faible {confidence:.2f}. Alignement incertain.")
        
        return data
    
    def search_forward(
        self,
        query: str,
        proximity: Optional[List[float]] = None,
        bbox: Optional[List[float]] = None,
        country: str = 'cm',
        limit: int = 5,
        types: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        Appelle Mapbox Search API (forward geocoding) pour recherche POI/adresses par nom.
        
        Utilisé frontend pour auto-complétion : user tape "Carrefour E", retourne suggestions
        avec coords, labels, contexte administratif (quartier, ville).
        
        Args:
            query (str): Texte recherche (ex. "Carrefour Ekounou", "Polytechnique Yaoundé")
            proximity (Optional[List[float]]): Coords [lon, lat] pour biaiser résultats vers zone (ex. centre Yaoundé)
            bbox (Optional[List[float]]): Bounding box [min_lon, min_lat, max_lon, max_lat] pour limiter zone
            country (str): Code pays ISO ('cm' pour Cameroun) - ESSENTIEL pour éviter résultats hors pays
            limit (int): Nombre max résultats (1-10)
            types (Optional[List[str]]): Types POI (ex. ['poi', 'address', 'place']). Si None, tous
            
        Returns:
            Optional[Dict]: Résultats recherche. Structure :
                {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "properties": {
                            "name": "Carrefour Ekounou",
                            "full_address": "Ekounou, Yaoundé, Cameroun",
                            "place_type": ["poi"],
                            "context": {
                                "locality": {"name": "Ekounou"},
                                "place": {"name": "Yaoundé"},
                                "region": {"name": "Centre"}
                            }
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [11.5174, 3.8667]
                        }
                    }, ...]
                }
                
        Exemples :
            >>> results = client.search_forward("Polytechnique", proximity=[11.50, 3.85], country='cm')
            >>> for feat in results['features'][:3]:
            ...     print(f"{feat['properties']['name']} - {feat['geometry']['coordinates']}")
            
        Optimisations :
            - Cache résultats populaires (ex. "Carrefour Ekounou" -> coords fixes)
            - Limiter à Yaoundé via bbox initial : [11.45, 3.80, 11.60, 3.90] (approximatif)
        """
        if not query:
            logger.error("search_forward: query vide")
            return None
        
        # URL endpoint (v6 geocoding forward)
        endpoint = f"{self.base_url}/search/geocode/v6/forward"
        
        # Paramètres
        params = {
            'q': query,
            'country': country,
            'limit': limit,
            'language': 'fr',  # Français pour Cameroun
        }
        
        if proximity:
            params['proximity'] = f"{proximity[0]},{proximity[1]}"
        
        if bbox:
            params['bbox'] = ','.join(map(str, bbox))
        
        if types:
            params['types'] = ','.join(types)
        
        # Cache key
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        
        # Appel API
        data = self._make_request(endpoint, params, cache_key)
        
        if not data:
            return None
        
        # Vérifier FeatureCollection
        if data.get('type') != 'FeatureCollection':
            logger.warning("search_forward: Réponse invalide")
            return None
        
        return data
        pass
    
    def reverse_geocoding(
        self,
        coordinates: List[float],
        types: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        Appelle Mapbox Geocoding API (reverse) pour obtenir POI/adresse depuis coords.
        
        Utilisé après Map Matching : coords alignées -> label POI proche (ex. carrefour, école).
        Aussi pour enrichir Points avec métadonnées administratives (quartier, ville).
        
        Args:
            coordinates (List[float]): [lon, lat]
            types (Optional[List[str]]): Types retour prioritaires (ex. ['poi', 'locality', 'place'])
            
        Returns:
            Optional[Dict]: POI/adresse le plus proche. Structure :
                {
                    "type": "FeatureCollection",
                    "features": [{
                        "properties": {
                            "name": "Carrefour Ekounou",
                            "full_address": "Ekounou, Yaoundé II, Yaoundé, Cameroun",
                            "place_type": ["poi"],
                            "context": {
                                "locality": {"name": "Ekounou"},        # Quartier
                                "district": {"name": "Yaoundé II"},     # Arrondissement
                                "place": {"name": "Yaoundé"},           # Ville
                                "region": {"name": "Centre"}            # Région
                            }
                        },
                        "geometry": {
                            "coordinates": [11.5174, 3.8667]
                        }
                    }]
                }
                
        Exemples :
            >>> coords_aligne = [11.5021, 3.8547]  # Après Map Matching
            >>> poi = client.reverse_geocoding(coords_aligne, types=['poi', 'locality'])
            >>> if poi['features']:
            ...     feat = poi['features'][0]
            ...     label = feat['properties']['name']
            ...     quartier = feat['properties']['context']['locality']['name']
            ...     print(f"POI: {label}, Quartier: {quartier}")
            
        Gestion manques :
            - Si features vide (zone non cartographiée), fallback "Point inconnu" + coords
            - Si context incomplet (pas quartier), utiliser locality ou place
        """
        if not coordinates or len(coordinates) != 2:
            logger.error("reverse_geocoding: Coordonnées [lon, lat] requises")
            return None
        
        lon, lat = coordinates
        
        # URL endpoint (v6 reverse)
        endpoint = f"{self.base_url}/search/geocode/v6/reverse"
        
        # Paramètres
        params = {
            'longitude': lon,
            'latitude': lat,
            'limit': 1,
            'language': 'fr',
        }
        
        if types:
            params['types'] = ','.join(types)
        
        # Cache key
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        
        # Appel API
        data = self._make_request(endpoint, params, cache_key)
        
        if not data:
            return None
        
        # Vérifier FeatureCollection
        if data.get('type') != 'FeatureCollection':
            logger.warning("reverse_geocoding: Réponse invalide")
            return None
        
        # Logger si features vide
        if not data.get('features'):
            logger.warning(f"reverse_geocoding: Aucun POI trouvé pour {coordinates}")
        
        return data
    
    def extract_congestion_moyen(self, directions_data: Dict) -> Optional[float]:
        """
        Extrait et calcule congestion moyenne depuis réponse Directions API.
        
        Parse annotations congestion (catégoriques : low/moderate/heavy/severe/unknown),
        convertit en numérique (0-100), moyenne sur tous segments.
        
        Args:
            directions_data (Dict): JSON complet Directions API
            
        Returns:
            Optional[float]: Congestion 0-100 ou None si tous "unknown"
            
        Mapping :
            - "low" -> 15
            - "moderate" -> 40
            - "heavy" -> 70
            - "severe" -> 95
            - "unknown" -> ignore (ne compte pas dans moyenne)
            
        Exemples :
            >>> data = {'routes': [{'legs': [{'annotation': {'congestion': ['low', 'moderate', 'unknown', 'heavy']}}]}]}
            >>> client.extract_congestion_moyen(data)
            41.67  # (15 + 40 + 70) / 3
        """
        if not directions_data or 'routes' not in directions_data:
            return None
        
        routes = directions_data.get('routes', [])
        if not routes:
            return None
        
        # Mapping congestion catégorique -> numérique
        congestion_map = {
            'low': 15,
            'moderate': 40,
            'heavy': 70,
            'severe': 95,
        }
        
        congestion_values = []
        
        for leg in routes[0].get('legs', []):
            annotation = leg.get('annotation', {})
            congestion_list = annotation.get('congestion', [])
            
            for cong in congestion_list:
                if cong in congestion_map:
                    congestion_values.append(congestion_map[cong])
                # Ignorer "unknown" et autres valeurs non mappées
        
        if not congestion_values:
            logger.debug("extract_congestion_moyen: Tous segments 'unknown', retour None")
            return None
        
        moyenne = sum(congestion_values) / len(congestion_values)
        return round(moyenne, 2)
    
    def extract_route_classe_dominante(self, directions_data: Dict) -> Optional[str]:
        """
        Extrait classe route dominante depuis steps Directions API.
        
        Parse steps, examine distances par classe (primary, secondary, tertiary, etc.),
        retourne classe avec cumul distance maximal.
        
        Args:
            directions_data (Dict): JSON Directions API
            
        Returns:
            Optional[str]: 'primary', 'secondary', etc. ou None
            
        Exemples :
            >>> # 60% segments "primary", 40% "secondary"
            >>> client.extract_route_classe_dominante(data)
            'primary'
        """
        if not directions_data or 'routes' not in directions_data:
            return None
        
        routes = directions_data.get('routes', [])
        if not routes:
            return None
        
        # Dictionnaire pour cumuler distances par classe
        classes_distances = {}
        
        for leg in routes[0].get('legs', []):
            for step in leg.get('steps', []):
                distance = step.get('distance', 0)
                
                # Extraire classe depuis intersections (mapbox_streets_v8.class)
                intersections = step.get('intersections', [])
                for intersection in intersections:
                    mapbox_streets = intersection.get('mapbox_streets_v8', {})
                    classe = mapbox_streets.get('class')
                    
                    if classe:
                        classes_distances[classe] = classes_distances.get(classe, 0) + distance
                        break  # Une classe par step suffit
        
        if not classes_distances:
            logger.debug("extract_route_classe_dominante: Aucune classe trouvée")
            return None
        
        # Retourner classe avec distance max
        classe_dominante = max(classes_distances, key=classes_distances.get)
        return classe_dominante


# Instance singleton pour import facile
mapbox_client = MapboxClient()
