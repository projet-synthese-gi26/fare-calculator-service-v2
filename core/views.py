"""
Views Django REST Framework pour l'API d'estimation des prix de taxi.

Endpoints principaux :
- /api/estimate/ (POST/GET) : Estimation prix pour trajet donné
- /api/add-trajet/ (POST) : Ajout trajet réel par utilisateur
- /api/trajets/ (GET) : Liste trajets (admin/debug)
- /api/points/ (GET) : Liste points d'intérêt (admin/debug)

Logique estimation hiérarchique (dans EstimateView) :
    1. check_similar_match : Recherche trajets similaires avec périmètres progressifs
       - Filtrage grossier par quartiers/arrondissement (optimisation queries BD)
       - Vérification similarité points via isochrones Mapbox (2min étroit, 5min élargi) 
         OU cercles Haversine fallback (50m/150m si isochrones échouent)
       - Validation distances/durées via Mapbox Matrix API
       - Si match périmètre étroit (2min/50m) : Prix direct sans ajustement
       - Si match périmètre élargi (5min/150m) : Prix avec ajustements (distance extra, congestion)
       - Fallback variables : Si pas de match avec heure/météo exactes, chercher avec différentes 
         et noter dans réponse (+50 CFA si nuit vs jour, +10% si pluie vs soleil)
    2. fallback_inconnu : Si aucun trajet similaire trouvé
       - Estimations distance-based, standardisé, zone-based, ML (si disponible)
       - Retourne 4 estimations avec fiabilité faible (0.5)
    
Toutes fonctions de prédiction/ML sont des **pass** avec docstrings détaillées pour équipe.
"""

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.utils import timezone
from django.db.models import Avg, Min, Max, Count, Q
from django.conf import settings
from datetime import datetime
import logging
from typing import Dict, List, Optional, Tuple

from .models import Point, Trajet, ApiKey
from .serializers import (
    PointSerializer,
    TrajetSerializer,
    ApiKeySerializer,
    EstimateInputSerializer,
    PredictionOutputSerializer
)
from .utils import (
    mapbox_client,
    nominatim_client,
    openmeteo_client,
    haversine_distance,
    determiner_tranche_horaire
)

logger = logging.getLogger(__name__)


class PointViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet lecture seule pour Points d'intérêt.
    
    Endpoints :
        GET /api/points/ : Liste tous points
        GET /api/points/{id}/ : Détail point
        GET /api/points/?quartier=Ekounou : Filtrage par quartier
        GET /api/points/?ville=Yaoundé : Filtrage par ville
        
    Utilisé principalement admin/debug. Frontend utilise Search API Mapbox pour auto-complétion.
    """
    queryset = Point.objects.all()
    serializer_class = PointSerializer
    filterset_fields = ['ville', 'quartier', 'arrondissement']
    search_fields = ['label', 'quartier', 'ville']
    ordering_fields = ['created_at', 'label']
    ordering = ['-created_at']


class TrajetViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet lecture seule pour Trajets.
    
    Endpoints :
        GET /api/trajets/ : Liste tous trajets
        GET /api/trajets/{id}/ : Détail trajet
        GET /api/trajets/?heure=matin : Filtrage par heure
        GET /api/trajets/?meteo=1 : Filtrage par météo
        GET /api/trajets/?type_zone=0 : Filtrage par type zone
        
    Utilisé admin/debug et analyse données. Création via AddTrajetView.
    """
    queryset = Trajet.objects.all().select_related('point_depart', 'point_arrivee')
    serializer_class = TrajetSerializer
    filterset_fields = ['heure', 'meteo', 'type_zone', 'route_classe_dominante']
    search_fields = ['point_depart__label', 'point_arrivee__label']
    ordering_fields = ['date_ajout', 'prix', 'distance']
    ordering = ['-date_ajout']
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Endpoint stats globales trajets : /api/trajets/stats/
        
        Retourne :
            - Nombre total trajets
            - Prix moyen, min, max
            - Distance moyenne
            - Répartition par heure, météo, type zone
            
        JSON output :
            {
                "total_trajets": 150,
                "prix": {"moyen": 250, "min": 100, "max": 500},
                "distance_moyenne": 4800,
                "repartition_heure": {"matin": 50, "apres-midi": 40, ...},
                "repartition_meteo": {0: 80, 1: 40, ...},
                "repartition_zone": {0: 100, 1: 30, 2: 20}
            }
        """
        # TODO : Équipe implémente agrégations Django ORM
        # total = Trajet.objects.count()
        # prix_stats = Trajet.objects.aggregate(
        #     moyen=Avg('prix'),
        #     min=Min('prix'),
        #     max=Max('prix')
        # )
        # distance_moy = Trajet.objects.aggregate(Avg('distance'))['distance__avg']
        # repartition_heure = dict(Trajet.objects.values('heure').annotate(count=Count('id')).values_list('heure', 'count'))
        # ...
        # return Response({...})
        
        return Response({
            "message": "TODO équipe : implémenter stats agrégées",
            "note": "Utiliser Django ORM aggregations (Avg, Min, Max, Count)"
        })


class EstimateView(APIView):
    """
    View principale pour estimation prix trajet : POST/GET /api/estimate/
    
    Accepte :
        POST avec JSON body (EstimateInputSerializer)
        GET avec query params (?depart_lat=X&depart_lon=Y&arrivee_lat=Z...)
        
    Workflow estimation hiérarchique :
        1. Valider inputs via EstimateInputSerializer (conversion nom→coords si nécessaire)
        2. Appliquer fallbacks variables optionnelles (heure, météo, type_zone) si manquantes
        3. Filtrer candidats par quartiers départ/arrivée via reverse-geocoding (optimisation)
        4. check_similar_match : Recherche trajets similaires avec 2 périmètres
            a) Périmètre ÉTROIT (isochrone 2min / cercle 50m fallback)
               - Vérifier points départ/arrivée dans isochrones Mapbox 2 minutes
               - Si isochrones échouent (routes manquantes Cameroun) → cercles Haversine 50m
               - Si match + distance ±10% : PRIX DIRECT sans ajustement (fiabilité 0.9-0.95)
               - Moyenne/min/max des prix trouvés
            b) Périmètre ÉLARGI (isochrone 5min / cercle 150m fallback)
               - Mêmes vérifications avec périmètres plus larges
               - Si match : Calculer ajustements via Mapbox Matrix API
                 * Distance extra (Matrix pour distance réelle départ→départ_bd, arrivée→arrivée_bd)
                 * Ajustement prix : +50 CFA par km extra (configurable settings.ADJUSTMENT_PRIX_PAR_KM)
                 * Congestion différente : +10% si user signale embouteillage (congestion_user>7)
                 * Sinuosité différente : +20 CFA si indice>1.5 (routes tortueuses)
               - PRIX AJUSTÉ (fiabilité 0.7-0.8)
            c) Fallback VARIABLES (si pas de match avec heure/météo exactes)
               - Chercher même périmètre mais avec heure différente (ex : matin→nuit)
               - Chercher avec météo différente (ex : soleil→pluie)
               - Appliquer ajustements standards :
                 * Heure diff : +50 CFA si jour→nuit, -30 CFA si nuit→jour
                 * Météo diff : +10% si soleil→pluie, -5% si pluie→soleil
               - Noter dans réponse : "Prix basé sur trajets à heure différente (nuit)"
        5. fallback_inconnu : Si aucun trajet similaire dans périmètres
            - Estimation distance-based : Chercher distances similaires ±20%, extrapoler prix
            - Estimation standardisée : Prix officiels Cameroun (300 CFA jour, 350 nuit)
            - Estimation zone-based : Moyenne prix trajets dans arrondissement/ville
            - Estimation ML : predict_prix_ml avec features (distance, heure, météo, zone, congestion)
            - Retourne 4 estimations, fiabilité faible (0.5), invite à ajouter prix après trajet
            - Retourner les 3-4 estimations avec message "Inconnu, fiabilité faible"
        7. Construire objet Prediction (PredictionOutputSerializer) avec tous détails
        8. Retourner JSON Response
        
    Exemples requêtes :
        POST /api/estimate/
        {
            "depart": {"lat": 3.8547, "lon": 11.5021},
            "arrivee": "Carrefour Ekounou",
            "heure": "matin"
        }
        
        GET /api/estimate/?depart_lat=3.8547&depart_lon=11.5021&arrivee_lat=3.8667&arrivee_lon=11.5174&heure=matin
        
    Exemples réponses :
        # Cas exact
        {
            "statut": "exact",
            "prix_moyen": 250,
            "prix_min": 200,
            "prix_max": 300,
            "fiabilite": 0.95,
            "message": "Estimation basée sur 8 trajets exacts similaires.",
            "details_trajet": {...},
            "ajustements_appliques": {...}
        }
        
        # Cas similaire
        {
            "statut": "similaire",
            "prix_moyen": 270,
            "prix_min": 250,
            "prix_max": 290,
            "fiabilite": 0.75,
            "message": "Estimation ajustée depuis trajets similaires (+20 CFA pour distance extra).",
            ...
        }
        
        # Cas inconnu
        {
            "statut": "inconnu",
            "prix_moyen": 280,
            "estimations_supplementaires": {
                "distance_based": 260,
                "standardise": 300,
                "zone_based": 270,
                "ml_prediction": 285
            },
            "fiabilite": 0.50,
            "message": "Trajet inconnu. Estimations approximatives. Ajoutez votre prix après trajet.",
            "suggestions": ["Fiabilité faible, négociez prudemment"]
        }
    """
    
    def post(self, request):
        """Endpoint POST /api/estimate/ avec JSON body."""
        serializer = EstimateInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        validated_data = serializer.validated_data
        return self._process_estimate(validated_data)
    
    def get(self, request):
        """Endpoint GET /api/estimate/ avec query params (conversion vers format POST)."""
        # Convertir query params vers format EstimateInputSerializer
        try:
            data = {
                'depart': {
                    'lat': float(request.GET.get('depart_lat')),
                    'lon': float(request.GET.get('depart_lon'))
                },
                'arrivee': {
                    'lat': float(request.GET.get('arrivee_lat')),
                    'lon': float(request.GET.get('arrivee_lon'))
                }
            }
            
            # Optionnels
            if request.GET.get('heure'):
                data['heure'] = request.GET.get('heure')
            if request.GET.get('meteo'):
                data['meteo'] = int(request.GET.get('meteo'))
            if request.GET.get('type_zone'):
                data['type_zone'] = int(request.GET.get('type_zone'))
            if request.GET.get('congestion_user'):
                data['congestion_user'] = int(request.GET.get('congestion_user'))
            
        except (TypeError, ValueError, KeyError) as e:
            return Response(
                {"error": f"Paramètres GET invalides : {e}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = EstimateInputSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        return self._process_estimate(serializer.validated_data)
    
    def _process_estimate(self, validated_data: Dict) -> Response:
        """
        Traite estimation prix avec logique hiérarchique complète.
        
        Args:
            validated_data : Dict depuis EstimateInputSerializer avec :
                - depart_coords : [lat, lon]
                - arrivee_coords : [lat, lon]
                - depart_label, arrivee_label : str ou None
                - heure, meteo, type_zone, congestion_user : optionnels
                
        Returns:
            Response : JSON PredictionOutputSerializer
        """
        depart_coords = validated_data['depart_coords']
        arrivee_coords = validated_data['arrivee_coords']
        heure = validated_data.get('heure')
        meteo = validated_data.get('meteo')
        type_zone = validated_data.get('type_zone')
        congestion_user = validated_data.get('congestion_user')
        
        # TODO : Équipe implémente logique hiérarchique complète
        
        # Étape 1 : Fallbacks variables si manquantes
        # if heure is None:
        #     heure = determiner_tranche_horaire()
        # if meteo is None:
        #     meteo = openmeteo_client.get_current_weather_code(depart_coords[0], depart_coords[1])
        
        # Étape 2 : Identifier quartiers départ/arrivée pour filtrage
        # quartier_depart = self._get_quartier_from_coords(depart_coords)
        # quartier_arrivee = self._get_quartier_from_coords(arrivee_coords)
        
        # Étape 3 : check_exact_match
        # exact_trajets = self.check_exact_match(
        #     quartier_depart, quartier_arrivee, heure, meteo, type_zone
        # )
        # if exact_trajets:
        #     return self._build_exact_prediction(exact_trajets, depart_coords, arrivee_coords)
        
        # Étape 4 : check_similar_match
        # similar_trajets = self.check_similar_match(
        #     depart_coords, arrivee_coords, quartier_depart, quartier_arrivee, heure, meteo
        # )
        # if similar_trajets:
        #     return self._build_similar_prediction(similar_trajets, depart_coords, arrivee_coords)
        
        # Étape 5 : fallback_inconnu
        # estimations = self.fallback_inconnu(
        #     depart_coords, arrivee_coords, heure, meteo, type_zone
        # )
        # return self._build_inconnu_prediction(estimations)
        
        # Placeholder temporaire
        prix_standard = settings.PRIX_STANDARD_JOUR_CFA if heure in ['matin', 'apres-midi', 'soir'] else settings.PRIX_STANDARD_NUIT_CFA
        
        prediction_data = {
            'statut': 'inconnu',
            'prix_moyen': prix_standard,
            'prix_min': None,
            'prix_max': None,
            'estimations_supplementaires': {
                'distance_based': prix_standard * 0.93,  # -7% estimation basse
                'standardise': prix_standard,
                'zone_based': prix_standard * 0.97  # -3% estimation intermédiaire
            },
            'fiabilite': 0.5,
            'message': (
                "TODO équipe : Implémenter logique estimation hiérarchique complète. "
                "Cette réponse est un placeholder."
            ),
            'details_trajet': {
                'depart': validated_data.get('depart_label') or f"{depart_coords[0]:.4f}, {depart_coords[1]:.4f}",
                'arrivee': validated_data.get('arrivee_label') or f"{arrivee_coords[0]:.4f}, {arrivee_coords[1]:.4f}",
                'heure': heure,
                'meteo': meteo
            },
            'suggestions': [
                "Logique estimation non implémentée (coquille pour équipe).",
                "Ajoutez votre prix après trajet pour enrichir la BD."
            ]
        }
        
        serializer = PredictionOutputSerializer(data=prediction_data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def _get_quartier_from_coords(self, coords: List[float]) -> Dict:
        """
        Helper : Extrait quartier/ville/arrondissement depuis coords via Nominatim reverse-geocoding.
        
        Utilisé pour filtrage grossier des candidats BD avant vérification isochrones.
        
        Args:
            coords : [lat, lon]
            
        Returns:
            Dict : {
                'quartier': str ou None,
                'ville': str ou None,
                'arrondissement': str ou None,
                'departement': str ou None
            }
            
        Exemples :
            >>> info = self._get_quartier_from_coords([3.8547, 11.5021])
            >>> print(info)
            {'quartier': 'Ngoa-Ekelle', 'ville': 'Yaoundé', 'arrondissement': 'Yaoundé II', 'departement': 'Mfoundi'}
        """
        try:
            result = nominatim_client.reverse_geocode(lat=coords[0], lon=coords[1])
            if not result:
                return {'quartier': None, 'ville': None, 'arrondissement': None, 'departement': None}
            
            address = result.get('address', {})
            return {
                'quartier': address.get('suburb') or address.get('neighbourhood'),
                'ville': address.get('city') or address.get('town') or address.get('village'),
                'arrondissement': address.get('municipality') or address.get('county'),
                'departement': address.get('state_district') or address.get('state')
            }
        except Exception as e:
            logger.warning(f"_get_quartier_from_coords échec pour {coords}: {e}")
            return {'quartier': None, 'ville': None, 'arrondissement': None, 'departement': None}
    
    def check_similar_match(
        self,
        depart_coords: List[float],
        arrivee_coords: List[float],
        distance_mapbox: float,
        heure: Optional[str],
        meteo: Optional[int],
        type_zone: Optional[int],
        congestion_user: Optional[int]
    ) -> Optional[Dict]:
        """
        Recherche trajets similaires avec périmètres progressifs (2min→5min ou 50m→150m fallback).
        
        **LOGIQUE CENTRALE DU PROJET** : 
        Il n'y a PAS de distinction "exact vs similaire" - c'est un système de similarité avec 
        2 niveaux de périmètres + fallback sur variables (heure/météo différentes si pas de match).
        
        Workflow hiérarchique :
            
            1. FILTRAGE GROSSIER (Optimisation queries BD)
               - Extraire quartiers/arrondissement depuis depart_coords et arrivee_coords via Nominatim
               - Filtrer Trajet.objects.filter(
                   point_depart__quartier__in=[quartier, arrondissement],
                   point_arrivee__quartier__in=[quartier_arrivee, arrondissement_arrivee]
                 )
               - Cela réduit candidats de 1000+ à ~20-50 trajets à vérifier
            
            2. NIVEAU 1 : PÉRIMÈTRE ÉTROIT (isochrone 2min / cercle 50m fallback)
               a) Générer isochrones Mapbox 2 minutes autour de chaque point_depart candidat :
                  isochrone_depart = mapbox_client.get_isochrone(
                      coords=(pt_depart.coords_latitude, pt_depart.coords_longitude),
                      contours_minutes=[2],
                      profile='driving-traffic'
                  )
               b) Vérifier si depart_coords est DANS le polygone isochrone via Shapely :
                  from shapely.geometry import shape, Point as ShapelyPoint
                  polygon_depart = shape(isochrone_depart['features'][0]['geometry'])
                  if polygon_depart.contains(ShapelyPoint(depart_coords[1], depart_coords[0])):
                      # Match périmètre étroit départ ✓
               c) Répéter pour arrivee_coords vs. isochrones point_arrivee candidats
               d) Si isochrone Mapbox échoue (NoRoute Cameroun, routes manquantes) :
                  **FALLBACK cercle Haversine 50m** :
                  if haversine_distance(depart_coords, pt_depart.coords) <= 50:
                      # Match périmètre étroit départ ✓
               e) Si match DÉPART + ARRIVÉE dans périmètre étroit :
                  - Vérifier distance routière ±10% via Mapbox Matrix ou distance stockée
                  - Vérifier heure/météo EXACTES (même valeurs que demandées)
                  - Si OK : **MATCH ÉTROIT** → Prix direct SANS ajustement (fiabilité 0.9-0.95)
                  - Calculer moyenne/min/max des prix trajets matchés
                  - Retourner immédiatement avec statut='similaire_etroit'
            
            3. NIVEAU 2 : PÉRIMÈTRE ÉLARGI (isochrone 5min / cercle 150m fallback)
               - Si pas de match étroit, recommencer avec isochrones 5 minutes (ou cercles 150m)
               - Mêmes vérifications Shapely/Haversine
               - Si match DÉPART + ARRIVÉE dans périmètre élargi :
                 a) Calculer distances réelles via Mapbox Matrix API :
                    matrix_depart = mapbox_client.get_matrix(
                        coordinates=[(lat, lon) for depart_coords + trajets_candidats_departs],
                        sources=[0],  # Nouveau départ
                        destinations=[1, 2, ...]  # Départs BD
                    )
                    distance_extra_depart = matrix_depart['distances'][0][i]
                 b) Calculer ajustements prix :
                    - **Distance extra** : +settings.ADJUSTMENT_PRIX_PAR_KM * (dist_extra_km)
                      Ex : +50 CFA par km extra (si 200m extra → +10 CFA)
                    - **Congestion différente** : Si congestion_user fourni et > congestion_bd_moyen + 20 
                      → +10% (settings.ADJUSTMENT_CONGESTION_POURCENT)
                    - **Sinuosité** : Si trajet BD sinuosite_indice > 1.5 (routes tortueuses) 
                      → +20 CFA (settings.ADJUSTMENT_SINUOSITE_CFA)
                    - **Météo diff** : Si meteo demandée != meteo_bd → ±10% selon type
                      (soleil→pluie : +10%, pluie→soleil : -5%)
                    - **Heure diff** : Si heure demandée != heure_bd → ±50 CFA selon type
                      (jour→nuit : +50 CFA, nuit→jour : -30 CFA)
                 c) Calculer prix ajusté :
                    prix_base = moyenne(trajets_matchés.prix)
                    prix_ajusté = prix_base + ajust_distance + ajust_sinuosite + ajust_meteo + ajust_heure
                    prix_ajusté *= (1 + ajust_congestion_pourcent/100)
                 d) **MATCH ÉLARGI** → Retourner avec statut='similaire_elargi', fiabilité 0.7-0.8
            
            4. NIVEAU 3 : FALLBACK VARIABLES (si pas de match avec heure/météo exactes)
               - Recommencer recherche périmètres (étroit puis élargi) MAIS :
                 * Ignorer filtre heure (accepter toutes heures)
                 * Ignorer filtre météo (accepter toutes météos)
               - Si match trouvé :
                 * Appliquer ajustements standards heure/météo (voir ci-dessus)
                 * **Ajouter note dans réponse** : "Prix basé sur trajets à heure différente (nuit vs matin)"
                 * Retourner avec statut='similaire_variables_diff', fiabilité 0.6-0.7
            
            5. AUCUN MATCH → Return None (passage à fallback_inconnu)
        
        Args:
            depart_coords, arrivee_coords : [lat, lon] nouveau trajet
            distance_mapbox : Distance routière calculée pour nouveau trajet (mètres)
            heure, meteo, type_zone : Variables contextuelles demandées (peuvent être None)
            congestion_user : Embouteillages ressentis user 1-10 (optionnel)
            
        Returns:
            Dict ou None :
                {
                    'statut': 'similaire_etroit' | 'similaire_elargi' | 'similaire_variables_diff',
                    'prix_moyen': float,
                    'prix_min': float,
                    'prix_max': float,
                    'fiabilite': float (0.6-0.95),
                    'message': str,
                    'nb_trajets_utilises': int,
                    'details_trajet': {...},
                    'ajustements_appliques': {
                        'distance_extra_metres': int,
                        'ajustement_distance_cfa': float,
                        'ajustement_congestion_pourcent': int,
                        'ajustement_sinuosite_cfa': float,
                        'ajustement_meteo_cfa': float,
                        'ajustement_heure_cfa': float,
                        'facteur_ajustement_total': float,
                        'note_variables': str ou None  # Si heure/météo différentes
                    },
                    'suggestions': List[str]
                }
                
            None si aucun trajet similaire trouvé (passage à fallback_inconnu)
            
        Exemples :
            # Match étroit (2min/50m) avec heure/météo exactes
            >>> result = self.check_similar_match([3.8547, 11.5021], [3.8667, 11.5174], 5200, 'matin', 1, 0, None)
            >>> print(result)
            {
                'statut': 'similaire_etroit',
                'prix_moyen': 250.0,
                'prix_min': 200.0,
                'prix_max': 300.0,
                'fiabilite': 0.93,
                'message': 'Estimation basée sur 8 trajets très similaires (périmètre 2min).',
                'ajustements_appliques': {'distance_extra_metres': 0, 'facteur_ajustement_total': 1.0}
            }
            
            # Match élargi (5min/150m) avec ajustements
            >>> result = self.check_similar_match([3.8550, 11.5025], [3.8670, 11.5180], 5400, 'matin', 1, 0, 7)
            >>> print(result)
            {
                'statut': 'similaire_elargi',
                'prix_moyen': 270.0,
                'prix_min': 250.0,
                'prix_max': 290.0,
                'fiabilite': 0.78,
                'message': 'Estimation ajustée depuis 5 trajets similaires (+20 CFA pour 200m extra, +10% congestion).',
                'ajustements_appliques': {
                    'distance_extra_metres': 200,
                    'ajustement_distance_cfa': 20.0,
                    'ajustement_congestion_pourcent': 10,
                    'facteur_ajustement_total': 1.10
                }
            }
            
            # Match avec variables différentes (heure nuit au lieu de matin)
            >>> result = self.check_similar_match([3.8547, 11.5021], [3.8667, 11.5174], 5200, 'matin', 1, 0, None)
            >>> print(result)
            {
                'statut': 'similaire_variables_diff',
                'prix_moyen': 300.0,
                'fiabilite': 0.68,
                'message': 'Estimation basée sur trajets similaires à heure différente.',
                'ajustements_appliques': {
                    'ajustement_heure_cfa': 50.0,
                    'note_variables': 'Prix basé sur trajets de nuit (+50 CFA vs matin demandé)'
                }
            }
            
        Gestion edge cases :
            - Si isochrones Mapbox échouent (NoRoute, routes manquantes Cameroun) :
              **TOUJOURS fallback cercles Haversine** (50m/150m)
            - Si quartiers extraction échoue (Nominatim timeout) :
              Filtrer par ville ou skip filtrage (query full BD, plus lent mais exhaustif)
            - Si <2 trajets après filtrage :
              Log warning et return None immédiatement (éviter calculs isochrones inutiles)
            - Si Matrix API échoue (trop de candidats >25) :
              Batch en groupes de 25 ou fallback Haversine pour distances
              
        Constants settings utilisées :
            - settings.ISOCHRONE_MINUTES_ETROIT = 2
            - settings.ISOCHRONE_MINUTES_ELARGI = 5
            - settings.CIRCLE_RADIUS_ETROIT_M = 50
            - settings.CIRCLE_RADIUS_ELARGI_M = 150
            - settings.ADJUSTMENT_PRIX_PAR_KM = 50.0  # CFA par km extra
            - settings.ADJUSTMENT_CONGESTION_POURCENT = 10  # % par tranche 20 pts congestion
            - settings.ADJUSTMENT_SINUOSITE_CFA = 20.0  # CFA si sinuosité >1.5
            - settings.ADJUSTMENT_METEO_SOLEIL_PLUIE_POURCENT = 10  # +10% si pluie
            - settings.ADJUSTMENT_HEURE_JOUR_NUIT_CFA = 50  # +50 CFA si nuit
            - settings.SIMILARITY_DISTANCE_TOLERANCE_POURCENT = 10  # ±10% distance routière
        """
        # TODO : Équipe implémente logique similarité complète avec :
        # - Filtrage grossier par quartiers (Nominatim reverse-geocode)
        # - Génération isochrones Mapbox 2min + 5min (get_isochrone)
        # - Vérification containment Shapely (polygon.contains(point))
        # - Fallback cercles Haversine (haversine_distance <= 50m / 150m)
        # - Validation distances Matrix API (get_matrix)
        # - Calculs ajustements prix (distance, congestion, sinuosité, météo, heure)
        # - Fallback variables (ignorer filtres heure/météo si aucun match exact)
        # - Construction dict réponse complète
        pass
    
    def fallback_inconnu(
        self,
        depart_coords: List[float],
        arrivee_coords: List[float],
        heure: Optional[str],
        meteo: Optional[int],
        type_zone: Optional[int]
    ) -> Dict[str, float]:
        """
        Génère estimations pour trajet totalement inconnu (aucun similaire en BD).
        
        Retourne 3-4 estimations différentes pour donner choix à utilisateur :
            1. distance_based : Basé sur distance routière Mapbox et prix/km moyen BD
            2. standardise : Tarifs officiels Cameroun (300 CFA jour, 350 nuit)
            3. zone_based : Prix moyen dans arrondissement/ville (fallback large)
            4. ml_prediction : Prédiction ML via modèle entraîné (si disponible)
            
        Args:
            depart_coords, arrivee_coords : Coords [lat, lon]
            heure, meteo, type_zone : Variables contextuelles (peuvent être None)
            
        Returns:
            Dict : {
                'distance_based': float,
                'standardise': float,
                'zone_based': float,
                'ml_prediction': float ou None
            }
            
        Workflow :
            1. Calculer distance routière via Mapbox Directions
            2. Estimation distance_based :
                - Calculer prix/km moyen BD : Trajet.objects.aggregate(Avg('prix'), Avg('distance'))
                - prix_estim = (prix_moy / distance_moy) * distance_nouveau
                - Ajuster pour heure/météo (+10% nuit, +5% pluie)
            3. Estimation standardise :
                - Lire settings.PRIX_STANDARD_JOUR_CFA / PRIX_STANDARD_NUIT_CFA
                - Return prix selon heure
            4. Estimation zone_based :
                - Identifier ville/arrondissement via reverse-geocode coords
                - Calculer moyenne prix trajets dans cette zone (Trajet.objects.filter(...))
                - Si zone vide BD, fallback moyenne globale BD
            5. Estimation ML :
                - Appeler self.predict_prix_ml(distance, heure, meteo, type_zone, congestion, ...)
                - Si modèle non entraîné (pas assez données), return None
            6. Return dict avec toutes estimations
            
        Exemples :
            >>> estimations = self.fallback_inconnu(
            ...     [3.8547, 11.5021], [3.8667, 11.5174],
            ...     'matin', 1, 0
            ... )
            >>> print(estimations)
            {
                'distance_based': 280.0,
                'standardise': 300.0,
                'zone_based': 290.0,
                'ml_prediction': 285.0
            }
            
        Gestion manques :
            - Si Mapbox échoue distance, fallback Haversine * facteur sinuosité moyen (1.5)
            - Si BD vide (pas trajets), utiliser uniquement standardise
            - Si ML non entraîné, ml_prediction = None (géré dans serializer output)
        """
        # TODO : Équipe implémente estimations fallback complètes
        # TODO : Intégrer appels Mapbox Directions, agrégations Django, predict_prix_ml
        pass
    
    def predict_prix_ml(
        self,
        distance: float,
        heure: Optional[str],
        meteo: Optional[int],
        type_zone: Optional[int],
        congestion: Optional[float],
        sinuosite: Optional[float],
        nb_virages: Optional[int]
    ) -> Optional[float]:
        """
        Prédiction prix via modèle Machine Learning entraîné sur trajets BD.
        
        **FONCTION CŒUR ML - ÉQUIPE IMPLÉMENTE LOGIQUE COMPLÈTE**
        
        Modèle suggéré : Régression (scikit-learn RandomForestRegressor ou GradientBoosting)
        Features :
            - distance (float, mètres)
            - heure_encoded (int, 0-3 pour matin/apres-midi/soir/nuit)
            - meteo (int, 0-3)
            - type_zone (int, 0-2)
            - congestion (float, 0-100, remplacer None par moyenne si manque)
            - sinuosite (float, ≥1.0, remplacer None par 1.5 si manque)
            - nb_virages (int, remplacer None par 0)
            - jour_semaine (int, 0-6, déduit de heure si timestamp disponible)
            
        Workflow :
            1. Charger modèle depuis fichier (ex. 'ml_models/prix_model.pkl') via joblib
            2. Si modèle n'existe pas (pas encore entraîné), return None
            3. Préparer features : encoder heure (mapping str→int), gérer manques (fillna avec moyennes)
            4. Normaliser features si nécessaire (StandardScaler sauvegardé avec modèle)
            5. Prédire : model.predict([features_array])
            6. Return prix prédit (float)
            
        Entraînement (via task Celery, voir tasks.py) :
            1. Query tous trajets BD : Trajet.objects.all().values(...)
            2. Préparer DataFrame pandas avec features + target (prix)
            3. Split train/test (80/20)
            4. Entraîner modèle (ex. RandomForestRegressor(n_estimators=100, random_state=42))
            5. Évaluer metrics (MAE, RMSE, R²)
            6. Sauvegarder modèle + scaler via joblib.dump
            7. Logger infos (metrics, date entraînement)
            
        Args:
            distance, heure, meteo, type_zone, congestion, sinuosite, nb_virages : Features prédiction
            
        Returns:
            float : Prix prédit en CFA ou None si modèle indisponible
            
        Exemples :
            >>> prix_ml = self.predict_prix_ml(
            ...     distance=5200, heure='matin', meteo=1, type_zone=0,
            ...     congestion=45.0, sinuosite=2.3, nb_virages=7
            ... )
            >>> if prix_ml:
            ...     print(f"Prédiction ML : {prix_ml:.2f} CFA")
            
        Gestion erreurs :
            - Si modèle échoue (exception), logger error et return None (utiliser autres estimations)
            - Si features manquantes critiques (ex. distance=None), return None
            
        Note performance :
            - Avec 100+ trajets BD, R² attendu ~0.7-0.8
            - Avec 1000+ trajets, R² >0.85 possible
            - Ré-entraîner quotidiennement via Celery pour intégrer nouveaux trajets
        """
        # TODO : ÉQUIPE IMPLÉMENTE LOGIQUE ML COMPLÈTE
        # TODO : Charger modèle depuis fichier (gérer FileNotFoundError)
        # TODO : Encoder features, normaliser, prédire
        # TODO : Gérer exceptions (return None si erreur)
        pass
    
    def _get_quartier_from_coords(self, coords: List[float]) -> Optional[str]:
        """
        Identifie quartier depuis coordonnées via reverse-geocoding.
        Helper pour filtrage exact/similar.
        
        Args:
            coords : [lat, lon]
            
        Returns:
            str : Nom du quartier ou None si non trouvé
        """
        lat, lon = coords
        logger.debug(f"_get_quartier_from_coords: Reverse-geocoding {lat}, {lon}")
        
        # Appeler Nominatim pour reverse-geocoding
        reverse_data = nominatim_client.reverse_geocode(lat, lon)
        
        if reverse_data:
            metadata = nominatim_client.extract_quartier_ville(reverse_data)
            quartier = metadata.get('quartier')
            
            if quartier:
                logger.debug(f"Quartier identifié : {quartier}")
                return quartier
            else:
                logger.debug("Quartier non trouvé dans metadata Nominatim")
                return None
        else:
            logger.warning("Reverse-geocoding Nominatim échoué")
            return None


class AddTrajetView(APIView):
    """
    View pour ajout trajet réel par utilisateur : POST /api/add-trajet/
    
    Workflow :
        1. Valider inputs via TrajetSerializer (nested Points)
        2. Appliquer prétraitements :
            - Si coords random (pas POI nommé), convertir via Map Matching + Search Mapbox
            - Appeler Mapbox Directions pour distance, enrichissements (congestion, sinuosité)
            - Fallbacks variables optionnelles (heure, météo, type_zone)
        3. Sauvegarder Points (ou récupérer si existent déjà)
        4. Créer Trajet avec tous champs enrichis
        5. Retourner Trajet créé avec HTTP 201
        
    Exemples requête :
        POST /api/add-trajet/
        {
            "point_depart": {
                "coords_latitude": 3.8547,
                "coords_longitude": 11.5021,
                "label": "Polytechnique Yaoundé"
            },
            "point_arrivee": {
                "coords_latitude": 3.8667,
                "coords_longitude": 11.5174,
                "label": "Carrefour Ekounou"
            },
            "prix": 200,
            "heure": "matin",
            "meteo": 1,
            "congestion_user": 5
        }
        
    Réponse 201 :
        {
            "id": 42,
            "point_depart": {...},
            "point_arrivee": {...},
            "distance": 5212.5,
            "prix": 200,
            ...tous champs enrichis...
            "date_ajout": "2023-11-05T14:30:00Z"
        }
    """
    
    def post(self, request):
        """Endpoint POST /api/add-trajet/"""
        serializer = TrajetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Création via serializer (gère enrichissements dans create())
        try:
            trajet = serializer.save()
            logger.info(f"Trajet créé : {trajet}")
            return Response(TrajetSerializer(trajet).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Erreur création trajet : {e}")
            return Response(
                {"error": f"Erreur création trajet : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class HealthCheckView(APIView):
    """
    View santé API : GET /api/health/
    
    Vérifie :
        - Django répond
        - BD accessible
        - Redis/Celery connecté
        - APIs externes (Mapbox, Nominatim, OpenMeteo) accessibles (optionnel)
        
    Retourne :
        {
            "status": "healthy",
            "timestamp": "2023-11-05T14:30:00Z",
            "checks": {
                "database": "ok",
                "redis": "ok",
                "mapbox": "ok",
                "nominatim": "ok",
                "openmeteo": "ok"
            }
        }
    """
    
    def get(self, request):
        from django.db import connection
        from django.core.cache import cache
        
        checks = {}
        
        # Check BD
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks['database'] = 'ok'
        except Exception as e:
            checks['database'] = f'error: {e}'
        
        # Check Redis (cache)
        try:
            cache.set('health_check', 'ok', 10)
            checks['redis'] = 'ok' if cache.get('health_check') == 'ok' else 'error'
        except Exception as e:
            checks['redis'] = f'error: {e}'
        
        # TODO : Checks APIs externes (optionnels, peuvent être lents)
        # try:
        #     mapbox_test = mapbox_client.get_directions([[11.50, 3.85], [11.51, 3.86]])
        #     checks['mapbox'] = 'ok' if mapbox_test else 'error'
        # except:
        #     checks['mapbox'] = 'error'
        
        checks['mapbox'] = 'not_checked'
        checks['nominatim'] = 'not_checked'
        checks['openmeteo'] = 'not_checked'
        
        overall_status = 'healthy' if all(v == 'ok' or v == 'not_checked' for v in checks.values()) else 'degraded'
        
        return Response({
            'status': overall_status,
            'timestamp': timezone.now().isoformat(),
            'checks': checks
        })

