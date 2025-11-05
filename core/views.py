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
        Recherche trajets similaires avec hiérarchie correcte : périmètres (étroit→élargi) × variables (exactes→différentes).
        
        **LOGIQUE CENTRALE CORRIGÉE** : 
        Système de recherche avec 2 DIMENSIONS :
        - **DIMENSION 1** : Périmètres géographiques (ÉTROIT 2min/50m → ÉLARGI 5min/150m)
        - **DIMENSION 2** : Variables contextuelles (EXACTES heure/météo → DIFFÉRENTES)
        
        **HIÉRARCHIE VRAIE** (du plus précis au moins précis) :
        
        1. ✅ **PÉRIMÈTRE ÉTROIT + Variables EXACTES** (inclut matchs EXACTS si coords identiques)
           → Si trouvé : Prix DIRECT sans ajustement distance (fiabilité 0.95)
           
        2. ✅ **PÉRIMÈTRE ÉTROIT + Variables DIFFÉRENTES** (heure/météo différentes)
           → Si trouvé : Prix avec ajustement heure/météo + NOTE dans réponse (fiabilité 0.85)
           → Ex : "Polytech-Kennedy nuit sans pluie" trouve "Polytech-Kennedy jour avec pluie"
           → Note : "Prix basé sur trajets de jour (+50 CFA vs nuit), avec pluie (-5%)"
           
        3. ✅ **PÉRIMÈTRE ÉLARGI + Variables EXACTES**
           → Si trouvé : Prix avec ajustement DISTANCE uniquement (fiabilité 0.75)
           → Ajustement distance bidirectionnel : +50 CFA/km si plus long, -50 CFA/km si plus court
           
        4. ✅ **PÉRIMÈTRE ÉLARGI + Variables DIFFÉRENTES**
           → Si trouvé : Prix avec ajustements DISTANCE + heure/météo (fiabilité 0.65)
           
        5. ❌ **AUCUN MATCH** → Return None → Passage fallback_inconnu (modèle ML)
        
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
                  - Heure différente : +50 CFA si jour→nuit, -30 CFA si nuit→jour
                    (settings.ADJUSTMENT_HEURE_JOUR_NUIT_CFA)
                  - Météo différente : +10% si soleil→pluie, -5% si pluie→soleil
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
                    * Si distance_extra > 0 : +settings.ADJUSTMENT_PRIX_PAR_100M par 100m
                    * Si distance_extra < 0 : -settings.ADJUSTMENT_PRIX_PAR_100M par 100m
                  - Ex : Trajet demandé 5.2km, BD 5.4km → -200m → -10 CFA (réduit prix)
                  - Ex : Trajet demandé 5.6km, BD 5.4km → +200m → +10 CFA (augmente prix)
               e) Retourner statut='similaire_elargi', fiabilité 0.75
            
            5. NIVEAU 2B : PÉRIMÈTRE ÉLARGI + Variables DIFFÉRENTES
               a) Reprendre isochrones 5 minutes / cercles 150m
               b) **IGNORER filtres heure/météo**
               c) Vérifier containment + distance ±20%
               d) Si match : Ajustements DISTANCE + heure/météo (cumulés)
               e) **NOTE dans réponse** avec détails variables différentes
               f) Retourner statut='similaire_elargi_variables_diff', fiabilité 0.65
            
            6. AUCUN MATCH → Return None (passage à fallback_inconnu)
        
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
            >>> # Polytech→Kennedy matin sans pluie TROUVE Polytech→Kennedy matin sans pluie (coords identiques)
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
            >>> # Polytech→Kennedy matin soleil TROUVE Polytech→Kennedy jour pluie
            >>> result = self.check_similar_match([3.8547, 11.5021], [3.8667, 11.5174], 5200, 'matin', 0, 0, None)
            >>> print(result)
            {
                'statut': 'similaire_variables_diff_etroit',
                'prix_moyen': 245.0,  # 250 - 5% météo
                'fiabilite': 0.85,
                'message': 'Estimation depuis 5 trajets proches à heure/météo différentes.',
                'ajustements_appliques': {
                    'ajustement_meteo_pourcent': -5,  # BD pluie, demandé soleil → -5%
                    'note_variables': 'Prix basé sur trajets avec pluie (−5% vs soleil demandé)'
                }
            }
            
            # Exemple 3 : Périmètre élargi + variables exactes (ajustement distance)
            >>> # Point 200m de Polytech → Point 150m de Kennedy (5.4km vs 5.2km BD)
            >>> result = self.check_similar_match([3.8550, 11.5025], [3.8670, 11.5180], 5400, 'matin', 0, 0, None)
            >>> print(result)
            {
                'statut': 'similaire_elargi',
                'prix_moyen': 260.0,  # 250 + 10 CFA (200m extra)
                'fiabilite': 0.75,
                'message': 'Estimation ajustée depuis 5 trajets similaires (+10 CFA pour 200m extra).',
                'ajustements_appliques': {
                    'distance_extra_metres': 200,
                    'ajustement_distance_cfa': 10.0  # +50 CFA/km * 0.2km
                }
            }
            
            # Exemple 4 : Périmètre élargi + distance PLUS COURTE (réduit prix)
            >>> # Trajet demandé 5.0km, BD 5.4km → -400m → -20 CFA
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
            - settings.ADJUSTMENT_PRIX_PAR_100M = 5.0  # CFA par 100m extra (bidirectionnel !)
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
             et congestion_user) → PAS de double ajustement post-prédiction.
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
        
        # 1. FILTRAGE GROSSIER : Récupérer unités administratives pour filtrer candidats BD
        info_depart = self._get_quartier_from_coords(depart_coords)
        info_arrivee = self._get_quartier_from_coords(arrivee_coords)
        
        # Construire query base avec toutes les unités disponibles (maximiser chances match)
        query_filters = Q()
        
        # Filtre départ : Prioriser commune, puis arrondissement, puis ville
        if info_depart['commune']:
            query_filters &= Q(point_depart__quartier__iexact=info_depart['commune'])
        elif info_depart['arrondissement']:
            query_filters &= Q(point_depart__arrondissement__iexact=info_depart['arrondissement'])
        elif info_depart['ville']:
            query_filters &= Q(point_depart__ville__iexact=info_depart['ville'])
        
        # Filtre arrivée : Même logique
        if info_arrivee['commune']:
            query_filters &= Q(point_arrivee__quartier__iexact=info_arrivee['commune'])
        elif info_arrivee['arrondissement']:
            query_filters &= Q(point_arrivee__arrondissement__iexact=info_arrivee['arrondissement'])
        elif info_arrivee['ville']:
            query_filters &= Q(point_arrivee__ville__iexact=info_arrivee['ville'])
        
        # Si aucun filtre (reverse-geocode échec), query full BD (lent mais exhaustif)
        candidats = Trajet.objects.filter(query_filters) if query_filters else Trajet.objects.all()
        
        # Log si filtrage échoué
        if not query_filters:
            logger.warning(f"Filtrage géographique impossible pour {depart_coords} → {arrivee_coords}. Query full BD.")
        
        # Si <2 trajets après filtrage, skip calculs coûteux
        if candidats.count() < 2:
            logger.info(f"Moins de 2 candidats après filtrage géo. Return None.")
            return None
        
        # 2. HIÉRARCHIE 2D : Périmètres (ÉTROIT→ÉLARGI) × Variables (EXACTES→DIFFÉRENTES)
        
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
            isochrone_minutes = settings.ISOCHRONE_MINUTES_ETROIT
            circle_radius_m = settings.CIRCLE_RADIUS_ETROIT_M
            tolerance_pourcent = getattr(settings, 'SIMILARITY_DISTANCE_TOLERANCE_ETROIT_POURCENT', 10)
            fiabilite_base = 0.95 if variables_exactes else 0.85
            statut_base = 'exact' if variables_exactes else 'similaire_variables_diff_etroit'
        else:  # elargi
            isochrone_minutes = settings.ISOCHRONE_MINUTES_ELARGI
            circle_radius_m = settings.CIRCLE_RADIUS_ELARGI_M
            tolerance_pourcent = getattr(settings, 'SIMILARITY_DISTANCE_TOLERANCE_ELARGI_POURCENT', 20)
            fiabilite_base = 0.75 if variables_exactes else 0.65
            statut_base = 'similaire_elargi' if variables_exactes else 'similaire_variables_diff_elargi'
        
        # Filtrer par variables contextuelles si demandé
        query = candidats
        if variables_exactes:
            if heure:
                query = query.filter(heure=heure)
            if meteo is not None:
                query = query.filter(meteo=meteo)
            if type_zone is not None:
                query = query.filter(type_zone=type_zone)
        
        # Si <2 trajets après filtrage variables, return None
        if query.count() < 2:
            return None
        
        # 3. VÉRIFICATION PÉRIMÈTRE : Isochrones Mapbox ou fallback cercles Haversine
        try:
            # Tenter isochrones Mapbox
            iso_depart = mapbox_client.get_isochrone(
                coords=[depart_coords[1], depart_coords[0]],  # Mapbox attend [lon, lat]
                minutes=isochrone_minutes,
                profile='driving-traffic'
            )
            iso_arrivee = mapbox_client.get_isochrone(
                coords=[arrivee_coords[1], arrivee_coords[0]],
                minutes=isochrone_minutes,
                profile='driving-traffic'
            )
            
            if iso_depart and iso_arrivee:
                # Convertir GeoJSON → Shapely Polygon
                poly_depart = shape(iso_depart['features'][0]['geometry'])
                poly_arrivee = shape(iso_arrivee['features'][0]['geometry'])
                use_isochrones = True
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
        
        if len(matches) < 2:
            return None
        
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
        
        if len(matches_with_distance) < 2:
            return None
        
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
        if perimetre == 'elargi':
            # Conversion : ADJUSTMENT_PRIX_PAR_100M (ex: 5 CFA/100m)
            ajust_distance = (distance_extra_moyen / 100.0) * settings.ADJUSTMENT_PRIX_PAR_100M
            prix_moyen += ajust_distance
            ajustements['ajustement_distance_cfa'] = ajust_distance
            if ajust_distance > 0:
                notes.append(f"+{int(ajust_distance)} CFA pour {int(distance_extra_moyen)}m extra")
            elif ajust_distance < 0:
                notes.append(f"{int(ajust_distance)} CFA pour {int(abs(distance_extra_moyen))}m de moins")
        else:
            ajustements['ajustement_distance_cfa'] = 0.0
        
        # Ajustement HEURE/MÉTÉO (seulement si variables DIFFÉRENTES)
        if not variables_exactes:
            # Identifier différence heure
            if heure and trajets_match[0].heure != heure:
                # Supposons BD a "jour" et user demande "nuit" → +50 CFA
                # Ou inverse → -30 CFA (exemple simplifié)
                # TODO : Logique plus précise selon combinaisons
                ajust_heure = settings.ADJUSTMENT_HEURE_JOUR_NUIT_CFA if heure == 'nuit' else -30
                prix_moyen += ajust_heure
                ajustements['ajustement_heure_cfa'] = ajust_heure
                notes.append(f"Prix basé sur trajets '{trajets_match[0].heure}' ({'+' if ajust_heure > 0 else ''}{int(ajust_heure)} CFA vs '{heure}' demandé)")
            
            # Identifier différence météo
            if meteo is not None and trajets_match[0].meteo != meteo:
                # Ex: BD pluie (1), demandé soleil (0) → -5%
                # Ou BD soleil (0), demandé pluie (1) → +10%
                pourcent_meteo = settings.ADJUSTMENT_METEO_SOLEIL_PLUIE_POURCENT
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
        
        return {
            'statut': statut_base,
            'prix_moyen': round(prix_moyen, 2),
            'prix_min': round(prix_min, 2),
            'prix_max': round(prix_max, 2),
            'fiabilite': fiabilite_base,
            'message': message,
            'ajustements_appliques': ajustements,
            'nb_trajets_matches': len(trajets_match)
        }
    
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
            - feature_interaction : distance * congestion (capture non-linéarité)
            
        Workflow :
            1. Charger modèle classifier depuis 'ml_models/prix_classifier.pkl' via joblib
            2. Si modèle n'existe pas (pas encore entraîné), return None
            3. Préparer features : encoder heure (mapping str→int), gérer manques (fillna)
            4. Normaliser features (StandardScaler sauvegardé avec modèle)
            5. Prédire classe : classe_idx = model.predict(features_scaled)[0]
            6. Mapper index → prix réel : prix = PRIX_CLASSES_CFA[classe_idx]
            7. Return prix (int, pas float !)
            
        Préparation target pour entraînement (via train_ml_model) :
            1. Pour chaque trajet BD, mapper prix réel vers classe la plus proche
               Ex: 275 CFA → classe 300 (plus proche que 250)
            2. Encoder classes : [100, 150, ...] → indices [0, 1, 2, ..., 17]
            3. Entraîner classifier avec y = indices classes
            4. Sauvegarder mapping classes dans prix_classes.json
            
        Entraînement (via task Celery, voir tasks.py) :
            1. Query tous trajets BD : Trajet.objects.all()
            2. Mapper chaque prix BD vers classe proche (fonction mapper_prix_vers_classe)
            3. Préparer features + target_classes (indices 0-17)
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
            
        Returns:
            int : Prix prédit (une des 18 classes CFA) ou None si modèle indisponible
            
        Exemples :
            >>> prix_ml = self.predict_prix_ml(
            ...     distance=5200, heure='matin', meteo=1, type_zone=0,
            ...     congestion=45.0, sinuosite=2.3, nb_virages=7
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
        # TODO : ÉQUIPE IMPLÉMENTE LOGIQUE CLASSIFICATION COMPLÈTE
        # TODO : Charger classifier (prix_classifier.pkl) + scaler + prix_classes.json
        # TODO : Encoder features, normaliser, prédire classe (index 0-17)
        # TODO : Mapper index → prix réel (PRIX_CLASSES_CFA[classe_idx])
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

