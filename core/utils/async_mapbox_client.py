"""
Client ASYNC pour interactions avec Mapbox APIs.
Version asynchrone de MapboxClient utilisant httpx.AsyncClient.

Usage:
    async with AsyncMapboxClient() as client:
        route_data = await client.get_directions(
            coordinates=[[11.5021, 3.8547], [11.5174, 3.8667]],
        )
"""

import httpx
import logging
from typing import Dict, List, Optional
from django.conf import settings
from django.core.cache import cache
import json
import hashlib

logger = logging.getLogger(__name__)


class AsyncMapboxClient:
    """
    Client async pour Mapbox APIs avec gestion cache et fallbacks.
    Utilise httpx.AsyncClient pour I/O non-bloquant.
    
    Usage:
        async with AsyncMapboxClient() as client:
            data = await client.get_directions(...)
    """
    
    def __init__(self):
        self.token = settings.MAPBOX_ACCESS_TOKEN
        self.base_url = settings.MAPBOX_BASE_URL
        self.cache_enabled = getattr(settings, 'MAPBOX_CACHE_ENABLED', True)
        self.cache_ttl = getattr(settings, 'MAPBOX_CACHE_TTL_SECONDS', 3600)
        self._client: Optional[httpx.AsyncClient] = None
        
        if not self.token:
            logger.warning("MAPBOX_ACCESS_TOKEN non configuré.")
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=15.0)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    def _generate_cache_key(self, endpoint: str, params: Dict) -> str:
        params_str = json.dumps(params, sort_keys=True)
        hash_obj = hashlib.md5(f"{endpoint}:{params_str}".encode())
        return f"mapbox_async:{hash_obj.hexdigest()}"
    
    async def _make_request(self, endpoint: str, params: Dict, cache_key: Optional[str] = None) -> Optional[Dict]:
        """Effectue requête HTTP GET async vers Mapbox."""
        # Check cache (sync, acceptable pour Django cache in async context)
        if self.cache_enabled and cache_key:
            cached = cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit pour {endpoint}")
                return cached
        
        params['access_token'] = self.token
        
        try:
            response = await self._client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            
            if self.cache_enabled and cache_key:
                cache.set(cache_key, data, self.cache_ttl)
            
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Mapbox HTTP error {endpoint}: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Mapbox request error {endpoint}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Mapbox JSON parse error: {e}")
            return None
    
    async def get_directions(
        self,
        coordinates: List[List[float]],
        profile: str = 'driving-traffic',
        annotations: Optional[List[str]] = None,
        geometries: str = 'geojson',
        steps: bool = True,
    ) -> Optional[Dict]:
        """
        Async version of Directions API call.
        See MapboxClient.get_directions for full documentation.
        """
        if not coordinates or len(coordinates) < 2:
            logger.error("get_directions: Au moins 2 coordonnées requises")
            return None
        
        coords_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
        endpoint = f"{self.base_url}/directions/v5/mapbox/{profile}/{coords_string}"
        
        params = {
            'geometries': geometries,
            'steps': 'true' if steps else 'false',
            'overview': 'full',
        }
        
        if annotations:
            params['annotations'] = ','.join(annotations)
        
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        data = await self._make_request(endpoint, params, cache_key)
        
        if not data:
            return None
        
        if data.get('code') != 'Ok':
            logger.error(f"Mapbox Directions fail: {data.get('code')}")
            return None
        
        if not data.get('routes'):
            logger.warning("Mapbox Directions: No route found")
            return None
        
        return data
    
    async def get_matrix(
        self,
        coordinates: List[List[float]],
        profile: str = 'driving-traffic',
        sources: Optional[List[int]] = None,
        destinations: Optional[List[int]] = None,
        annotations: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        Async version of Matrix API call.
        See MapboxClient.get_matrix for full documentation.
        """
        if not coordinates or len(coordinates) < 2:
            logger.error("get_matrix: Au moins 2 coordonnées requises")
            return None
        
        if len(coordinates) > 25:
            logger.warning(f"get_matrix: {len(coordinates)} coords > 25 limit. Truncating.")
            coordinates = coordinates[:25]
        
        coords_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
        endpoint = f"{self.base_url}/directions-matrix/v1/mapbox/{profile}/{coords_string}"
        
        params = {}
        if sources is not None:
            params['sources'] = ';'.join(map(str, sources))
        if destinations is not None:
            params['destinations'] = ';'.join(map(str, destinations))
        if annotations:
            params['annotations'] = ','.join(annotations)
        
        cache_key = self._generate_cache_key(endpoint, params) if self.cache_enabled else None
        data = await self._make_request(endpoint, params, cache_key)
        
        if not data:
            return None
        
        if data.get('code') != 'Ok':
            logger.error(f"Mapbox Matrix fail: {data.get('code')}")
            return None
        
        return data
    
    async def search_forward(
        self,
        query: str,
        proximity: Optional[List[float]] = None,
        country: str = 'cm',
        limit: int = 5,
    ) -> Optional[Dict]:
        """Async forward geocoding."""
        if not query:
            return None
        
        endpoint = f"{self.base_url}/search/geocode/v6/forward"
        params = {
            'q': query,
            'country': country,
            'limit': limit,
            'language': 'fr',
        }
        if proximity:
            params['proximity'] = f"{proximity[0]},{proximity[1]}"
        
        cache_key = self._generate_cache_key(endpoint, params)
        return await self._make_request(endpoint, params, cache_key)
    
    async def reverse_geocoding(
        self,
        coordinates: List[float],
    ) -> Optional[Dict]:
        """Async reverse geocoding."""
        if not coordinates or len(coordinates) != 2:
            return None
        
        lon, lat = coordinates
        endpoint = f"{self.base_url}/search/geocode/v6/reverse"
        params = {
            'longitude': lon,
            'latitude': lat,
            'limit': 1,
            'language': 'fr',
        }
        
        cache_key = self._generate_cache_key(endpoint, params)
        return await self._make_request(endpoint, params, cache_key)
    
    def extract_congestion_moyen(self, directions_data: Dict) -> Optional[float]:
        """Same as sync version - pure computation, no I/O."""
        if not directions_data or 'routes' not in directions_data:
            return None
        
        routes = directions_data.get('routes', [])
        if not routes:
            return None
        
        congestion_map = {'low': 15, 'moderate': 40, 'heavy': 70, 'severe': 95}
        congestion_values = []
        
        for leg in routes[0].get('legs', []):
            annotation = leg.get('annotation', {})
            for cong in annotation.get('congestion', []):
                if cong in congestion_map:
                    congestion_values.append(congestion_map[cong])
        
        if not congestion_values:
            return None
        
        return round(sum(congestion_values) / len(congestion_values), 2)
