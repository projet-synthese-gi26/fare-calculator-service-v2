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
from drf_spectacular.utils import extend_schema
from django.utils import timezone
from django.db.models import Avg, Min, Max, Count, Q
from django.conf import settings
from datetime import datetime
import logging
from typing import Dict, List, Optional, Tuple

from .models import Point, Trajet, ApiKey, Publicite
from .serializers import (
    PointSerializer,
    TrajetSerializer,
    EstimateInputSerializer,
    PredictionOutputSerializer,
    HealthCheckSerializer,
    PubliciteSerializer
)
from .utils import (
    mapbox_client,
    nominatim_client,
    openmeteo_client,
    haversine_distance,
    determiner_tranche_horaire
)
from .utils.calculations import calculer_sinuosite_base, calculer_virages_par_km

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


class TrajetViewSet(viewsets.ModelViewSet):
    """
    ViewSet CRUD pour Trajets (Lecture et Création uniquement).
    
    Endpoints :
        GET /api/trajets/ : Liste tous trajets
        POST /api/trajets/ : Créer nouveau trajet
        GET /api/trajets/{id}/ : Détail trajet
        GET /api/trajets/?heure=matin : Filtrage par heure
        GET /api/trajets/?meteo=1 : Filtrage par météo
        GET /api/trajets/?type_zone=0 : Filtrage par type zone
        
    Note: Modification (PUT/PATCH) et Suppression (DELETE) désactivées via API.
    Utilisé pour contribution communautaire (POST depuis frontend) et admin/debug.
    """
    queryset = Trajet.objects.all().select_related('point_depart', 'point_arrivee')
    serializer_class = TrajetSerializer
    http_method_names = ['get', 'post', 'head', 'options']
    filterset_fields = ['heure', 'meteo', 'type_zone', 'route_classe_dominante']
    search_fields = ['point_depart__label', 'point_arrivee__label']
    ordering_fields = ['date_ajout', 'prix', 'distance', 'point_depart__label']
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


class PubliciteViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet lecture seule pour les publicités actives.
    
    Endpoints :
        GET /api/publicites/ : Liste toutes les pubs actives
        GET /api/publicites/{id}/ : Détail d'une pub
    """
    queryset = Publicite.objects.filter(is_active=True)
    serializer_class = PubliciteSerializer
    pagination_class = None  # Pas de pagination pour les pubs


class EstimateView(APIView):
    """
    View principale pour estimation prix trajet : POST/GET /api/estimate/
    
    Accepte :
        POST avec JSON body (EstimateInputSerializer)
        GET avec query params (?depart_lat=X&depart_lon=Y&arrivee_lat=Z...)
        
    Workflow estimation hiérarchique :
        1. Valider inputs via EstimateInputSerializer (conversion nom->coords si nécessaire)
        2. Appliquer fallbacks variables optionnelles (heure, météo, type_zone) si manquantes
        3. Filtrer candidats par quartiers départ/arrivée via reverse-geocoding (optimisation)
        4. check_similar_match : Recherche trajets similaires avec 2 périmètres
            a) Périmètre ÉTROIT (isochrone 2min / cercle 50m fallback)
               - Vérifier points départ/arrivée dans isochrones Mapbox 2 minutes
               - Si isochrones échouent (routes manquantes Cameroun) -> cercles Haversine 50m
               - Si match + distance ±10% : PRIX DIRECT sans ajustement (fiabilité 0.9-0.95)
               - Moyenne/min/max des prix trouvés
            b) Périmètre ÉLARGI (isochrone 5min / cercle 150m fallback)
               - Mêmes vérifications avec périmètres plus larges
               - Si match : Calculer ajustements via Mapbox Matrix API
                 * Distance extra (Matrix pour distance réelle départ->départ_bd, arrivée->arrivée_bd)
                 * Ajustement prix : +50 CFA par km extra (configurable settings.ADJUSTMENT_PRIX_PAR_KM)
                 * Congestion différente : +10% si user signale embouteillage (congestion_user>7)
                 * Sinuosité différente : +20 CFA si indice>1.5 (routes tortueuses)
               - PRIX AJUSTÉ (fiabilité 0.7-0.8)
            c) Fallback VARIABLES (si pas de match avec heure/météo exactes)
               - Chercher même périmètre mais avec heure différente (ex : matin->nuit)
               - Chercher avec météo différente (ex : soleil->pluie)
               - Appliquer ajustements standards :
                 * Heure diff : +50 CFA si jour->nuit, -30 CFA si nuit->jour
                 * Météo diff : +10% si soleil->pluie, -5% si pluie->soleil
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
    
    serializer_class = EstimateInputSerializer

    @extend_schema(
        request=EstimateInputSerializer, 
        responses=PredictionOutputSerializer,
        description="""
        Endpoint principal d'estimation de prix.
        
        **Flexibilité des paramètres :**
        - Les coordonnées (`lat`/`lon`) sont **optionnelles** si un nom de lieu (`label`) est fourni.
        - L'API effectuera un géocodage automatique si nécessaire.
        - Les paramètres `heure`, `meteo`, `type_zone` sont **optionnels** (détectés automatiquement si omis).
        
        **Exemple minimaliste (Noms de lieux uniquement) :**
        ```json
        {
            "depart": {"label": "Poste Centrale"},
            "arrivee": {"label": "Mvan"}
        }
        ```
        """
    )
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
    
    # Instance MapboxClient pour les appels API
    mapbox_client = mapbox_client
    
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
        depart_label = validated_data.get('depart_label')
        arrivee_label = validated_data.get('arrivee_label')
        heure = validated_data.get('heure')
        meteo = validated_data.get('meteo')
        type_zone = validated_data.get('type_zone')
        congestion_user = validated_data.get('congestion_user')
        qualite_trajet = validated_data.get('qualite_trajet')
        use_ml_only = validated_data.get('use_ml_only', False)
        
        logger.info(f"[ESTIMATION] Depart {depart_coords} -> Arrivee {arrivee_coords}")
        logger.info(f"   Labels: '{depart_label}' -> '{arrivee_label}'")
        logger.info(f"   Variables: heure={heure}, meteo={meteo}, type_zone={type_zone}, congestion={congestion_user}, qualite={qualite_trajet}, use_ml_only={use_ml_only}")
        
        # ============================================================
        # ÉTAPE 1 : FALLBACKS AUTOMATIQUES POUR VARIABLES MANQUANTES
        # ============================================================
        
        # Fallback heure : utiliser datetime.now() -> tranche
        if heure is None:
            heure = determiner_tranche_horaire()
            logger.info(f"[FALLBACK] Heure auto-detectee : {heure}")
        
        # Fallback météo : appeler OpenMeteo API
        if meteo is None:
            try:
                code_meteo = openmeteo_client.get_current_weather_code(depart_coords[0], depart_coords[1])
                if code_meteo is not None:
                    meteo = code_meteo
                    logger.info(f"[FALLBACK] Meteo auto-detectee via OpenMeteo : code {meteo}")
                else:
                    meteo = 0  # Soleil par défaut
                    logger.warning("[FALLBACK] OpenMeteo echec, meteo=0 (soleil) par defaut")
            except Exception as e:
                meteo = 0
                logger.warning(f"[FALLBACK] Erreur OpenMeteo ({e}), meteo=0 par defaut")
        
        # ============================================================
        # ÉTAPE 2 : ENRICHIR LES LABELS VIA REVERSE-GEOCODING SI MANQUANTS
        # ============================================================
        
        depart_metadata = {'label': depart_label, 'quartier': None, 'ville': None, 'arrondissement': None}
        arrivee_metadata = {'label': arrivee_label, 'quartier': None, 'ville': None, 'arrondissement': None}
        
        # Enrichir départ via Nominatim si label manquant
        if not depart_label:
            try:
                reverse_data = nominatim_client.reverse_geocode(depart_coords[0], depart_coords[1])
                if reverse_data:
                    depart_metadata['label'] = reverse_data.get('display_name', '').split(',')[0] or f"Point ({depart_coords[0]:.4f}, {depart_coords[1]:.4f})"
                    extracted = nominatim_client.extract_quartier_ville(reverse_data)
                    depart_metadata.update(extracted)
                    logger.info(f"[GEOCODE] Depart enrichi : {depart_metadata['label']} ({depart_metadata.get('quartier', 'N/A')})")
                else:
                    depart_metadata['label'] = f"Point ({depart_coords[0]:.4f}, {depart_coords[1]:.4f})"
            except Exception as e:
                depart_metadata['label'] = f"Point ({depart_coords[0]:.4f}, {depart_coords[1]:.4f})"
                logger.warning(f"[GEOCODE] Erreur Nominatim depart: {e}")
        
        # Enrichir arrivée via Nominatim si label manquant
        if not arrivee_label:
            try:
                reverse_data = nominatim_client.reverse_geocode(arrivee_coords[0], arrivee_coords[1])
                if reverse_data:
                    arrivee_metadata['label'] = reverse_data.get('display_name', '').split(',')[0] or f"Point ({arrivee_coords[0]:.4f}, {arrivee_coords[1]:.4f})"
                    extracted = nominatim_client.extract_quartier_ville(reverse_data)
                    arrivee_metadata.update(extracted)
                    logger.info(f"[GEOCODE] Arrivee enrichie : {arrivee_metadata['label']} ({arrivee_metadata.get('quartier', 'N/A')})")
                else:
                    arrivee_metadata['label'] = f"Point ({arrivee_coords[0]:.4f}, {arrivee_coords[1]:.4f})"
            except Exception as e:
                arrivee_metadata['label'] = f"Point ({arrivee_coords[0]:.4f}, {arrivee_coords[1]:.4f})"
                logger.warning(f"[GEOCODE] Erreur Nominatim arrivee: {e}")
        
        # ============================================================
        # ÉTAPE 3 : CALCUL DISTANCE/DURÉE VIA MAPBOX DIRECTIONS
        # ============================================================
        
        distance_metres = None
        duree_secondes = None
        congestion_mapbox = None
        route_classe = None
        sinuosite_indice = None
        nb_virages_calc = None
        
        try:
            logger.info("[MAPBOX] Appel Directions API...")
            
            # Mapbox attend [lon, lat]
            coords_mapbox = [
                [depart_coords[1], depart_coords[0]],
                [arrivee_coords[1], arrivee_coords[0]]
            ]
            
            directions = mapbox_client.get_directions(
                coordinates=coords_mapbox,
                profile='driving-traffic',
                annotations=['congestion', 'duration', 'distance'],
                steps=True
            )
            
            if directions and directions.get('code') == 'Ok' and directions.get('routes'):
                route = directions['routes'][0]
                distance_metres = route.get('distance', 0)
                duree_secondes = route.get('duration', 0)
                
                # Extraire congestion moyenne
                congestion_mapbox = mapbox_client.extract_congestion_moyen(directions)
                
                # Extraire classe route dominante
                route_classe = mapbox_client.extract_route_classe_dominante(directions)

                # Calculer sinuosité (distance route vs haversine)
                sinuosite_indice = calculer_sinuosite_base(
                    distance_metres,
                    depart_coords[0],
                    depart_coords[1],
                    arrivee_coords[0],
                    arrivee_coords[1]
                )

                maneuvers = []
                for leg in route.get('legs', []):
                    for step in leg.get('steps', []):
                        maneuver = step.get('maneuver')
                        if maneuver:
                            maneuvers.append(maneuver)
                if maneuvers:
                    nb_virages_calc, _ = calculer_virages_par_km(maneuvers, distance_metres)
                
                logger.info(f"[MAPBOX] Distance: {distance_metres:.0f}m ({distance_metres/1000:.2f}km)")
                logger.info(f"[MAPBOX] Duree: {duree_secondes:.0f}s ({duree_secondes/60:.1f}min)")
                logger.info(f"[MAPBOX] Congestion: {congestion_mapbox}, Classe route: {route_classe}")
            else:
                raise ValueError("Pas de route trouvee")
                
        except Exception as e:
            logger.warning(f"[MAPBOX] Erreur ({e}) - fallback Haversine")
            
            # Fallback Haversine - IMPORTANT: garder la distance ligne droite séparée
            distance_ligne_droite = haversine_distance(
                depart_coords[0], depart_coords[1],
                arrivee_coords[0], arrivee_coords[1]
            )
            # Estimer distance route (coefficient sinuosité urbaine typique)
            distance_metres = distance_ligne_droite * 1.3
            
            duree_secondes = distance_metres / 8.33  # ~30 km/h
            congestion_mapbox = 50.0  # Valeur par défaut urbaine
            
            # Sinuosité fallback : valeur par défaut urbaine (pas de calcul possible)
            # On ne peut pas calculer la vraie sinuosité sans données Mapbox
            sinuosite_indice = 1.3  # Valeur typique urbaine (=coefficient utilisé)
            nb_virages_calc = int(distance_metres / 500) if distance_metres else None
            
            logger.info(f"[HAVERSINE] Distance ligne droite: {distance_ligne_droite:.0f}m, Distance estimée: {distance_metres:.0f}m, Duree: {duree_secondes:.0f}s")
        
        # Fallback type_zone si non fourni
        if type_zone is None:
            if route_classe in ['motorway', 'trunk', 'primary']:
                type_zone = 0  # Urbaine
            elif route_classe in ['secondary', 'tertiary']:
                type_zone = 1  # Mixte
            else:
                type_zone = 0  # Urbaine par défaut pour Yaoundé
            logger.info(f"[FALLBACK] Type zone deduit : {type_zone}")
        
        # ============================================================
        # ÉTAPE 4 : RECHERCHE TRAJETS SIMILAIRES (HIÉRARCHIE 2D)
        # ============================================================
        
        similar_result = None
        if not use_ml_only:
            similar_result = self.check_similar_match(
                depart_coords=depart_coords,
                arrivee_coords=arrivee_coords,
                distance_mapbox=distance_metres,
                heure=heure,
                meteo=meteo,
                type_zone=type_zone,
                congestion_user=congestion_user
            )
        else:
            logger.info("[ESTIMATION] Mode ML-only active. Skip recherche BD.")
        
        # ============================================================
        # ÉTAPE 5 : CONSTRUIRE LA RÉPONSE
        # ============================================================
        
        # Structure détails trajet complète
        details_trajet = {
            'depart': {
                'label': depart_metadata['label'],
                'coords': depart_coords,
                'quartier': depart_metadata.get('quartier'),
                'ville': depart_metadata.get('ville')
            },
            'arrivee': {
                'label': arrivee_metadata['label'],
                'coords': arrivee_coords,
                'quartier': arrivee_metadata.get('quartier'),
                'ville': arrivee_metadata.get('ville')
            },
            'distance_metres': distance_metres,
            'duree_secondes': duree_secondes,
            'heure': heure,
            'meteo': meteo,
            'meteo_label': {0: 'Soleil', 1: 'Pluie legere', 2: 'Pluie forte', 3: 'Orage'}.get(meteo, 'Inconnu'),
            'type_zone': type_zone,
            'type_zone_label': {0: 'Urbaine', 1: 'Mixte', 2: 'Rurale'}.get(type_zone, 'Inconnue'),
            'congestion_mapbox': congestion_mapbox,
            'sinuosite_indice': sinuosite_indice,
            'nb_virages_estimes': nb_virages_calc,
            'route_classe': route_classe,
            'qualite_trajet': qualite_trajet
        }
        
        # ============================================================
        # ÉTAPE 4.5 : PRÉDICTION ML SYSTÉMATIQUE
        # ============================================================
        
        ml_prediction_val = self.predict_prix_ml(
            distance=distance_metres,
            heure=heure,
            meteo=meteo,
            type_zone=type_zone,
            congestion=congestion_mapbox,
            sinuosite=sinuosite_indice,
            nb_virages=nb_virages_calc,
            coords_depart=depart_coords,
            coords_arrivee=arrivee_coords,
            duree=duree_secondes / 60.0 if duree_secondes else None,
            qualite_trajet=qualite_trajet
        )
        
        ml_details = {
            'ml_prediction': ml_prediction_val,
            'features_utilisees': {
                'distance_metres': distance_metres,
                'duree_secondes': duree_secondes,
                'congestion': congestion_mapbox,
                'sinuosite': sinuosite_indice,
                'nb_virages': nb_virages_calc,
                'heure': heure,
                'meteo': meteo,
                'type_zone': type_zone,
                'qualite_trajet': qualite_trajet
            }
        }
        
        if similar_result:
            # ========== CAS TRAJET SIMILAIRE TROUVÉ ==========
            logger.info(f"[MATCH] Trajets similaires trouves ! Statut: {similar_result['statut']}")
            
            # Appliquer ajustement congestion POST-similarité si congestion_user fourni
            prix_final = similar_result['prix_moyen']
            ajustements = similar_result.get('ajustements_appliques', {})
            
            if congestion_user and congestion_user > 7:
                # Embouteillage signalé par user -> +10%
                ajust_congestion = int(prix_final * 0.10)
                prix_final += ajust_congestion
                ajustements['ajustement_congestion_cfa'] = ajust_congestion
                ajustements['note_congestion'] = f"+{ajust_congestion} CFA (embouteillage signale niveau {congestion_user}/10)"
                logger.info(f"[AJUST] Congestion user {congestion_user} -> +{ajust_congestion} CFA")
            
            # Arrondir vers classe valide
            prix_final = self._arrondir_prix_vers_classe(prix_final)
            
            # ============================================================
            # ÉTAPE 6 : AJUSTEMENT RL (Reinforcement Learning)
            # ============================================================
            try:
                from .ml.rl_agent import FareAdjustmentAgent
                rl_agent = FareAdjustmentAgent()
                rl_factor = rl_agent.predict_action(heure, meteo, type_zone)
                
                if rl_factor != 0.0:
                    ajustement_rl = int(prix_final * rl_factor)
                    prix_final += ajustement_rl
                    ajustements['ajustement_rl'] = ajustement_rl
                    ajustements['note_rl'] = f"{'+' if rl_factor > 0 else ''}{int(rl_factor*100)}% (Ajustement intelligent)"
                    logger.info(f"[RL] Facteur {rl_factor} -> Ajustement {ajustement_rl} CFA")
                    
                    # Re-arrondir après ajustement RL
                    prix_final = self._arrondir_prix_vers_classe(prix_final)
            except Exception as e:
                logger.error(f"[RL] Erreur prediction agent: {e}")
            
            prediction_data = {
                'statut': similar_result['statut'],
                'prix_moyen': prix_final,
                'prix_min': similar_result.get('prix_min'),
                'prix_max': similar_result.get('prix_max'),
                'distance': distance_metres,
                'duree': duree_secondes,
                'fiabilite': similar_result['fiabilite'],
                'message': similar_result['message'],
                'nb_trajets_utilises': similar_result.get('nb_trajets_matches', 0),
                'details_trajet': details_trajet,
                'ajustements_appliques': ajustements,
                'estimations_supplementaires': ml_details,
                'suggestions': [
                    f"Estimation basee sur {similar_result.get('nb_trajets_matches', 0)} trajets similaires.",
                    "Ajoutez votre prix reel apres le trajet pour ameliorer les estimations."
                ]
            }
            
        else:
            # ========== CAS TRAJET INCONNU -> FALLBACK ==========
            logger.info("[FALLBACK] Aucun trajet similaire - utilisation estimations fallback")
            
            # Appeler fallback_inconnu pour les 4 estimations
            # Note: fallback_inconnu recalcule en interne, on pourrait optimiser
            # mais on garde la structure pour compatibilité
            estimations = ml_details
            
            ml_price = ml_prediction_val
            if ml_price is not None:
                prix_moyen = self._arrondir_prix_vers_classe(ml_price)
            else:
                prix_moyen = settings.PRIX_STANDARD_NUIT_CFA if heure == 'nuit' else settings.PRIX_STANDARD_JOUR_CFA
                prix_moyen = self._arrondir_prix_vers_classe(prix_moyen)

            classes = settings.PRIX_CLASSES_CFA
            idx = classes.index(prix_moyen) if prix_moyen in classes else 0
            prix_min = classes[max(0, idx - 1)]
            prix_max = classes[min(len(classes) - 1, idx + 1)]

            prediction_data = {
                'statut': 'inconnu',
                'prix_moyen': prix_moyen,
                'prix_min': prix_min,
                'prix_max': prix_max,
                'distance': distance_metres,
                'duree': duree_secondes,
                'estimations_supplementaires': estimations,
                'fiabilite': 0.55 if ml_price is not None else 0.3,
                'message': (
                    "Trajet inconnu dans notre base. Estimation ML prioritaire avec transparence des features. "
                    "Ajoutez votre prix reel apres course pour enrichir les donnees communautaires."
                ),
                'details_trajet': details_trajet,
                'ajustements_appliques': {
                    'note': 'Aucun ajustement (pas de trajets similaires en BD)'
                },
                'suggestions': [
                    f"Distance calculee : {distance_metres/1000:.2f} km",
                    f"Duree estimee : {duree_secondes/60:.1f} minutes",
                    "Fiabilite faible : negociez prudemment",
                    "Votre contribution enrichira les estimations futures !"
                ]
            }
        
        logger.info(f"[RESPONSE] Statut={prediction_data['statut']}, Prix={prediction_data['prix_moyen']} CFA, Fiabilite={prediction_data['fiabilite']}")
        
        serializer = PredictionOutputSerializer(data=prediction_data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    def _get_quartier_from_coords(self, coords: List[float]) -> Dict:
        """
        Helper : Extrait la PLUS PETITE unité administrative depuis coords via Nominatim.
        
        On récupère toutes les unités disponibles (commune/quartier/suburb/neighbourhood)
        pour maximiser les chances de filtrage grossier efficace avant isochrones.
        
        Args:
            coords : [lat, lon]
            
        Returns:
            Dict : {
                'commune': str ou None,  # Plus petite unité (suburb, neighbourhood, village)
                'quartier': str ou None,  # Alias commune (compatibilité)
                'ville': str ou None,
                'arrondissement': str ou None,  # Municipality/county/city_district
                'departement': str ou None
            }
            
        Exemples :
            >>> info = self._get_quartier_from_coords([3.8547, 11.5021])
            >>> print(info)
            {'commune': 'Ngoa-Ekelle', 'quartier': 'Ngoa-Ekelle', 'ville': 'Yaoundé', 
             'arrondissement': 'Yaoundé II', 'departement': 'Mfoundi'}
        """
        try:
            result = nominatim_client.reverse_geocode(lat=coords[0], lon=coords[1], zoom=18)
            if not result:
                return {'commune': None, 'quartier': None, 'ville': None, 'arrondissement': None, 'departement': None}
            
            address = result.get('address', {})
            
            # Récupérer la PLUS PETITE unité disponible (ordre priorité)
            commune = (
                address.get('suburb') or 
                address.get('neighbourhood') or 
                address.get('hamlet') or 
                address.get('village') or
                address.get('quarter')  # Vérifier si Nominatim utilise "quarter" pour Cameroun
            )
            
            return {
                'commune': commune,
                'quartier': commune,  # Alias pour compatibilité code existant
                'ville': address.get('city') or address.get('town') or address.get('village'),
                'arrondissement': (
                    address.get('municipality') or 
                    address.get('county') or 
                    address.get('city_district')
                ),
                'departement': address.get('state_district') or address.get('state')
            }
        except Exception as e:
            logger.warning(f"_get_quartier_from_coords échec pour {coords}: {e}")
            return {'commune': None, 'quartier': None, 'ville': None, 'arrondissement': None, 'departement': None}
    
    def _arrondir_prix_vers_classe(self, prix: float) -> int:
        """
        Arrondit un prix calculé vers la classe de prix valide la plus proche.
        
        Les prix taxis Cameroun appartiennent à des tranches fixes (18 classes) :
        [100, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000]
        
        Args:
            prix : Prix calculé (float, peut être 247.8 ou 312.5 par exemple)
            
        Returns:
            int : Classe de prix la plus proche (ex: 247.8 -> 250, 312.5 -> 300)
            
        Exemples:
            >>> self._arrondir_prix_vers_classe(247.8)
            250
            >>> self._arrondir_prix_vers_classe(312.5)
            300
            >>> self._arrondir_prix_vers_classe(75.0)
            100  # Prix minimum
            >>> self._arrondir_prix_vers_classe(2500.0)
            2000  # Prix maximum
        """
        import numpy as np
        
        # Utiliser les classes définies dans settings
        classes = settings.PRIX_CLASSES_CFA
        
        # Clip prix entre min et max
        prix = max(classes[0], min(prix, classes[-1]))
        
        # Trouver classe la plus proche
        idx = np.argmin([abs(prix - classe) for classe in classes])
        return classes[idx]
    
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
        Recherche trajets similaires avec hiérarchie correcte : périmètres (étroit->élargi) × variables (exactes->différentes).
        
        **LOGIQUE CENTRALE CORRIGÉE** : 
        Système de recherche avec 2 DIMENSIONS :
        - **DIMENSION 1** : Périmètres géographiques (ÉTROIT 2min/50m -> ÉLARGI 5min/150m)
        - **DIMENSION 2** : Variables contextuelles (EXACTES heure/météo -> DIFFÉRENTES)
        
        **HIÉRARCHIE VRAIE** (du plus précis au moins précis) :
        
        1. ✅ **PÉRIMÈTRE ÉTROIT + Variables EXACTES** (inclut matchs EXACTS si coords identiques)
           -> Si trouvé : Prix DIRECT sans ajustement distance (fiabilité 0.95)
           
        2. ✅ **PÉRIMÈTRE ÉTROIT + Variables DIFFÉRENTES** (heure/météo différentes)
           -> Si trouvé : Prix avec ajustement heure/météo + NOTE dans réponse (fiabilité 0.85)
           -> Ex : "Polytech-Kennedy nuit sans pluie" trouve "Polytech-Kennedy jour avec pluie"
           -> Note : "Prix basé sur trajets de jour (+50 CFA vs nuit), avec pluie (-5%)"
           
        3. ✅ **PÉRIMÈTRE ÉLARGI + Variables EXACTES**
           -> Si trouvé : Prix avec ajustement DISTANCE uniquement (fiabilité 0.75)
           -> Ajustement distance bidirectionnel : +50 CFA/km si plus long, -50 CFA/km si plus court
           
        4. ✅ **PÉRIMÈTRE ÉLARGI + Variables DIFFÉRENTES**
           -> Si trouvé : Prix avec ajustements DISTANCE + heure/météo (fiabilité 0.65)
           
        5. ❌ **AUCUN MATCH** -> Return None -> Passage fallback_inconnu (modèle ML)
        
        **IMPORTANT** : 
        - **Ajustement CONGESTION** : N'est PAS fait ici ! Se fait À LA FIN de toute prédiction
          (voir _process_estimate après retour de cette fonction)
        - **Ajustement DISTANCE** : Seul ajustement calculé ici, bidirectionnel (+ ou -)
        - **Ajustement heure/météo** : Seulement si variables différentes trouvées
        
        Workflow détaillé :
            
            1. FILTRAGE GROSSIER (Optimisation queries BD)
               - Extraire quartiers/arrondissement depuis depart_coords et arrivee_coords via Nominatim
               - Filtrer Trajet.objects.filter(
                   point_depart__quartier__in=[quartier, arrondissement],
                   point_arrivee__quartier__in=[quartier_arrivee, arrondissement_arrivee]
                 )
               - Cela réduit candidats de 1000+ à ~20-50 trajets à vérifier
            
            2. NIVEAU 1A : PÉRIMÈTRE ÉTROIT + Variables EXACTES
               a) Générer isochrones Mapbox 2 minutes (ou fallback cercles 50m si Mapbox échoue)
               b) Filtrer trajets BD par heure EXACTE et meteo EXACTE
               c) Vérifier containment isochrone/cercle pour départ ET arrivée
               d) Vérifier distance routière ±10%
               e) Si match : **Prix DIRECT**, fiabilité 0.95, statut='exact'
                  (Cas inclut matchs EXACTS si coords identiques)
            
            3. NIVEAU 1B : PÉRIMÈTRE ÉTROIT + Variables DIFFÉRENTES
               a) Reprendre isochrones 2 minutes / cercles 50m du niveau 1A
               b) **IGNORER filtres heure/météo** (accepter toutes valeurs)
               c) Vérifier containment + distance ±10%
               d) Si match : Calculer ajustements heure/météo :
                  - Heure différente : +50 CFA si jour->nuit, -30 CFA si nuit->jour
                    (settings.ADJUSTMENT_HEURE_JOUR_NUIT_CFA)
                  - Météo différente : +10% si soleil->pluie, -5% si pluie->soleil
                    (settings.ADJUSTMENT_METEO_SOLEIL_PLUIE_POURCENT)
               e) **Ajouter NOTE dans réponse** : 
                  "Prix basé sur trajets à heure différente (jour vs nuit demandée, +50 CFA)"
               f) Retourner statut='similaire_variables_diff_etroit', fiabilité 0.85
            
            4. NIVEAU 2A : PÉRIMÈTRE ÉLARGI + Variables EXACTES
               a) Générer isochrones Mapbox 5 minutes (ou fallback cercles 150m)
               b) Filtrer par heure EXACTE et meteo EXACTE
               c) Vérifier containment + distance ±20% (tolérance plus large)
               d) Si match : Calculer ajustement DISTANCE via Matrix API :
                  - Calculer distance extra réelle : matrix_depart + matrix_arrivee
                  - **Ajustement bidirectionnel** :
                    * Si distance_extra > 0 : +settings.PRIX_AJUSTEMENT_PAR_KM par km (50 CFA/km par défaut)
                    * Si distance_extra < 0 : -settings.PRIX_AJUSTEMENT_PAR_KM par km
                  - Ex : Trajet demandé 5.2km, BD 5.4km -> -0.2km -> -10 CFA (réduit prix)
                  - Ex : Trajet demandé 5.6km, BD 5.4km -> +0.2km -> +10 CFA (augmente prix)
               e) Retourner statut='similaire_elargi', fiabilité 0.75
            
            5. NIVEAU 2B : PÉRIMÈTRE ÉLARGI + Variables DIFFÉRENTES
               a) Reprendre isochrones 5 minutes / cercles 150m
               b) **IGNORER filtres heure/météo**
               c) Vérifier containment + distance ±20%
               d) Si match : Ajustements DISTANCE + heure/météo (cumulés)
               e) **NOTE dans réponse** avec détails variables différentes
               f) Retourner statut='similaire_elargi_variables_diff', fiabilité 0.65
            
            6. AUCUN MATCH -> Return None (passage à fallback_inconnu)
        
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
            # Exemple 1 : Match EXACT (périmètre étroit + variables exactes)
            >>> # Polytech->Kennedy matin sans pluie TROUVE Polytech->Kennedy matin sans pluie (coords identiques)
            >>> result = self.check_similar_match([3.8547, 11.5021], [3.8667, 11.5174], 5200, 'matin', 0, 0, None)
            >>> print(result)
            {
                'statut': 'exact',
                'prix_moyen': 250.0,
                'prix_min': 200.0,
                'prix_max': 300.0,
                'fiabilite': 0.95,
                'message': 'Estimation basée sur 8 trajets exacts (périmètre 2min, heure/météo identiques).',
                'ajustements_appliques': {'distance_extra_metres': 0, 'ajustement_distance_cfa': 0.0}
            }
            
            # Exemple 2 : Périmètre étroit + variables DIFFÉRENTES
            >>> # Polytech->Kennedy matin soleil TROUVE Polytech->Kennedy jour pluie
            >>> result = self.check_similar_match([3.8547, 11.5021], [3.8667, 11.5174], 5200, 'matin', 0, 0, None)
            >>> print(result)
            {
                'statut': 'similaire_variables_diff_etroit',
                'prix_moyen': 245.0,  # 250 - 5% météo
                'fiabilite': 0.85,
                'message': 'Estimation depuis 5 trajets proches à heure/météo différentes.',
                'ajustements_appliques': {
                    'ajustement_meteo_pourcent': -5,  # BD pluie, demandé soleil -> -5%
                    'note_variables': 'Prix basé sur trajets avec pluie (−5% vs soleil demandé)'
                }
            }
            
            # Exemple 3 : Périmètre élargi + variables exactes (ajustement distance)
            >>> # Point 200m de Polytech -> Point 150m de Kennedy (5.4km vs 5.2km BD)
            >>> result = self.check_similar_match([3.8550, 11.5025], [3.8670, 11.5180], 5400, 'matin', 0, 0, None)
            >>> print(result)
            {
                'statut': 'similaire_elargi',
                'prix_moyen': 260.0,  # 250 + 10 CFA (200m = 0.2km extra)
                'fiabilite': 0.75,
                'message': 'Estimation ajustée depuis 5 trajets similaires (+10 CFA pour 200m extra).',
                'ajustements_appliques': {
                    'distance_extra_metres': 200,
                    'ajustement_distance_cfa': 10.0  # +50 CFA/km * 0.2km
                }
            }
            
            # Exemple 4 : Périmètre élargi + distance PLUS COURTE (réduit prix)
            >>> # Trajet demandé 5.0km, BD 5.4km -> -400m (-0.4km) -> -20 CFA
            >>> result = self.check_similar_match([3.8545, 11.5020], [3.8665, 11.5170], 5000, 'matin', 0, 0, None)
            >>> print(result)
            {
                'statut': 'similaire_elargi',
                'prix_moyen': 230.0,  # 250 - 20 CFA (400m de moins)
                'ajustements_appliques': {
                    'distance_extra_metres': -400,  # Négatif = distance plus courte
                    'ajustement_distance_cfa': -20.0  # Réduit le prix
                }
            }
            
        Gestion edge cases :
            - Si isochrones Mapbox échouent (NoRoute, routes manquantes Cameroun) :
              **TOUJOURS fallback cercles Haversine** (settings.CIRCLE_RADIUS_ETROIT_M / ELARGI_M)
            - Si quartiers extraction échoue (Nominatim timeout) :
              Filtrer par ville ou skip filtrage (query full BD, plus lent mais exhaustif)
            - Si <2 trajets après filtrage :
              Log warning et return None immédiatement (éviter calculs isochrones inutiles)
            - Si Matrix API échoue (trop de candidats >25) :
              Batch en groupes de 25 ou fallback Haversine pour distances
              
        Constants settings utilisées (toutes configurables via .env) :
            - settings.ISOCHRONE_MINUTES_ETROIT = 2  # Minutes isochrone périmètre étroit
            - settings.ISOCHRONE_MINUTES_ELARGI = 5  # Minutes isochrone périmètre élargi
            - settings.CIRCLE_RADIUS_ETROIT_M = 50  # Rayon cercle fallback étroit (mètres)
            - settings.CIRCLE_RADIUS_ELARGI_M = 150  # Rayon cercle fallback élargi (mètres)
            - settings.PRIX_AJUSTEMENT_PAR_KM = 50.0  # CFA par km extra (bidirectionnel !)
            - settings.ADJUSTMENT_METEO_SOLEIL_PLUIE_POURCENT = 10  # +10% si pluie, -5% inverse
            - settings.ADJUSTMENT_HEURE_JOUR_NUIT_CFA = 50  # +50 CFA si nuit, -30 inverse
            - settings.ADJUSTMENT_CONGESTION_POURCENT = 10  # +10% par tranche 20 pts (appliqué POST-fonction)
            - settings.SIMILARITY_DISTANCE_TOLERANCE_ETROIT_POURCENT = 10  # ±10% périmètre étroit
            - settings.SIMILARITY_DISTANCE_TOLERANCE_ELARGI_POURCENT = 20  # ±20% périmètre élargi
            
        **NOTES IMPORTANTES** : 
        1. Ajustement CONGESTION : 
           - Pour estimations SIMILARITY (cette fonction) : Appliqué À LA FIN dans _process_estimate()
             via settings.ADJUSTMENT_CONGESTION_POURCENT (ex: +10% par tranche 20 pts congestion).
           - Pour estimations ML : La congestion est déjà une FEATURE du modèle (Trajet.congestion_moyen
             et congestion_user) -> PAS de double ajustement post-prédiction.
           - Cette fonction retourne seulement statut pour indiquer si ML ou similarity a été utilisé.
        
        2. Congestion/sinuosité en BD : 
           - Stockées : Trajet.congestion_moyen (0-100 Mapbox), Trajet.sinuosite_indice (≥1.0)
           - Usage principal : Features ML pour predict_prix_ml()
           - Usage secondaire : Analyse patterns (ex: routes sinueuses = prix plus élevés)
        
        3. Variables différentes : 
           - Si aucun match avec heure/météo/type_zone EXACTES, on cherche en ignorant ces filtres
           - Ajustements heure/météo appliqués pour compenser différences (+50 CFA nuit, +10% pluie)
           - Fiabilité réduite (0.85 étroit, 0.65 élargi)
        """
        from shapely.geometry import shape, Point as ShapelyPoint

        logger.info(
            f"[SIMILAR] Demande distance={distance_mapbox:.0f}m heure={heure} meteo={meteo} type_zone={type_zone}"
        )
        
        # 1. FILTRAGE GROSSIER : Récupérer unités administratives pour filtrer candidats BD
        info_depart = self._get_quartier_from_coords(depart_coords)
        info_arrivee = self._get_quartier_from_coords(arrivee_coords)

        logger.info(
            f"[SIMILAR] Filtres geo depart={info_depart} arrivee={info_arrivee}"
        )
        
        # Vérification défensive : s'assurer que les résultats sont des dicts
        if not isinstance(info_depart, dict):
            logger.warning(f"_get_quartier_from_coords a retourne {type(info_depart)} au lieu de dict pour {depart_coords}")
            info_depart = {'commune': None, 'quartier': None, 'ville': None, 'arrondissement': None, 'departement': None}
        if not isinstance(info_arrivee, dict):
            logger.warning(f"_get_quartier_from_coords a retourne {type(info_arrivee)} au lieu de dict pour {arrivee_coords}")
            info_arrivee = {'commune': None, 'quartier': None, 'ville': None, 'arrondissement': None, 'departement': None}
        
        # Construire query base avec toutes les unités disponibles (maximiser chances match)
        query_filters = Q()
        
        # Filtre départ : Prioriser commune, puis arrondissement, puis ville
        if info_depart.get('commune'):
            query_filters &= Q(point_depart__quartier__iexact=info_depart.get('commune'))
        elif info_depart.get('arrondissement'):
            query_filters &= Q(point_depart__arrondissement__iexact=info_depart.get('arrondissement'))
        elif info_depart.get('ville'):
            query_filters &= Q(point_depart__ville__iexact=info_depart.get('ville'))
        
        # Filtre arrivée : Même logique
        if info_arrivee.get('commune'):
            query_filters &= Q(point_arrivee__quartier__iexact=info_arrivee.get('commune'))
        elif info_arrivee.get('arrondissement'):
            query_filters &= Q(point_arrivee__arrondissement__iexact=info_arrivee.get('arrondissement'))
        elif info_arrivee.get('ville'):
            query_filters &= Q(point_arrivee__ville__iexact=info_arrivee.get('ville'))
        
        # Si aucun filtre (reverse-geocode échec), query full BD (lent mais exhaustif)
        candidats = Trajet.objects.filter(query_filters) if query_filters else Trajet.objects.all()
        
        # Log si filtrage échoué
        if not query_filters:
            logger.warning(f"Filtrage geographique impossible pour {depart_coords} -> {arrivee_coords}. Query full BD.")
        logger.info(f"[SIMILAR] Candidats après filtre geo: {candidats.count()}")
        
        # Si aucun trajet après filtrage, skip calculs coûteux
        if candidats.count() < 1:
            logger.info(f"Aucun candidat après filtrage géo. Return None.")
            return None
        
        # 2. HIÉRARCHIE 2D : Périmètres (ÉTROIT->ÉLARGI) × Variables (EXACTES->DIFFÉRENTES)
        
        # Niveau 1A : PÉRIMÈTRE ÉTROIT + Variables EXACTES
        result = self._check_perimetre_level(
            candidats=candidats,
            depart_coords=depart_coords,
            arrivee_coords=arrivee_coords,
            distance_mapbox=distance_mapbox,
            heure=heure,
            meteo=meteo,
            type_zone=type_zone,
            perimetre='etroit',
            variables_exactes=True
        )
        if result:
            return result
        
        # Niveau 1B : PÉRIMÈTRE ÉTROIT + Variables DIFFÉRENTES
        result = self._check_perimetre_level(
            candidats=candidats,
            depart_coords=depart_coords,
            arrivee_coords=arrivee_coords,
            distance_mapbox=distance_mapbox,
            heure=heure,
            meteo=meteo,
            type_zone=type_zone,
            perimetre='etroit',
            variables_exactes=False
        )
        if result:
            return result
        
        # Niveau 2A : PÉRIMÈTRE ÉLARGI + Variables EXACTES
        result = self._check_perimetre_level(
            candidats=candidats,
            depart_coords=depart_coords,
            arrivee_coords=arrivee_coords,
            distance_mapbox=distance_mapbox,
            heure=heure,
            meteo=meteo,
            type_zone=type_zone,
            perimetre='elargi',
            variables_exactes=True
        )
        if result:
            return result
        
        # Niveau 2B : PÉRIMÈTRE ÉLARGI + Variables DIFFÉRENTES
        result = self._check_perimetre_level(
            candidats=candidats,
            depart_coords=depart_coords,
            arrivee_coords=arrivee_coords,
            distance_mapbox=distance_mapbox,
            heure=heure,
            meteo=meteo,
            type_zone=type_zone,
            perimetre='elargi',
            variables_exactes=False
        )
        if result:
            return result
        
        # Aucun match trouvé
        logger.info(f"Aucun trajet similaire trouvé après hiérarchie complète.")
        return None
    
    def _check_perimetre_level(
        self,
        candidats,
        depart_coords: List[float],
        arrivee_coords: List[float],
        distance_mapbox: float,
        heure: Optional[str],
        meteo: Optional[int],
        type_zone: Optional[int],
        perimetre: str,  # 'etroit' ou 'elargi'
        variables_exactes: bool  # True = filter heure/meteo, False = ignorer
    ) -> Optional[Dict]:
        """
        Helper : Vérifie matches pour UN niveau de la hiérarchie (périmètre + variables).
        
        Args:
            candidats : QuerySet trajets pré-filtrés géographiquement
            depart_coords, arrivee_coords : Coords [lat, lon]
            distance_mapbox : Distance routière requête (mètres)
            heure, meteo, type_zone : Variables contextuelles
            perimetre : 'etroit' (2min/50m) ou 'elargi' (5min/150m)
            variables_exactes : True = filtrer heure/météo, False = ignorer filtres
            
        Returns:
            Dict réponse estimation ou None si aucun match
        """
        from shapely.geometry import shape, Point as ShapelyPoint
        
        # Config périmètre
        if perimetre == 'etroit':
            # ISOCHRONE_MINUTES_EXACT est une liste, on prend le premier élément
            isochrone_minutes = settings.ISOCHRONE_MINUTES_EXACT[0] if isinstance(settings.ISOCHRONE_MINUTES_EXACT, list) else settings.ISOCHRONE_MINUTES_EXACT
            # Fallback cercle 200m pour périmètre étroit (quartier proche)
            circle_radius_m = 200
            tolerance_pourcent = getattr(settings, 'SIMILARITY_DISTANCE_TOLERANCE_ETROIT_POURCENT', 15)
            fiabilite_base = 0.95 if variables_exactes else 0.85
            statut_base = 'exact' if variables_exactes else 'similaire'
        else:  # elargi
            isochrone_minutes = settings.ISOCHRONE_MINUTES_SIMILAR[0] if isinstance(settings.ISOCHRONE_MINUTES_SIMILAR, list) else settings.ISOCHRONE_MINUTES_SIMILAR
            # Fallback cercle 500m pour périmètre élargi (quartiers voisins)
            circle_radius_m = 500
            tolerance_pourcent = getattr(settings, 'SIMILARITY_DISTANCE_TOLERANCE_ELARGI_POURCENT', 25)
            fiabilite_base = 0.75 if variables_exactes else 0.65
            statut_base = 'similaire' if variables_exactes else 'similaire'
        
        # Filtrer par variables contextuelles si demandé
        query = candidats
        if variables_exactes:
            if heure:
                query = query.filter(heure=heure)
            if meteo is not None:
                query = query.filter(meteo=meteo)
            if type_zone is not None:
                query = query.filter(type_zone=type_zone)
        
        # Si aucun trajet après filtrage variables, return None
        if query.count() < 1:
            return None
        
        # 3. VÉRIFICATION PÉRIMÈTRE : Isochrones Mapbox ou fallback cercles Haversine
        try:
            # Tenter isochrones Mapbox
            iso_depart = mapbox_client.get_isochrone(
                coordinates=[depart_coords[1], depart_coords[0]],  # Mapbox attend [lon, lat]
                contours_minutes=[isochrone_minutes],
                profile='driving-traffic'
            )
            iso_arrivee = mapbox_client.get_isochrone(
                coordinates=[arrivee_coords[1], arrivee_coords[0]],
                contours_minutes=[isochrone_minutes],
                profile='driving-traffic'
            )
            
            if iso_depart and iso_arrivee:
                # Convertir GeoJSON -> Shapely Polygon
                poly_depart = shape(iso_depart['features'][0]['geometry'])
                poly_arrivee = shape(iso_arrivee['features'][0]['geometry'])
                use_isochrones = True
                logger.info(
                    f"[SIMILAR] Isochrones {perimetre} {isochrone_minutes}min OK (poly départ {len(iso_depart['features'])} feat)"
                )
            else:
                raise ValueError("Isochrones Mapbox retournés vides")
                
        except Exception as e:
            logger.warning(f"Isochrones Mapbox échec ({e}). Fallback cercles Haversine {circle_radius_m}m.")
            poly_depart = None
            poly_arrivee = None
            use_isochrones = False
        
        # Filtrer candidats dans périmètre
        matches = []
        for trajet in query:
            # Vérifier si points du trajet sont dans périmètre
            point_dep_trajet = ShapelyPoint(trajet.point_depart.coords_longitude, trajet.point_depart.coords_latitude)
            point_arr_trajet = ShapelyPoint(trajet.point_arrivee.coords_longitude, trajet.point_arrivee.coords_latitude)
            
            if use_isochrones:
                # Méthode Mapbox : containment Shapely
                if poly_depart.contains(point_dep_trajet) and poly_arrivee.contains(point_arr_trajet):
                    matches.append(trajet)
            else:
                # Fallback cercles Haversine
                dist_dep = haversine_distance(
                    depart_coords[0], depart_coords[1],
                    trajet.point_depart.coords_latitude, trajet.point_depart.coords_longitude
                )
                dist_arr = haversine_distance(
                    arrivee_coords[0], arrivee_coords[1],
                    trajet.point_arrivee.coords_latitude, trajet.point_arrivee.coords_longitude
                )
                if dist_dep <= circle_radius_m and dist_arr <= circle_radius_m:
                    matches.append(trajet)
        
        if len(matches) < 1:
            return None

        logger.info(
            f"[SIMILAR] Matches {len(matches)} sur périmètre {perimetre} (isochrones={use_isochrones})"
        )
        
        # 4. VALIDATION DISTANCES : Matrix API ou Haversine
        # Calculer distance_extra pour chaque match
        matches_with_distance = []
        for trajet in matches:
            # Calculer différence distance : trajet demandé vs trajet BD
            distance_diff = abs(distance_mapbox - trajet.distance)
            distance_tolerance = (tolerance_pourcent / 100.0) * distance_mapbox
            
            # Accepter si dans tolérance
            if distance_diff <= distance_tolerance:
                distance_extra = distance_mapbox - trajet.distance  # Peut être négatif !
                matches_with_distance.append({
                    'trajet': trajet,
                    'distance_extra': distance_extra
                })
        
        if len(matches_with_distance) < 1:
            return None

        logger.info(
            f"[SIMILAR] Matches dans tolérance distance ({tolerance_pourcent}%): {len(matches_with_distance)}"
        )
        
        # 5. CALCUL PRIX MOYEN + AJUSTEMENTS
        trajets_match = [m['trajet'] for m in matches_with_distance]
        prix_list = [t.prix for t in trajets_match]
        distance_extra_moyen = sum(m['distance_extra'] for m in matches_with_distance) / len(matches_with_distance)
        
        prix_moyen = sum(prix_list) / len(prix_list)
        prix_min = min(prix_list)
        prix_max = max(prix_list)
        
        # Ajustements
        ajustements = {'distance_extra_metres': distance_extra_moyen}
        notes = []
        
        # Ajustement DISTANCE (bidirectionnel : + si plus long, - si plus court)
        # Formule : 50 CFA par kilomètre extra
        if perimetre == 'elargi':
            prix_ajustement_par_km = getattr(settings, 'PRIX_AJUSTEMENT_PAR_KM', 50.0)
            distance_extra_km = distance_extra_moyen / 1000.0
            ajust_distance = distance_extra_km * prix_ajustement_par_km
            prix_moyen += ajust_distance
            ajustements['ajustement_distance_cfa'] = ajust_distance
            if ajust_distance > 0:
                notes.append(f"+{int(ajust_distance)} CFA pour {int(distance_extra_moyen)}m extra ({distance_extra_km:.2f}km)")
            elif ajust_distance < 0:
                notes.append(f"{int(ajust_distance)} CFA pour {int(abs(distance_extra_moyen))}m de moins ({abs(distance_extra_km):.2f}km)")
        else:
            ajustements['ajustement_distance_cfa'] = 0.0
        
        # Ajustement HEURE/MÉTÉO (seulement si variables DIFFÉRENTES)
        if not variables_exactes:
            # Identifier différence heure - SEULE la nuit a un tarif différent (+17%)
            if heure and trajets_match[0].heure != heure:
                nuit_pourcent = getattr(settings, 'PRIX_AJUSTEMENT_NUIT_POURCENT', 17)
                bd_is_nuit = trajets_match[0].heure == 'nuit'
                demande_is_nuit = heure == 'nuit'
                
                if bd_is_nuit and not demande_is_nuit:
                    # BD = nuit, demandé = jour → Réduire prix (le jour est moins cher)
                    ajust_heure = -(prix_moyen * nuit_pourcent / (100 + nuit_pourcent))
                elif not bd_is_nuit and demande_is_nuit:
                    # BD = jour, demandé = nuit → Augmenter prix
                    ajust_heure = prix_moyen * nuit_pourcent / 100
                else:
                    # matin↔soir↔apres-midi : pas d'ajustement significatif
                    ajust_heure = 0
                
                if ajust_heure != 0:
                    prix_moyen += ajust_heure
                    ajustements['ajustement_heure_cfa'] = ajust_heure
                    notes.append(f"Prix basé sur trajets '{trajets_match[0].heure}' ({'+' if ajust_heure > 0 else ''}{int(ajust_heure)} CFA vs '{heure}' demandé)")
            
            # Identifier différence météo
            if meteo is not None and trajets_match[0].meteo != meteo:
                # Pluie = +5% du prix (PRIX_AJUSTEMENT_METEO_PLUIE_POURCENT)
                pourcent_meteo = getattr(settings, 'PRIX_AJUSTEMENT_METEO_PLUIE_POURCENT', 5)
                if meteo > trajets_match[0].meteo:  # Demandé pire météo
                    ajust_meteo_pourcent = pourcent_meteo
                else:  # Demandé meilleure météo
                    ajust_meteo_pourcent = -pourcent_meteo // 2
                
                prix_moyen *= (1 + ajust_meteo_pourcent / 100.0)
                ajustements['ajustement_meteo_pourcent'] = ajust_meteo_pourcent
                meteo_names = {0: 'soleil', 1: 'pluie légère', 2: 'pluie forte', 3: 'orage'}
                notes.append(f"Prix basé sur trajets '{meteo_names.get(trajets_match[0].meteo, 'inconnu')}' ({ajust_meteo_pourcent:+d}% vs '{meteo_names.get(meteo, 'inconnu')}' demandé)")
        
        # Message final
        message_base = f"Estimation basée sur {len(trajets_match)} trajets"
        if perimetre == 'etroit' and variables_exactes:
            message = f"{message_base} exacts (périmètre {isochrone_minutes}min)."
        elif perimetre == 'etroit':
            message = f"{message_base} proches à variables différentes."
        elif variables_exactes:
            message = f"{message_base} similaires (périmètre {isochrone_minutes}min)."
        else:
            message = f"{message_base} similaires à variables différentes."
        
        if notes:
            message += " " + " ".join(notes)
        
        # IMPORTANT : Arrondir prix aux CLASSES valides (100, 150, 200, 250, ...)
        # Les prix taxis Cameroun ne sont PAS continus mais appartiennent à des tranches fixes
        
        # Calculer le ratio d'ajustement pour l'appliquer au min/max aussi
        prix_original = sum(prix_list) / len(prix_list)
        if prix_original > 0:
            ratio_ajustement = prix_moyen / prix_original
            prix_min_ajuste = prix_min * ratio_ajustement
            prix_max_ajuste = prix_max * ratio_ajustement
        else:
            prix_min_ajuste = prix_min
            prix_max_ajuste = prix_max
        
        prix_moyen_arrondi = self._arrondir_prix_vers_classe(prix_moyen)
        prix_min_arrondi = self._arrondir_prix_vers_classe(prix_min_ajuste)
        prix_max_arrondi = self._arrondir_prix_vers_classe(prix_max_ajuste)
        
        # S'assurer que min <= moyen <= max
        prix_min_arrondi = min(prix_min_arrondi, prix_moyen_arrondi)
        prix_max_arrondi = max(prix_max_arrondi, prix_moyen_arrondi)
        
        return {
            'statut': statut_base,
            'prix_moyen': prix_moyen_arrondi,  # int, pas float !
            'prix_min': prix_min_arrondi,
            'prix_max': prix_max_arrondi,
            'fiabilite': fiabilite_base,
            'message': message,
            'ajustements_appliques': ajustements,
            'nb_trajets_matches': len(trajets_match)
        }
    
    def fallback_inconnu(
        self,
        depart_coords: List[float],
        arrivee_coords: List[float],
        distance_metres: float,
        heure: Optional[str],
        meteo: Optional[int],
        type_zone: Optional[int],
        congestion_mapbox: Optional[float] = None,
        congestion_user: Optional[int] = None,
        sinuosite: Optional[float] = None,
        nb_virages: Optional[int] = None,
        distance_override: float = None,
        duree_override: float = None
    ) -> Dict[str, object]:
        """
        Génère estimation ML unique pour trajet inconnu (aucun match en BD).
        La seule estimation retournée est `ml_prediction` issue du classifieur.
        """
        try:
            from core.apps import taxi_predictor
        except ImportError:
            taxi_predictor = None

        # Distance et durée finales (privilégier Mapbox déjà calculé)
        dist_finale = distance_override or distance_metres
        if dist_finale is None:
            dist_finale = haversine_distance(
                depart_coords[0], depart_coords[1],
                arrivee_coords[0], arrivee_coords[1]
            ) * 1.3
        duree_finale = duree_override or (dist_finale / 8.33 if dist_finale else None)

        # Caractéristiques complémentaires
        congestion_finale = congestion_mapbox if congestion_mapbox is not None else (
            float(congestion_user) * 10 if congestion_user is not None else 50.0
        )
        sinuosite_finale = sinuosite or calculer_sinuosite_base(
            dist_finale,
            depart_coords[0],
            depart_coords[1],
            arrivee_coords[0],
            arrivee_coords[1]
        )
        nb_virages_final = nb_virages if nb_virages is not None else (int(dist_finale / 500) if dist_finale else 0)
        duree_minutes = duree_finale / 60.0 if duree_finale else None

        logger.info(
            f"[FALLBACK-ML] Features dist={dist_finale:.0f}m duree={duree_finale:.0f}s cong={congestion_finale:.1f} sin={sinuosite_finale:.2f} virages={nb_virages_final} heure={heure} meteo={meteo} zone={type_zone}"
        )

        ml_prediction = None
        if taxi_predictor and getattr(taxi_predictor, 'is_ready', False):
            try:
                ml_prediction = taxi_predictor.predict(
                    distance=dist_finale,
                    heure=heure,
                    meteo=meteo,
                    type_zone=type_zone,
                    congestion=congestion_finale,
                    sinuosite=sinuosite_finale,
                    nb_virages=nb_virages_final,
                    coords_depart=depart_coords,
                    coords_arrivee=arrivee_coords,
                    duree=duree_minutes
                )
                logger.info(f"[FALLBACK-ML] Prediction ML: {ml_prediction} CFA")
            except Exception as e:
                logger.error(f"[FALLBACK-ML] Erreur prediction ML: {e}")
                ml_prediction = None
        else:
            logger.warning("[FALLBACK-ML] Predictor ML non pret ou indisponible")

        return {
            'ml_prediction': ml_prediction,
            'features_utilisees': {
                'distance_metres': dist_finale,
                'duree_secondes': duree_finale,
                'congestion': congestion_finale,
                'sinuosite': sinuosite_finale,
                'nb_virages': nb_virages_final,
                'heure': heure,
                'meteo': meteo,
                'type_zone': type_zone
            }
        }
    
    def predict_prix_ml(
        self,
        distance: float,
        heure: Optional[str],
        meteo: Optional[int],
        type_zone: Optional[int],
        congestion: Optional[float],
        sinuosite: Optional[float],
        nb_virages: Optional[int],
        coords_depart: Optional[List[float]] = None,
        coords_arrivee: Optional[List[float]] = None,
        duree: Optional[float] = None,
        qualite_trajet: Optional[int] = None
    ) -> Optional[int]:
        """
        Prédiction prix via modèle Machine Learning de CLASSIFICATION MULTICLASSE.
        
        **FONCTION CŒUR ML - ÉQUIPE IMPLÉMENTE LOGIQUE COMPLÈTE**
        
        ⚠️ IMPORTANT : Ce N'EST PAS une régression ! 
        Les prix taxis au Cameroun appartiennent à des TRANCHES FIXES (18 classes) :
        [100, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000] CFA
        
        Le modèle doit prédire la CLASSE (tranche de prix) la plus probable, pas un float continu.
        
        Modèle recommandé : 
            - RandomForestClassifier(n_estimators=100, max_depth=15) avec 18 classes
            - XGBoostClassifier
            - OU réseau neuronal avec softmax output (18 neurones)
            
        Features recommandées :
            - distance (float, mètres)
            - heure_encoded (int, 0-3 pour matin/apres-midi/soir/nuit)
            - meteo (int, 0-3)
            - type_zone (int, 0-2)
            - congestion (float, 0-100, remplacer None par moyenne ~50.0)
            - sinuosite (float, ≥1.0, remplacer None par 1.5 si manque)
            - nb_virages (int, remplacer None par 0)
            - qualite_trajet (int, 1-10, remplacer None par 5) **NOUVEAU PARAMÈTRE**
            - feature_interaction : distance * congestion (capture non-linéarité)
            
        **NOTE SUR qualite_trajet :**
        Ce paramètre (échelle 1-10) représente l'évaluation utilisateur de la difficulté du trajet
        (embouteillages, nids de poule, conditions routières). Il sera intégré dans le PROCHAIN modèle
        entraîné. Le modèle actuel (prix_classifier.pkl) NE contient PAS cette feature.
        
        Pour l'instant, cette fonction accepte qualite_trajet en paramètre mais ne l'utilise PAS encore
        dans la prédiction (mock/préparation). Lors du prochain entraînement avec la BD enrichie, 
        qualite_trajet sera ajouté aux features et le modèle sera ré-entraîné pour l'intégrer.
        
        Workflow actuel (SANS qualite_trajet dans le modèle) :
            1. Charger modèle classifier depuis 'ml_models/prix_classifier.pkl' via joblib
            2. Si modèle n'existe pas (pas encore entraîné), return None
            3. Préparer features : encoder heure (mapping str->int), gérer manques (fillna)
               **IGNORER qualite_trajet pour l'instant** (pas dans le modèle actuel)
            4. Normaliser features (StandardScaler sauvegardé avec modèle)
            5. Prédire classe : classe_idx = model.predict(features_scaled)[0]
            6. Mapper index -> prix réel : prix = PRIX_CLASSES_CFA[classe_idx]
            7. Return prix (int, pas float !)
            
        Workflow futur (AVEC qualite_trajet intégré) :
            1-2. Identique
            3. Préparer features AVEC qualite_trajet (fillna 5 si None)
            4-7. Identique
            
        Préparation target pour entraînement (via train_ml_model) :
            1. Pour chaque trajet BD, mapper prix réel vers classe la plus proche
               Ex: 275 CFA -> classe 300 (plus proche que 250)
            2. Encoder classes : [100, 150, ...] -> indices [0, 1, 2, ..., 17]
            3. Entraîner classifier avec y = indices classes
            4. Sauvegarder mapping classes dans prix_classes.json
            
        Entraînement (via task Celery, voir tasks.py) :
            1. Query tous trajets BD : Trajet.objects.all()
            2. Mapper chaque prix BD vers classe proche (fonction mapper_prix_vers_classe)
            3. Préparer features + target_classes (indices 0-17)
               **Inclure qualite_trajet dans features pour nouveau modèle**
            4. Split train/test (80/20) stratifié (keep class distribution)
            5. Entraîner RandomForestClassifier ou XGBoost
            6. Évaluer metrics : accuracy, f1-score, tolérance ±1 classe
            7. Sauvegarder modèle + scaler + prix_classes.json
            
        Args:
            distance : Distance routière (mètres)
            heure : Tranche horaire ('matin', 'apres-midi', 'soir', 'nuit')
            meteo : Code météo (0=soleil, 1=pluie légère, 2=pluie forte, 3=orage)
            type_zone : Type zone (0=urbaine, 1=mixte, 2=rurale)
            congestion : Niveau congestion Mapbox (0-100) ou None
            sinuosite : Indice sinuosité (≥1.0) ou None
            nb_virages : Nombre virages significatifs ou None
            qualite_trajet : Évaluation difficulté trajet (1-10) ou None **[NOUVEAU - PRÉPARATION]**
            
        Returns:
            int : Prix prédit (une des 18 classes CFA) ou None si modèle indisponible
            
        Exemples :
            >>> prix_ml = self.predict_prix_ml(
            ...     distance=5200, heure='matin', meteo=1, type_zone=0,
            ...     congestion=45.0, sinuosite=2.3, nb_virages=7, qualite_trajet=6
            ... )
            >>> if prix_ml:
            ...     print(f"Prédiction ML : {prix_ml} CFA")  # Ex: "250 CFA" (int, pas float)
            
        Gestion erreurs :
            - Si modèle échoue (exception), logger error et return None
            - Si features manquantes critiques (distance=None), return None
            - Si classe prédite hors limites (impossible mais safe), clip vers [100, 2000]
            
        Note performance :
            - Avec 100+ trajets BD, accuracy attendue ~0.65-0.75
            - Avec 500+ trajets, accuracy ~0.75-0.82, tolérance ±1 classe >0.90
            - Avec 1000+ trajets, accuracy >0.85 possible
            - Ré-entraîner quotidiennement via Celery pour intégrer nouveaux trajets
            
        Métriques à utiliser (PAS R²/RMSE !) :
            - accuracy : Pourcentage classes exactes prédites
            - f1_score (weighted) : Balance precision/recall multi-classes
            - tolerance_1_classe : Pourcentage prédictions ±1 classe (250 au lieu 300 = OK)
        """
        try:
            from core.apps import taxi_predictor
            if not taxi_predictor or not taxi_predictor.is_ready:
                logger.warning("ML Predictor non disponible.")
                return None

            # MOCK: Le modèle actuel n'utilise PAS qualite_trajet
            # On le passe quand même pour préparer le terrain, mais il sera ignoré
            # jusqu'au prochain entraînement avec le nouveau modèle incluant cette feature
            prix = taxi_predictor.predict(
                distance=distance,
                heure=heure,
                meteo=meteo,
                type_zone=type_zone,
                congestion=congestion,
                sinuosite=sinuosite,
                nb_virages=nb_virages,
                coords_depart=coords_depart,
                coords_arrivee=coords_arrivee,
                duree=duree
                # qualite_trajet n'est PAS passé au prédicteur actuel
                # car le modèle .pkl existant ne contient pas cette feature
                # Lors du prochain ré-entraînement, ajouter: qualite_trajet=qualite_trajet
            )
            return prix

        except Exception as e:
            logger.error(f"Erreur predict_prix_ml: {e}")
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
    
    serializer_class = TrajetSerializer

    @extend_schema(request=TrajetSerializer, responses=TrajetSerializer)
    def post(self, request):
        """Endpoint POST /api/add-trajet/"""
        serializer = TrajetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Création via serializer (gère enrichissements dans create())
        try:
            trajet = serializer.save()
            logger.info(f"Trajet créé : {trajet}")
            
            # ============================================================
            # TRIGGER RL BATCH (Every 5 trips)
            # ============================================================
            try:
                from django.core.cache import cache
                from .tasks import train_rl_on_recent_trips
                
                # Incrémenter compteur
                count = cache.incr('rl_trajets_count', 1)
                
                if count >= 5:
                    logger.info(f"[RL] Triggering batch training (count={count})")
                    train_rl_on_recent_trips.delay(batch_size=5)
                    cache.set('rl_trajets_count', 0) # Reset
            except Exception as e:
                logger.warning(f"[RL] Failed to trigger batch training: {e}")
                # Si clé n'existe pas, incr peut échouer selon backend, fallback
                cache.set('rl_trajets_count', 1)

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
    
    serializer_class = HealthCheckSerializer

    @extend_schema(responses=HealthCheckSerializer)
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


class ClassifierTestView(APIView):
    """
    View de test pour le RandomForestClassifier : GET /api/classifier-test/
    
    Endpoint de diagnostic pour vérifier que le classifier fonctionne.
    Effectue une prédiction de test avec des données exemple.
    
    Retourne :
        {
            "status": "ok",
            "model_info": {
                "type": "RandomForestClassifier",
                "is_ready": true,
                "n_features": 13,
                "n_classes": 18
            },
            "test_prediction": {
                "input": {...},
                "predicted_price": 500,
                "message": "Test réussi"
            }
        }
    """
    pass


class StatsView(APIView):
    """
    Vue pour les statistiques globales du service.
    Fournit des agrégations sur les trajets, prix, lieux populaires, etc.
    """
    
    @extend_schema(
        summary="Obtenir les statistiques globales",
        description="Retourne des statistiques sur les trajets, les lieux populaires, les records, etc.",
        responses={200: dict}
    )
    def get(self, request):
        # Filtrage temporel
        period = request.query_params.get('period', 'all')
        qs = Trajet.objects.all()
        
        if period == 'month':
            now = timezone.now()
            qs = qs.filter(date_ajout__year=now.year, date_ajout__month=now.month)
        elif period == 'week':
            now = timezone.now()
            start_week = now - timezone.timedelta(days=7)
            qs = qs.filter(date_ajout__gte=start_week)
            
        # 1. Total trajets
        total_trajets = qs.count()
        
        # 2. Trajets difficiles (Top 5)
        trajets_difficiles = qs.order_by('qualite_trajet')[:5]
        
        # 3. Trajets chers (Top 5)
        trajets_chers = qs.order_by('-prix')[:5]
        
        # 4. Trajets longs (Top 5 durée)
        trajets_longs = qs.order_by('-duree_estimee')[:5]
        
        # 5. Lieux populaires (Départ & Arrivée)
        lieux_populaires_depart = qs.values('point_depart__label').annotate(count=Count('point_depart')).order_by('-count')[:5]
        lieux_populaires_arrivee = qs.values('point_arrivee__label').annotate(count=Count('point_arrivee')).order_by('-count')[:5]
        
        # 6. Lieu du mois (Destination la plus populaire ce mois-ci) - Toujours global ou filtré ?
        # Si on filtre déjà par mois, c'est le lieu du mois. Si on filtre "all", on garde la logique "ce mois-ci".
        # Pour rester cohérent avec le filtre, on va dire "Lieu le plus populaire de la période".
        
        lieu_populaire_qs = qs.values('point_arrivee__label').annotate(count=Count('point_arrivee')).order_by('-count')[:1]
        lieu_populaire = lieu_populaire_qs[0] if lieu_populaire_qs else None

        # Serialization des listes d'objets
        def serialize_trajet_list(trajets):
            return TrajetSerializer(trajets, many=True).data

        data = {
            "period": period,
            "total_trajets": total_trajets,
            "trajets_difficiles": serialize_trajet_list(trajets_difficiles),
            "trajets_chers": serialize_trajet_list(trajets_chers),
            "trajets_longs": serialize_trajet_list(trajets_longs),
            "lieux_populaires": {
                "depart": list(lieux_populaires_depart),
                "arrivee": list(lieux_populaires_arrivee)
            },
            "lieu_du_mois": lieu_populaire # Renamed key in response logic, but let's keep key name generic or specific?
            # Let's keep "lieu_du_mois" key for frontend compatibility but it represents "Top Place of Period"
        }
        
        return Response(data)


