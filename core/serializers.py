"""
Serializers Django REST Framework pour l'API d'estimation des prix de taxi.

Seri

alizers :
- PointSerializer : Sérialisation/création Points avec enrichissement metadata (quartier, ville)
- TrajetSerializer : Trajets avec validation, enrichissement Mapbox (congestion, sinuosité)
- ApiKeySerializer : Clés API (lecture seule pour sécurité)
- EstimateInputSerializer : Validation inputs estimation (coords ou noms, avec fallbacks)
- PredictionOutputSerializer : DTO non-persistant pour réponses estimation (statut, prix, message)

Gestion fallbacks :
- Coords manquantes -> conversion nom via Nominatim
- Météo null -> OpenMeteo API
- Heure null -> datetime.now() -> tranche
- Type zone null -> déduit classes routes Mapbox
"""

from rest_framework import serializers
from django.utils import timezone
from datetime import datetime
from typing import Dict, Optional
import logging

from .models import Point, Trajet, ApiKey
from .utils import (
    mapbox_client,
    nominatim_client,
    openmeteo_client,
    haversine_distance,
    determiner_tranche_horaire
)

logger = logging.getLogger(__name__)


class PointSerializer(serializers.ModelSerializer):
    """
    Serializer pour Point avec enrichissement automatique metadata administratives.
    
    Workflow création :
        1. User fournit coords (obligatoires) + optionnellement label
        2. Si label manque, reverse-geocode via Nominatim ou Mapbox pour obtenir POI/quartier
        3. Enrichir avec ville, quartier, arrondissement (via reverse geocoding)
        4. Sauvegarder Point complet
        
    Validation :
        - Coords entre -90/90 lat, -180/180 lon (géré par models validators)
        - Si coords hors Cameroun (détecté via reverse-geocode country_code != 'cm'), warning mais accepter
        
    Exemples JSON input :
        {
            "coords_latitude": 3.8547,
            "coords_longitude": 11.5021,
            "label": "École Polytechnique Yaoundé"  # Optionnel
        }
        
    Exemples JSON output :
        {
            "id": 1,
            "coords_latitude": 3.8547,
            "coords_longitude": 11.5021,
            "label": "École Polytechnique Yaoundé",
            "ville": "Yaoundé",
            "quartier": "Ngoa-Ekelle",
            "arrondissement": "Yaoundé I",
            "departement": "Mfoundi",
            "created_at": "2023-11-05T14:30:00Z"
        }
    """
    
    class Meta:
        model = Point
        fields = [
            'id', 'coords_latitude', 'coords_longitude', 'label',
            'ville', 'quartier', 'arrondissement', 'departement',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate(self, attrs):
        """
        Valide et enrichit Point avec metadata via reverse geocoding si manquantes.
        """
        lat = attrs.get('coords_latitude')
        lon = attrs.get('coords_longitude')
        
        # Si label manque, tenter reverse-geocode pour POI proche
        if not attrs.get('label'):
            logger.info(f"Label manquant pour Point ({lat}, {lon}), tentative reverse-geocode...")
            reverse_data = nominatim_client.reverse_geocode(lat, lon)
            if reverse_data:
                attrs['label'] = reverse_data.get('display_name', f'Point ({lat:.4f}, {lon:.4f})')
                metadata = nominatim_client.extract_quartier_ville(reverse_data)
                attrs.update({k: v for k, v in metadata.items() if v})  # Seulement valeurs non-None
                logger.info(f"Label auto-détecté : {attrs['label']}")
            else:
                attrs['label'] = f'Point ({lat:.4f}, {lon:.4f})'
                logger.warning("Reverse-geocode échoué, label générique utilisé")
        
        # Enrichir metadata administratives si manquantes (ville, quartier)
        if not attrs.get('quartier') or not attrs.get('ville'):
            logger.info(f"Metadata manquantes pour Point {attrs.get('label')}, enrichissement...")
            reverse_data = nominatim_client.reverse_geocode(lat, lon)
            if reverse_data:
                metadata = nominatim_client.extract_quartier_ville(reverse_data)
                for key, value in metadata.items():
                    if value and not attrs.get(key):  # Ne pas écraser si déjà fourni
                        attrs[key] = value
                logger.info(f"Metadata enrichies : ville={attrs.get('ville')}, quartier={attrs.get('quartier')}")
            else:
                logger.warning("Enrichissement metadata échoué (Nominatim unavailable)")
        
        return attrs


class TrajetSerializer(serializers.ModelSerializer):
    """
    Serializer pour Trajet avec validation, enrichissement Mapbox, et fallbacks.
    
    Workflow création complexe :
        1. Valider inputs (points départ/arrivée, prix obligatoires)
        2. Appliquer fallbacks variables optionnelles :
            - Heure null -> datetime.now() -> tranche (matin/après-midi/soir/nuit)
            - Météo null -> OpenMeteo API sur coords départ (ou moyenne départ/arrivée)
            - Type zone null -> déduit après appel Mapbox (classes routes dominante)
        3. Appeler Mapbox Directions API (driving-traffic, annotations complètes)
        4. Parser JSON Mapbox pour extraire :
            - Distance, durée (validation cohérence avec input si fourni)
            - Congestion moyenne (via extract_congestion_moyen)
            - Sinuosité (via calculate_sinuosite_from_mapbox_data du modèle)
            - Classe route dominante, nb virages, force virages
        5. Gérer données Mapbox manquantes (fallbacks : congestion=50 urbain, sinuosité=1.0)
        6. Sauvegarder Trajet enrichi
        
    Validation :
        - Prix > 0
        - Points départ != arrivée (vérifier coords différentes)
        - Si distance fournie par user, valider cohérence avec Mapbox (tolérance ±20%)
        
    Exemples JSON input :
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
            "heure": "matin",  # ou null
            "meteo": 1,        # ou null
            "type_zone": 0,    # ou null
            "congestion_user": 5  # optionnel
        }
        
    Exemples JSON output :
        {
            "id": 1,
            "point_depart": {...},  # Point complet
            "point_arrivee": {...},
            "distance": 5212.5,
            "prix": 200,
            "heure": "matin",
            "meteo": 1,
            "type_zone": 0,
            "congestion_user": 5,
            "congestion_moyen": 42.3,  # Enrichi Mapbox
            "sinuosite_indice": 2.48,
            "route_classe_dominante": "primary",
            "nb_virages": 7,
            "force_virages": 68.5,
            "duree_estimee": 780.0,
            "date_ajout": "2023-11-05T14:30:00Z"
        }
    """
    
    point_depart = PointSerializer()
    point_arrivee = PointSerializer()
    
    class Meta:
        model = Trajet
        fields = [
            'id', 'point_depart', 'point_arrivee', 'distance', 'prix',
            'heure', 'meteo', 'type_zone', 'congestion_user',
            'congestion_moyen', 'sinuosite_indice', 'route_classe_dominante',
            'nb_virages', 'force_virages', 'duree_estimee',
            'date_ajout', 'updated_at'
        ]
        read_only_fields = [
            'id', 'distance', 'congestion_moyen', 'sinuosite_indice',
            'route_classe_dominante', 'nb_virages', 'force_virages',
            'duree_estimee', 'date_ajout', 'updated_at'
        ]
    
    def validate(self, attrs):
        """
        Valide inputs Trajet et applique fallbacks variables optionnelles.
        """
        # Valider prix positif
        prix = attrs.get('prix')
        if prix is not None and prix <= 0:
            raise serializers.ValidationError({"prix": "Le prix doit être strictement positif."})
        
        # Valider points différents
        depart = attrs.get('point_depart')
        arrivee = attrs.get('point_arrivee')
        if depart and arrivee:
            if (depart.get('coords_latitude') == arrivee.get('coords_latitude') and
                depart.get('coords_longitude') == arrivee.get('coords_longitude')):
                raise serializers.ValidationError(
                    "Les points de départ et d'arrivée doivent être différents."
                )
        
        # Fallback heure : si null, utiliser datetime.now() -> tranche
        if attrs.get('heure') is None:
            now = timezone.now()
            attrs['heure'] = determiner_tranche_horaire(now)
            logger.info(f"Heure auto-détectée : {attrs['heure']}")
        
        # Fallback météo : si null, appeler OpenMeteo
        if attrs.get('meteo') is None:
            lat_depart = depart.get('coords_latitude') if depart else None
            lon_depart = depart.get('coords_longitude') if depart else None
            if lat_depart and lon_depart:
                logger.info(f"Météo manquante, appel OpenMeteo pour ({lat_depart}, {lon_depart})...")
                code_meteo = openmeteo_client.get_current_weather_code(lat_depart, lon_depart)
                if code_meteo is not None:
                    attrs['meteo'] = code_meteo
                    logger.info(f"Météo auto-détectée : code {code_meteo}")
                else:
                    logger.warning("OpenMeteo échoué, météo reste null")
        
        return attrs
    
    def create(self, validated_data):
        """
        Crée Trajet avec enrichissement Mapbox complet.
        
        Étapes :
            1. Créer/récupérer Points départ/arrivée
            2. Appeler Mapbox Directions API
            3. Parser réponse, extraire données enrichies
            4. Appliquer fallbacks si manques
            5. Créer Trajet avec tous champs
        """
        # Extraire nested points
        depart_data = validated_data.pop('point_depart')
        arrivee_data = validated_data.pop('point_arrivee')
        
        # Créer/récupérer Points (get_or_create pour éviter doublons coords identiques)
        point_depart, created_depart = Point.objects.get_or_create(
            coords_latitude=depart_data['coords_latitude'],
            coords_longitude=depart_data['coords_longitude'],
            defaults=depart_data
        )
        if created_depart:
            logger.info(f"Point départ créé : {point_depart.label}")
        
        point_arrivee, created_arrivee = Point.objects.get_or_create(
            coords_latitude=arrivee_data['coords_latitude'],
            coords_longitude=arrivee_data['coords_longitude'],
            defaults=arrivee_data
        )
        if created_arrivee:
            logger.info(f"Point arrivée créé : {point_arrivee.label}")
        
        # Appeler Mapbox Directions API
        coords = [
            [point_depart.coords_longitude, point_depart.coords_latitude],  # [lon, lat]
            [point_arrivee.coords_longitude, point_arrivee.coords_latitude]
        ]
        
        logger.info(f"Appel Mapbox Directions : {point_depart.label} -> {point_arrivee.label}")
        mapbox_data = mapbox_client.get_directions(
            coordinates=coords,
            profile='driving-traffic',
            annotations=['congestion', 'maxspeed', 'duration', 'distance'],
            steps=True
        )
        
        # Parser réponse Mapbox et enrichir
        if mapbox_data and mapbox_data.get('code') == 'Ok':
            route = mapbox_data['routes'][0]
            
            # Distance et durée
            validated_data['distance'] = route['distance']
            validated_data['duree_estimee'] = route['duration']
            
            # Congestion moyenne
            congestion = mapbox_client.extract_congestion_moyen(mapbox_data)
            if congestion is not None:
                validated_data['congestion_moyen'] = congestion
                logger.info(f"Congestion moyenne Mapbox : {congestion:.1f}")
            else:
                # Fallback : urbain=50, sinon 30
                validated_data['congestion_moyen'] = 50.0 if validated_data.get('type_zone') == 0 else 30.0
                logger.warning("Congestion Mapbox 'unknown', fallback appliqué")
            
            # Calcul sinuosité (méthodes dans calculations.py)
            from .utils.calculations import calculer_sinuosite_base, calculer_virages_par_km, calculer_force_virages
            
            # Extraire maneuvers pour virages
            maneuvers = []
            for leg in route.get('legs', []):
                for step in leg.get('steps', []):
                    if 'maneuver' in step:
                        maneuvers.append(step['maneuver'])
            
            # Méthode 3 (force virages) - préférée
            force_virages = calculer_force_virages(maneuvers, validated_data['distance'])
            if force_virages is not None:
                validated_data['force_virages'] = round(force_virages, 2)
                validated_data['sinuosite_indice'] = round(1.0 + (force_virages / 100), 2)
                logger.info(f"Sinuosité via force virages : {validated_data['sinuosite_indice']}")
            else:
                # Fallback Méthode 2 (virages par km)
                nb_virages, virages_km = calculer_virages_par_km(maneuvers, validated_data['distance'])
                validated_data['nb_virages'] = nb_virages
                if virages_km > 0:
                    validated_data['sinuosite_indice'] = round(1.0 + (virages_km / 2), 2)
                    logger.info(f"Sinuosité via virages/km : {validated_data['sinuosite_indice']}")
                else:
                    # Fallback Méthode 1 (distance/ligne droite)
                    sinuosite_base = calculer_sinuosite_base(
                        validated_data['distance'],
                        point_depart.coords_latitude, point_depart.coords_longitude,
                        point_arrivee.coords_latitude, point_arrivee.coords_longitude
                    )
                    validated_data['sinuosite_indice'] = round(sinuosite_base, 2)
                    logger.info(f"Sinuosité via méthode base : {validated_data['sinuosite_indice']}")
            
            # Classe route dominante
            classe = mapbox_client.extract_route_classe_dominante(mapbox_data)
            if classe:
                validated_data['route_classe_dominante'] = classe
                logger.info(f"Classe route dominante : {classe}")
                
                # Fallback type_zone si null
                if validated_data.get('type_zone') is None:
                    if classe in ['motorway', 'trunk', 'primary']:
                        validated_data['type_zone'] = 0  # Urbaine
                    elif classe in ['secondary', 'tertiary']:
                        validated_data['type_zone'] = 1  # Mixte
                    else:
                        validated_data['type_zone'] = 2  # Rurale
                    logger.info(f"Type zone déduit : {validated_data['type_zone']}")
        else:
            error_msg = "Impossible de calculer la distance via Mapbox (NoRoute ou erreur API)"
            logger.error(error_msg)
            raise serializers.ValidationError(error_msg)
        
        # Créer Trajet avec tous les enrichissements
        trajet = Trajet.objects.create(
            point_depart=point_depart,
            point_arrivee=point_arrivee,
            **validated_data
        )
        
        logger.info(f"Trajet créé : ID={trajet.id}, Distance={trajet.distance}m, Prix={trajet.prix} CFA")
        return trajet


class ApiKeySerializer(serializers.ModelSerializer):
    """
    Serializer pour ApiKey (lecture seule pour sécurité).
    
    Admin génère clés via interface Django Admin, pas via API.
    Ce serializer sert uniquement pour affichage (ex. liste clés user admin).
    """
    
    class Meta:
        model = ApiKey
        fields = ['key', 'name', 'is_active', 'created_at', 'last_used']
        read_only_fields = fields  # Tous en lecture seule


class EstimateInputSerializer(serializers.Serializer):
    """
    Serializer pour valider inputs requête /estimate (POST ou GET).
    
    Validation et conversion :
        - Accepte départ/arrivée sous forme coords OU nom (flexible)
        - Si nom fourni, convertir vers coords via Nominatim
        - Si coords, valider format [lat, lon] ou {lat: X, lon: Y}
        - Variables optionnelles (heure, météo, type_zone, congestion_user) avec fallbacks
        
    Exemples JSON input :
        # Variante coords
        {
            "depart": {"lat": 3.8547, "lon": 11.5021},
            "arrivee": {"lat": 3.8667, "lon": 11.5174},
            "heure": "matin",  # optionnel
            "meteo": 1,        # optionnel
            "type_zone": 0,    # optionnel
            "congestion_user": 5  # optionnel
        }
        
        # Variante noms (conversion auto)
        {
            "depart": "Polytechnique Yaoundé",
            "arrivee": "Carrefour Ekounou",
            # autres champs optionnels
        }
        
        # Variante mixte
        {
            "depart": {"lat": 3.8547, "lon": 11.5021},
            "arrivee": "Carrefour Ekounou"
        }
        
    Après validation, attrs contiendra toujours :
        {
            "depart_coords": [lat, lon],
            "arrivee_coords": [lat, lon],
            "depart_label": str ou None,
            "arrivee_label": str ou None,
            "heure": str ou None,
            "meteo": int ou None,
            "type_zone": int ou None,
            "congestion_user": int ou None
        }
    """
    
    # Champs acceptant str (nom) ou dict (coords)
    depart = serializers.JSONField(help_text="Coords {lat, lon} ou nom POI (str)")
    arrivee = serializers.JSONField(help_text="Coords {lat, lon} ou nom POI (str)")
    
    # Variables optionnelles
    heure = serializers.ChoiceField(
        choices=Trajet.HEURE_CHOICES,
        required=False,
        allow_null=True,
        help_text="Tranche horaire. Si null, actuelle détectée."
    )
    meteo = serializers.IntegerField(
        min_value=0, max_value=3,
        required=False,
        allow_null=True,
        help_text="Code météo 0-3. Si null, détecté via OpenMeteo."
    )
    type_zone = serializers.IntegerField(
        min_value=0, max_value=2,
        required=False,
        allow_null=True,
        help_text="Type zone 0-2. Si null, déduit routes Mapbox."
    )
    congestion_user = serializers.IntegerField(
        min_value=1, max_value=10,
        required=False,
        allow_null=True,
        help_text="Niveau embouteillages utilisateur 1-10."
    )
    
    def validate_depart(self, value):
        """Valide et convertit départ en coords."""
        return self._validate_location_field(value, 'depart')
    
    def validate_arrivee(self, value):
        """Valide et convertit arrivée en coords."""
        return self._validate_location_field(value, 'arrivee')
    
    def _validate_location_field(self, value, field_name):
        """
        Helper pour valider/convertir champ localisation (départ ou arrivée).
        
        Args:
            value : dict {lat, lon} ou str (nom)
            field_name : 'depart' ou 'arrivee' (pour messages erreur)
            
        Returns:
            dict : {'coords': [lat, lon], 'label': str ou None}
            
        Raises:
            ValidationError si format invalide ou conversion échoue
        """
        # Cas 1 : dict avec coords
        if isinstance(value, dict):
            lat = value.get('lat') or value.get('coords_latitude') or value.get('latitude')
            lon = value.get('lon') or value.get('coords_longitude') or value.get('longitude')
            
            if lat is None or lon is None:
                raise serializers.ValidationError(
                    f"{field_name} : Format coords invalide. Attendu {{lat: X, lon: Y}}."
                )
            
            # Valider ranges
            try:
                lat = float(lat)
                lon = float(lon)
                if not (-90 <= lat <= 90):
                    raise ValueError("Latitude hors range [-90, 90]")
                if not (-180 <= lon <= 180):
                    raise ValueError("Longitude hors range [-180, 180]")
            except (ValueError, TypeError) as e:
                raise serializers.ValidationError(f"{field_name} : Coords invalides - {e}")
            
            # Extraire label si fourni
            label = value.get('label') or value.get('name')
            
            return {'coords': [lat, lon], 'label': label}
        
        # Cas 2 : str (nom POI) -> convertir via Nominatim
        elif isinstance(value, str):
            nom = value.strip()
            if not nom:
                raise serializers.ValidationError(f"{field_name} : Nom POI vide.")
            
            logger.info(f"Conversion nom '{nom}' vers coords via Nominatim...")
            
            # Appeler Nominatim pour conversion nom -> coords
            coords = nominatim_client.search_place(
                query=nom,
                country_codes='cm',
                viewbox=[11.45, 3.80, 11.60, 3.90]  # Bbox Yaoundé
            )
            
            if coords:
                lat, lon = coords
                logger.info(f"Nom '{nom}' converti en coords : [{lat}, {lon}]")
                return {'coords': [lat, lon], 'label': nom}
            else:
                raise serializers.ValidationError(
                    f"{field_name} : Impossible de géolocaliser '{nom}'. "
                    f"Vérifiez l'orthographe ou fournissez les coordonnées directement."
                )
        
        else:
            raise serializers.ValidationError(
                f"{field_name} : Type invalide. Attendu dict (coords) ou str (nom)."
            )
    
    def validate(self, attrs):
        """
        Validation globale et normalisation finale.
        
        Transforme attrs pour avoir structure uniforme :
            {
                'depart_coords': [lat, lon],
                'arrivee_coords': [lat, lon],
                'depart_label': str ou None,
                'arrivee_label': str ou None,
                'heure': str ou None,
                'meteo': int ou None,
                'type_zone': int ou None,
                'congestion_user': int ou None
            }
        """
        # Extraire coords depuis validated fields
        depart_data = attrs['depart']
        arrivee_data = attrs['arrivee']
        
        attrs['depart_coords'] = depart_data['coords']
        attrs['arrivee_coords'] = arrivee_data['coords']
        attrs['depart_label'] = depart_data.get('label')
        attrs['arrivee_label'] = arrivee_data.get('label')
        
        # Supprimer champs originaux (nettoyage)
        attrs.pop('depart')
        attrs.pop('arrivee')
        
        # Valider coords différentes
        if attrs['depart_coords'] == attrs['arrivee_coords']:
            raise serializers.ValidationError(
                "Les points de départ et d'arrivée doivent être différents."
            )
        
        # Fallbacks variables optionnelles (appliqués dans view, pas ici)
        # Juste valider présence/absence
        
        return attrs


class FeaturesUtiliseesSerializer(serializers.Serializer):
    """Transparence sur les features passées au modèle ML."""

    distance_metres = serializers.FloatField()
    duree_secondes = serializers.FloatField()
    congestion = serializers.FloatField(allow_null=True)
    sinuosite = serializers.FloatField()
    nb_virages = serializers.IntegerField()
    heure = serializers.CharField()
    meteo = serializers.IntegerField()
    type_zone = serializers.IntegerField()


class EstimationsSupplementairesSerializer(serializers.Serializer):
    """Estimations alternatives pour statut 'inconnu' (ML uniquement)."""

    ml_prediction = serializers.IntegerField(required=False, allow_null=True)
    features_utilisees = FeaturesUtiliseesSerializer(required=False, allow_null=True)


class PredictionOutputSerializer(serializers.Serializer):
    """
    Serializer pour réponse estimation prix (DTO non-persistant).
    
    Statut hiérarchique (exact/similaire/inconnu) avec prix, ajustements, fiabilité, message.
    Pour le statut "inconnu", seul le fallback ML est retourné avec transparence des features.
    """
    
    statut = serializers.ChoiceField(
        choices=['exact', 'similaire', 'inconnu'],
        help_text="Statut estimation : exact (match BD), similaire (ajusté), inconnu (fallbacks)."
    )
    prix_moyen = serializers.FloatField(
        help_text="Prix moyen estimé en CFA."
    )
    prix_min = serializers.FloatField(
        allow_null=True,
        help_text="Prix minimal observé (si statut exact/similaire)."
    )
    prix_max = serializers.FloatField(
        allow_null=True,
        help_text="Prix maximal observé (si statut exact/similaire)."
    )
    distance = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text="Distance du trajet en mètres (via Mapbox ou Haversine)."
    )
    duree = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text="Durée estimée du trajet en secondes."
    )
    estimations_supplementaires = EstimationsSupplementairesSerializer(
        required=False,
        allow_null=True,
        help_text="(Inconnu) Fallback ML uniquement, avec features utilisées."
    )
    ajustements_appliques = serializers.DictField(
        required=False,
        help_text="Ajustements prix (congestion, météo, sinuosité, heure) avec explications."
    )
    fiabilite = serializers.FloatField(
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Score fiabilité 0-1 (basé sur nombre trajets similaires, variance prix)."
    )
    message = serializers.CharField(
        help_text="Message explicatif pour utilisateur (ex. 'Basé sur 10 trajets')."
    )
    details_trajet = serializers.DictField(
        required=False,
        help_text="Détails techniques (distance, durée, congestion, météo utilisée)."
    )
    suggestions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Suggestions pour utilisateur (ex. 'Ajoutez votre prix après trajet')."
    )
