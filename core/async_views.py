"""
Async Views pour Django - Version ASGI avec httpx.

Ce module contient les versions async des vues critiques pour une meilleure
performance I/O (appels Mapbox, OpenMeteo, Nominatim).

Usage (urls.py):
    from core.async_views import AsyncEstimateView
    path('api/estimate-async/', AsyncEstimateView.as_view(), name='estimate-async'),

Pour utiliser ces vues, l'application DOIT tourner sous un serveur ASGI (uvicorn).
"""

import logging
from typing import Dict, Optional

from django.conf import settings
from django.http import JsonResponse
from django.views import View
from asgiref.sync import sync_to_async

from .models import Trajet
from .utils.async_mapbox_client import AsyncMapboxClient
from .utils.openmeteo import OpenMeteoClient
from .utils.nominatim import NominatimClient
from .utils.calculations import (
    haversine_distance,
    determiner_tranche_horaire,
    calculer_sinuosite_base,
)

logger = logging.getLogger(__name__)

# Sync clients (will be wrapped with sync_to_async for async views)
openmeteo_client = OpenMeteoClient()
nominatim_client = NominatimClient()


class AsyncEstimateView(View):
    """
    Version async de EstimateView pour POST /api/estimate-async/.
    
    Avantages:
    - Appels Mapbox non-bloquants via httpx.AsyncClient
    - Meilleure concurrence sous charge
    
    Limitations:
    - ORM calls wrapped via sync_to_async (still blocking internally)
    - Nominatim/OpenMeteo calls sync (TODO: async versions)
    """
    
    async def post(self, request):
        """Async POST handler."""
        import json
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        
        # Validate required fields
        if 'depart' not in data or 'arrivee' not in data:
            return JsonResponse({"error": "depart and arrivee required"}, status=400)
        
        depart = data['depart']
        arrivee = data['arrivee']
        
        # Extract coords
        if not (depart.get('lat') and depart.get('lon') and arrivee.get('lat') and arrivee.get('lon')):
            return JsonResponse({"error": "lat/lon required for depart and arrivee"}, status=400)
        
        depart_coords = [float(depart['lat']), float(depart['lon'])]
        arrivee_coords = [float(arrivee['lat']), float(arrivee['lon'])]
        
        heure = data.get('heure')
        meteo = data.get('meteo')
        
        # Fallback heure
        if heure is None:
            heure = determiner_tranche_horaire()
        
        # Fallback meteo (sync call wrapped)
        if meteo is None:
            try:
                get_weather = sync_to_async(openmeteo_client.get_current_weather_code, thread_sensitive=True)
                meteo = await get_weather(depart_coords[0], depart_coords[1])
                if meteo is None:
                    meteo = 0
            except Exception:
                meteo = 0
        
        # Reverse geocode for labels (sync wrapped)
        depart_label = depart.get('label')
        arrivee_label = arrivee.get('label')
        
        if not depart_label:
            try:
                reverse_geo = sync_to_async(nominatim_client.reverse_geocode, thread_sensitive=True)
                result = await reverse_geo(depart_coords[0], depart_coords[1])
                if result:
                    depart_label = result.get('display_name', '').split(',')[0]
            except Exception as e:
                logger.warning(f"Nominatim error: {e}")
                depart_label = f"Point ({depart_coords[0]:.4f}, {depart_coords[1]:.4f})"
        
        if not arrivee_label:
            try:
                reverse_geo = sync_to_async(nominatim_client.reverse_geocode, thread_sensitive=True)
                result = await reverse_geo(arrivee_coords[0], arrivee_coords[1])
                if result:
                    arrivee_label = result.get('display_name', '').split(',')[0]
            except Exception as e:
                logger.warning(f"Nominatim error: {e}")
                arrivee_label = f"Point ({arrivee_coords[0]:.4f}, {arrivee_coords[1]:.4f})"
        
        # ASYNC Mapbox call
        distance_metres = None
        duree_secondes = None
        congestion_mapbox = None
        
        try:
            async with AsyncMapboxClient() as mapbox:
                # Mapbox expects [lon, lat]
                coords_mapbox = [
                    [depart_coords[1], depart_coords[0]],
                    [arrivee_coords[1], arrivee_coords[0]]
                ]
                
                directions = await mapbox.get_directions(
                    coordinates=coords_mapbox,
                    annotations=['congestion', 'duration', 'distance'],
                )
                
                if directions and directions.get('routes'):
                    route = directions['routes'][0]
                    distance_metres = route.get('distance', 0)
                    duree_secondes = route.get('duration', 0)
                    congestion_mapbox = mapbox.extract_congestion_moyen(directions)
                else:
                    raise ValueError("No route")
                    
        except Exception as e:
            logger.warning(f"Mapbox async error: {e}, falling back to Haversine")
            distance_ligne_droite = haversine_distance(
                depart_coords[0], depart_coords[1],
                arrivee_coords[0], arrivee_coords[1]
            )
            distance_metres = distance_ligne_droite * 1.3
            duree_secondes = distance_metres / 8.33
            congestion_mapbox = 50.0
        
        # Search similar trips (ORM - sync wrapped)
        similar_result = await self._search_similar_trips(
            depart_coords, arrivee_coords, distance_metres, heure, meteo
        )
        
        # Build response
        if similar_result:
            return JsonResponse({
                "statut": similar_result['statut'],
                "prix_moyen": similar_result['prix_moyen'],
                "prix_min": similar_result.get('prix_min'),
                "prix_max": similar_result.get('prix_max'),
                "fiabilite": similar_result['fiabilite'],
                "message": similar_result.get('message', ''),
                "details_trajet": {
                    "depart": {"label": depart_label, "coords": depart_coords},
                    "arrivee": {"label": arrivee_label, "coords": arrivee_coords},
                    "distance_metres": distance_metres,
                    "duree_secondes": duree_secondes,
                    "heure": heure,
                    "meteo": meteo,
                    "congestion_mapbox": congestion_mapbox,
                }
            })
        else:
            # Unknown trip fallback
            prix_fallback = self._calculate_fallback_price(distance_metres, heure, meteo)
            return JsonResponse({
                "statut": "inconnu",
                "prix_moyen": prix_fallback,
                "fiabilite": 0.5,
                "message": "Trajet inconnu. Estimation approximative.",
                "details_trajet": {
                    "depart": {"label": depart_label, "coords": depart_coords},
                    "arrivee": {"label": arrivee_label, "coords": arrivee_coords},
                    "distance_metres": distance_metres,
                    "duree_secondes": duree_secondes,
                    "heure": heure,
                    "meteo": meteo,
                    "congestion_mapbox": congestion_mapbox,
                }
            })
    
    @sync_to_async
    def _search_similar_trips(
        self,
        depart_coords,
        arrivee_coords,
        distance_mapbox,
        heure,
        meteo
    ) -> Optional[Dict]:
        """
        Recherche trajets similaires dans la BD.
        Wrapped sync_to_async pour ORM.
        """
        from django.db.models import Avg, Min, Max
        
        # Tolerance distance ±15%
        dist_min = distance_mapbox * 0.85
        dist_max = distance_mapbox * 1.15
        
        # Query candidats
        trajets = Trajet.objects.filter(
            distance_metres__gte=dist_min,
            distance_metres__lte=dist_max,
            heure=heure,
            meteo=meteo
        )
        
        # Filter by geographic proximity (simple Haversine filter)
        candidats = []
        for t in trajets[:100]:  # Limit scan
            d_dep = haversine_distance(
                depart_coords[0], depart_coords[1],
                t.depart_lat, t.depart_lon
            )
            d_arr = haversine_distance(
                arrivee_coords[0], arrivee_coords[1],
                t.arrivee_lat, t.arrivee_lon
            )
            if d_dep < 200 and d_arr < 200:  # Within 200m
                candidats.append(t)
        
        if not candidats:
            return None
        
        # Aggregate prices
        prix_list = [t.prix for t in candidats]
        return {
            "statut": "exact" if len(candidats) >= 3 else "similaire",
            "prix_moyen": int(sum(prix_list) / len(prix_list)),
            "prix_min": min(prix_list),
            "prix_max": max(prix_list),
            "fiabilite": min(0.95, 0.7 + len(candidats) * 0.05),
            "nb_matches": len(candidats),
            "message": f"Basé sur {len(candidats)} trajets similaires."
        }
    
    def _calculate_fallback_price(self, distance_m, heure, meteo) -> int:
        """Prix fallback basé sur distance."""
        # Base: 200 CFA + 50 CFA/km
        prix = 200 + int((distance_m / 1000) * 50)
        
        # Night premium
        if heure in ['soir', 'nuit']:
            prix = int(prix * 1.15)
        
        # Rain premium
        if meteo and meteo >= 2:
            prix = int(prix * 1.10)
        
        return min(max(prix, 200), 5000)  # Clamp
