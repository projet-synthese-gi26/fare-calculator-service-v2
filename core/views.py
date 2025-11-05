"""
Views Django REST Framework pour l'API d'estimation des prix de taxi.

Endpoints principaux :
- /api/estimate/ (POST/GET) : Estimation prix pour trajet donné
- /api/add-trajet/ (POST) : Ajout trajet réel par utilisateur
- /api/trajets/ (GET) : Liste trajets (admin/debug)
- /api/points/ (GET) : Liste points d'intérêt (admin/debug)

Logique estimation hiérarchique (dans EstimateView) :
    1. check_exact_match : Recherche trajets exacts (même quartiers départ/arrivée, variables similaires)
    2. check_similar_match : Recherche trajets similaires (isochrones/périmètres, ajustements)
    3. fallback_inconnu : Estimations distance-based, standardisé, zone-based, ML (si disponible)
    
Toutes fonctions de prédiction/ML sont des **pass** avec docstrings détaillées pour équipe.
"""

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.utils import timezone
from django.db.models import Avg, Min, Max, Count, Q
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
        2. Appliquer fallbacks variables optionnelles (heure, météo, type_zone)
        3. Filtrer candidats par quartiers départ/arrivée (optimisation queries BD)
        4. check_exact_match : Recherche trajets BD identiques (même quartiers, variables similaires)
            - Si trouvés : Calculer moyenne/min/max prix, fiabilité haute (0.9-1.0)
            - Ajuster pour congestion actuelle via Mapbox (post-prediction)
        5. check_similar_match : Si pas exact, recherche trajets similaires
            - Vérifier points dans isochrones Mapbox (2min exact, 5min élargi) OU cercles fallback (50m/150m)
            - Calculer distance/durée via Mapbox Matrix pour valider similarité
            - Appliquer fonction d'ajustement prix (distance extra, congestion, sinuosité, météo diff)
        6. fallback_inconnu : Si aucun similaire
            - Estimation distance-based : Trouver trajets BD avec distances similaires, extrapoler prix
            - Estimation standardisée : Prix officiels Cameroun (300 CFA jour, 350 nuit)
            - Estimation zone-based : Moyenne prix dans quartier/arrondissement
            - Estimation ML : Appeler predict_prix_ml avec features (distance, heure, météo, zone, congestion)
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
        prediction_data = {
            'statut': 'inconnu',
            'prix_moyen': 300.0,
            'prix_min': None,
            'prix_max': None,
            'estimations_supplementaires': {
                'distance_based': 280.0,
                'standardise': 300.0,
                'zone_based': 290.0
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
    
    def check_exact_match(
        self,
        quartier_depart: Optional[str],
        quartier_arrivee: Optional[str],
        heure: Optional[str],
        meteo: Optional[int],
        type_zone: Optional[int]
    ) -> Optional[List[Trajet]]:
        """
        Recherche trajets exacts dans BD (même quartiers départ/arrivée, variables similaires).
        
        Critères match exact :
            - point_depart.quartier == quartier_depart
            - point_arrivee.quartier == quartier_arrivee
            - heure compatible (même tranche OU null dans BD → flexible)
            - meteo compatible (même code OU écart ≤1 OU null → flexible)
            - type_zone compatible (même code OU null)
            
        Args:
            quartier_depart, quartier_arrivee : Quartiers identifiés depuis coords
            heure, meteo, type_zone : Variables contextuelles (peuvent être None)
            
        Returns:
            List[Trajet] : Trajets matchants (vide si aucun) ou None si quartiers manquent
            
        Workflow :
            1. Si quartiers manquent (None), log warning et return None (skip exact, passer à similaire)
            2. Filter BD : Trajet.objects.filter(
                    point_depart__quartier=quartier_depart,
                    point_arrivee__quartier=quartier_arrivee
                )
            3. Affiner avec variables si fournies :
                - Si heure fournie, filter(Q(heure=heure) | Q(heure__isnull=True))
                - Si meteo fournie, filter(Q(meteo=meteo) | Q(meteo__in=[meteo-1, meteo+1]) | Q(meteo__isnull=True))
                - Si type_zone fournie, filter(Q(type_zone=type_zone) | Q(type_zone__isnull=True))
            4. Return queryset (convert to list si nécessaire)
            
        Exemples :
            >>> trajets = self.check_exact_match('Ekounou', 'Ngoa-Ekelle', 'matin', 1, 0)
            >>> if trajets:
            ...     prix_moyen = sum(t.prix for t in trajets) / len(trajets)
            ...     print(f"{len(trajets)} trajets exacts trouvés, prix moyen {prix_moyen} CFA")
            
        Optimisations :
            - Indexes DB sur (point_depart, point_arrivee) et (heure, meteo, type_zone)
            - Select_related('point_depart', 'point_arrivee') pour éviter N+1 queries
            
        Gestion edge cases :
            - Si quartiers None (coords en zone non cartographiée), return None
            - Si queryset vide, return [] (pas None, pour distinguer "pas trouvé" vs. "skip")
        """
        # Vérifier que quartiers sont disponibles
        if not quartier_depart or not quartier_arrivee:
            logger.warning(
                f"check_exact_match: quartiers manquants (depart={quartier_depart}, arrivee={quartier_arrivee}). "
                f"Skip exact match, passage à similarité."
            )
            return None
        
        logger.info(f"check_exact_match: Recherche trajets {quartier_depart} → {quartier_arrivee}")
        
        # Filtrage base : quartiers départ/arrivée
        queryset = Trajet.objects.filter(
            point_depart__quartier=quartier_depart,
            point_arrivee__quartier=quartier_arrivee
        ).select_related('point_depart', 'point_arrivee')
        
        # Filtrage heure (flexible : même heure OU null dans BD)
        if heure is not None:
            queryset = queryset.filter(Q(heure=heure) | Q(heure__isnull=True))
        
        # Filtrage météo (flexible : même code ± 1 OU null)
        if meteo is not None:
            meteo_range = [meteo]
            if meteo > 0:
                meteo_range.append(meteo - 1)
            if meteo < 3:
                meteo_range.append(meteo + 1)
            queryset = queryset.filter(Q(meteo__in=meteo_range) | Q(meteo__isnull=True))
        
        # Filtrage type zone (flexible : même code OU null)
        if type_zone is not None:
            queryset = queryset.filter(Q(type_zone=type_zone) | Q(type_zone__isnull=True))
        
        # Conversion en liste et comptage
        trajets = list(queryset)
        
        if trajets:
            logger.info(f"check_exact_match: {len(trajets)} trajets exacts trouvés")
        else:
            logger.info("check_exact_match: Aucun trajet exact trouvé")
        
        return trajets
    
    def check_similar_match(
        self,
        depart_coords: List[float],
        arrivee_coords: List[float],
        quartier_depart: Optional[str],
        quartier_arrivee: Optional[str],
        heure: Optional[str],
        meteo: Optional[int]
    ) -> Optional[List[Tuple[Trajet, float]]]:
        """
        Recherche trajets similaires (périmètres/isochrones) avec calcul ajustement prix.
        
        Critères similarité :
            1. Filtrer par quartiers (si disponibles) pour limiter candidats
            2. Vérifier si depart_coords dans isochrone 2min (exact) ou 5min (élargi) du point_depart connu
            3. Idem pour arrivee_coords vs. point_arrivee
            4. Valider distance routière similaire via Mapbox Matrix (tolérance ±20%)
            5. Si isochrones indisponibles, fallback cercles Haversine (50m exact, 150m élargi)
            
        Args:
            depart_coords, arrivee_coords : Coords nouveaux [lat, lon]
            quartier_depart, quartier_arrivee : Pour filtrage initial
            heure, meteo : Pour pondération ajustements (prix diff si météo change)
            
        Returns:
            List[Tuple[Trajet, float]] : Liste (trajet, facteur_ajustement_prix) triée par ajustement croissant
            Exemple : [(trajet1, 1.0), (trajet2, 1.1), (trajet3, 1.2)]
            facteur_ajustement : 1.0 = identique, 1.1 = +10%, 0.9 = -10%
            
        Workflow :
            1. Filtrer candidats par quartiers (comme check_exact)
            2. Pour chaque candidat :
                a. Appeler Mapbox Isochrone pour point_depart (2min et 5min contours)
                b. Vérifier si depart_coords dans polygone via Shapely (point.within(polygon))
                c. Idem pour arrivee_coords vs. isochrone point_arrivee
                d. Si dans isochrone 2min → niveau "exact_similar" (ajustement minimal ±5%)
                e. Si dans isochrone 5min → niveau "elargi_similar" (ajustement ±15%)
                f. Calculer distance routière via Mapbox Directions ou Matrix
                g. Comparer avec trajet.distance : si écart >20%, rejeter candidat
                h. Calculer facteur_ajustement via fonction_ajustement_prix (voir ci-dessous)
            3. Trier candidats par facteur_ajustement (plus proches d'abord)
            4. Return top 5-10 candidats
            
        Fonction ajustement prix (appelée ici) :
            facteur = 1.0
            - Distance extra : +PRIX_AJUSTEMENT_PAR_100M * (distance_diff / 100)  # Ex. +50 CFA / 100m
            - Congestion diff : Si congestion_actuelle > trajet.congestion_moyen + 20 → +10%
            - Sinuosité diff : Si nouveau trajet plus sinueux (via Mapbox) → +5%
            - Météo diff : Si meteo change (ex. soleil → pluie) → +5%
            - Heure diff : Si heure change (jour → nuit) → +10%
            Return facteur (ex. 1.25 pour +25%)
            
        Gestion manques :
            - Si isochrones Mapbox échouent (NoRoute, zones rurales), fallback cercles Haversine
            - Si <3 candidats après filtrage, log info et return [] (passer à inconnu)
            
        Exemples :
            >>> similaires = self.check_similar_match(
            ...     [3.8550, 11.5025], [3.8670, 11.5180],
            ...     'Ekounou', 'Ngoa-Ekelle', 'matin', 1
            ... )
            >>> if similaires:
            ...     trajet_ref, ajustement = similaires[0]
            ...     prix_ajuste = trajet_ref.prix * ajustement
            ...     print(f"Trajet similaire : {trajet_ref}, prix ajusté {prix_ajuste} CFA")
        """
        # TODO : Équipe implémente logique similarité complète avec isochrones/Matrix Mapbox
        # TODO : Gérer fallbacks cercles Haversine si Mapbox échoue
        # TODO : Implémenter fonction_ajustement_prix avec pondérations configurables (settings)
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

