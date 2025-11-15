"""
Modèles pour le service d'estimation des prix de taxi au Cameroun (focus Yaoundé).

Les modèles incluent :
- Point : Points d'intérêt géolocalisés (POI, quartiers, carrefours)
- Trajet : Trajets réels ajoutés par utilisateurs avec prix et variables contextuelles
- ApiKey : Clés API pour authentification des requêtes externes

Tous les modèles sont enrichis avec des données Mapbox (congestion, sinuosité, classes routes)
et supportent les fallbacks pour données manquantes (couverture Cameroun incomplète).
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
from datetime import datetime


class Point(models.Model):
    """
    Représente un point d'intérêt (POI) géolocalisé dans le système.
    
    Au Cameroun, les taxis fonctionnent par POI connus (carrefours, écoles, quartiers)
    plutôt que coordonnées aléatoires. Ce modèle stocke ces points avec leurs métadonnées
    administratives pour filtrage et similarité.
    
    Champs :
        coords_latitude (float) : Latitude décimale (ex. 3.8547 pour Polytechnique Yaoundé)
        coords_longitude (float) : Longitude décimale (ex. 11.5021)
        label (str) : Nom du POI (ex. "Carrefour Ekounou", "École Polytechnique Yaoundé")
        ville (str, optionnel) : Ville (ex. "Yaoundé") - pour filtrage queries
        quartier (str, optionnel) : Quartier/sous-quartier (ex. "Ngoa-Ekelle") - ESSENTIEL pour filtrage similarité
        arrondissement (str, optionnel) : Commune/arrondissement (ex. "Yaoundé II")
        departement (str, optionnel) : Département (ex. "Mfoundi")
        
    Exemples d'utilisation :
        - Filtrer trajets candidats : Trajet.objects.filter(point_depart__quartier="Ekounou")
        - Prétraiter coords random → POI proche via Mapbox Map Matching/Search
        
    Gestion manques :
        Si quartier/ville absents (rare avec Mapbox Geocoding), fallback sur coords seules
        pour similarité (cercles fixes au lieu d'isochrones).
    """
    coords_latitude = models.FloatField(
        verbose_name="Latitude",
        help_text="Latitude décimale du point (ex. 3.8547). Validée entre -90 et 90.",
        validators=[MinValueValidator(-90.0), MaxValueValidator(90.0)]
    )
    coords_longitude = models.FloatField(
        verbose_name="Longitude",
        help_text="Longitude décimale du point (ex. 11.5021). Validée entre -180 et 180.",
        validators=[MinValueValidator(-180.0), MaxValueValidator(180.0)]
    )
    label = models.CharField(
        max_length=255,
        verbose_name="Nom du POI",
        help_text="Nom du point d'intérêt connu des taxis (ex. 'Carrefour Ekounou'). Obtenu via Mapbox Search API.",
        db_index=True
    )
    ville = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Ville",
        help_text="Ville du point (ex. 'Yaoundé'). Utilisé pour filtrage queries.",
        db_index=True
    )
    quartier = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Quartier",
        help_text="Quartier/sous-quartier (ex. 'Ngoa-Ekelle'). CRITIQUE pour filtrage similarité avant calculs Mapbox.",
        db_index=True
    )
    arrondissement = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Arrondissement/Commune",
        help_text="Commune (ex. 'Yaoundé II'). Extrait de 'context' Mapbox Geocoding."
    )
    departement = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Département",
        help_text="Département (ex. 'Mfoundi' pour Yaoundé). Fallback filtrage si quartier manque."
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Date de mise à jour")
    
    class Meta:
        verbose_name = "Point d'Intérêt"
        verbose_name_plural = "Points d'Intérêt"
        ordering = ['ville', 'quartier', 'label']
        indexes = [
            models.Index(fields=['ville', 'quartier']),
            models.Index(fields=['coords_latitude', 'coords_longitude']),
        ]
    
    def __str__(self):
        return f"{self.label} ({self.quartier or self.ville or 'Inconnu'})"


class Trajet(models.Model):
    """
    Représente un trajet réel ajouté par utilisateur avec prix payé et contexte.
    
    Trajet enrichi avec données Mapbox (congestion, sinuosité, classes routes) et
    variables contextuelles influençant prix (heure, météo, type zone). Base du système
    communautaire : plus de trajets = estimations précises.
    
    Champs Obligatoires :
        point_depart (ForeignKey Point) : POI de départ (ex. Polytechnique)
        point_arrivee (ForeignKey Point) : POI d'arrivée (ex. Carrefour Ekounou)
        distance (float) : Distance routière en mètres (via Mapbox Directions API)
        prix (float) : Prix payé en CFA (collecté utilisateur, donnée cruciale)
        
    Champs Contextuels (optionnels avec fallbacks) :
        heure (str) : Tranche horaire (matin/apres-midi/soir/nuit) ou null → auto via datetime.now()
        meteo (int) : Code météo (0=soleil, 1=pluie légère, 2=pluie forte, 3=orage) ou null → OpenMeteo API
        type_zone (int) : Type de zone (0=urbaine, 1=mixte, 2=rurale) ou null → déduit via Mapbox classes routes
        congestion_user (int) : Niveau embouteillage selon user (1-10 scale, 1=fluide, 10=bloqué) ou null
        
    Champs Enrichis Mapbox (calculés avant stockage) :
        congestion_moyen (float) : Moyenne congestion Mapbox (0-100) ou null si "unknown"
        sinuosite_indice (float) : Indice sinuosité calculé (1.0=ligne droite, >1.5=sinueux) via bearings/maneuvers
        route_classe_dominante (str) : Classe route principale ("primary", "secondary", etc.) ou null
        nb_virages (int) : Nombre de virages significatifs (type "turn"/"rotary")
        force_virages (float) : Somme angles virages / distance (°/km) pour complexité itinéraire
        duree_estimee (float) : Durée Mapbox en secondes (avec trafic) pour référence
        
    Exemples JSON attendu lors ajout :
        {
            "depart": {"coords": [11.5021, 3.8547], "label": "Polytechnique Yaoundé"},  # ou juste nom recherché
            "arrivee": {"coords": [11.5174, 3.8667], "label": "Carrefour Ekounou"},
            "prix": 200,
            "heure": "matin",  # ou null → auto
            "meteo": 1,        # ou null → OpenMeteo
            "type_zone": 0,    # ou null → déduit classes routes
            "congestion_user": 5  # optionnel, échelle 1-10
        }
        
    Gestion manques :
        - Si congestion Mapbox "unknown" : fallback heure/type_zone (urbaine=50 par défaut)
        - Si bearings manquants : sinuosité via Méthode 1 (distance/ligne droite)
        - Si météo null : appeler OpenMeteo avec coords, mapper à code 0-3
        - Si heure null : datetime.now() → tranche
        
    Workflow ajout :
        1. Valider départ/arrivée (coords ou nom → convert via Nominatim si nom)
        2. Appeler Mapbox Directions API (driving-traffic, annotations=congestion,maxspeed,duration)
        3. Parser JSON : calculer sinuosité (3 méthodes, prioriser force virages), extraire congestion_moyen, classe_dominante
        4. Fallbacks si manques (logs warnings)
        5. Sauvegarder Trajet avec tous champs
        6. Cache résultats Mapbox en BD pour réutilisation (filtrer par quartier avant requêtes)
    """
    
    # Choix tranches horaires (impacts prix selon docs projet)
    HEURE_CHOICES = [
        ('matin', 'Matin (6h-12h)'),
        ('apres-midi', 'Après-midi (12h-18h)'),
        ('soir', 'Soir (18h-22h)'),
        ('nuit', 'Nuit (22h-6h)'),
    ]
    
    # Relations POI
    point_depart = models.ForeignKey(
        Point,
        on_delete=models.CASCADE,
        related_name='trajets_depart',
        verbose_name="Point de départ",
        help_text="POI de départ du trajet (ex. 'Polytechnique Yaoundé')"
    )
    point_arrivee = models.ForeignKey(
        Point,
        on_delete=models.CASCADE,
        related_name='trajets_arrivee',
        verbose_name="Point d'arrivée",
        help_text="POI d'arrivée du trajet (ex. 'Carrefour Ekounou')"
    )
    
    # Champs obligatoires de base
    distance = models.FloatField(
        verbose_name="Distance (mètres)",
        help_text="Distance routière via Mapbox Directions API (driving-traffic). Inclut détours réels.",
        validators=[MinValueValidator(0.0)]
    )
    prix = models.FloatField(
        verbose_name="Prix payé (CFA)",
        help_text="Prix réel payé par utilisateur en Francs CFA. Donnée cruciale pour estimations communautaires.",
        validators=[MinValueValidator(0.0)]
    )
    
    # Variables contextuelles (optionnelles avec fallbacks)
    heure = models.CharField(
        max_length=20,
        choices=HEURE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Tranche horaire",
        help_text="Heure du trajet. Si null, déduire via datetime.now() au moment de l'ajout."
    )
    meteo = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Code météo",
        help_text="0=Soleil, 1=Pluie légère, 2=Pluie forte, 3=Orage. Si null, appeler OpenMeteo API.",
        validators=[MinValueValidator(0), MaxValueValidator(3)]
    )
    type_zone = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Type de zone",
        help_text="0=Urbaine, 1=Mixte, 2=Rurale. Si null, déduire via classes routes Mapbox (primary=urbaine).",
        validators=[MinValueValidator(0), MaxValueValidator(2)]
    )
    congestion_user = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Congestion utilisateur (1-10)",
        help_text="Niveau embouteillages selon user (1=fluide, 10=bloqué). Complète Mapbox pour zones non couvertes.",
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    
    # Enrichissements Mapbox (calculés avant stockage)
    congestion_moyen = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Congestion Mapbox (0-100)",
        help_text="Moyenne congestion segments Mapbox. Null si 'unknown' pour tous segments (fréquent Cameroun)."
    )
    sinuosite_indice = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Indice de sinuosité",
        help_text="Ratio distance/ligne droite ou force virages (°/km). 1.0=droit, >1.5=sinueux. Null si calcul échoue.",
        validators=[MinValueValidator(1.0)]
    )
    route_classe_dominante = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Classe route dominante",
        help_text="'primary', 'secondary', 'tertiary', etc. via Mapbox Streets v8. Null si indisponible.",
        db_index=True
    )
    nb_virages = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Nombre de virages",
        help_text="Nombre maneuvers type 'turn'/'rotary' dans itinéraire Mapbox.",
        validators=[MinValueValidator(0)]
    )
    force_virages = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Force virages (°/km)",
        help_text="Somme |bearing_before - bearing_after| / distance_km. Mesure complexité itinéraire.",
        validators=[MinValueValidator(0.0)]
    )
    duree_estimee = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Durée estimée (secondes)",
        help_text="Durée via Mapbox avec trafic. Pour info uniquement.",
        validators=[MinValueValidator(0.0)]
    )
    
    # Métadonnées
    date_ajout = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date d'ajout",
        help_text="Timestamp ajout trajet par utilisateur."
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Trajet"
        verbose_name_plural = "Trajets"
        ordering = ['-date_ajout']
        indexes = [
            models.Index(fields=['point_depart', 'point_arrivee']),
            models.Index(fields=['heure', 'meteo', 'type_zone']),
            models.Index(fields=['route_classe_dominante']),
        ]
    
    def __str__(self):
        return f"{self.point_depart.label} → {self.point_arrivee.label} ({self.prix} CFA)"
    
    def get_ligne_droite_distance(self):
        """
        Calcule distance ligne droite (Haversine) entre départ et arrivée.
        Utilisé pour calcul sinuosité base (distance / ligne_droite).
        
        Returns:
            float: Distance en mètres
            
        Note:
            Implémentation dans core/utils/calculations.py (fonction haversine_distance).
            Fallback si coords invalides : return distance (supposer linéaire).
        """
        # TODO : Équipe implémente via utils.calculations.haversine_distance
        pass
    
    def calculate_sinuosite_from_mapbox_data(self, mapbox_json):
        """
        Calcule indice sinuosité à partir du JSON Mapbox Directions.
        Priorise force virages (Méthode 3) si bearings complets, sinon fallback Méthode 1/2.
        
        Args:
            mapbox_json (dict): Réponse complète Mapbox Directions API avec steps, maneuvers, bearings
            
        Returns:
            dict: {
                'sinuosite_indice': float,
                'nb_virages': int,
                'force_virages': float,
                'methode_utilisee': str  # 'force_virages', 'virages_par_km', ou 'base'
            }
            
        Workflow :
            1. Extraire bearings, maneuvers, distance des steps
            2. Si bearings complets (>80% segments avec before/after) :
                - Calculer |bearing_before - bearing_after| pour chaque intersection (mod 360° pour angle minimal)
                - Somme totale / distance_km = force_virages (°/km)
                - Sinuosité = 1 + (force_virages / 100)  # Normalisation empirique
            3. Sinon si maneuvers disponibles :
                - Compter virages significatifs (type 'turn'/'rotary'), pondérer rotary x2
                - Nb virages / distance_km = virages_par_km
                - Sinuosité = 1 + (virages_par_km / 2)  # Normalisation
            4. Sinon fallback :
                - Sinuosité base = distance / ligne_droite (via get_ligne_droite_distance)
            5. Si échec total : return {'sinuosite_indice': None, 'nb_virages': None, ...}
            
        Exemples :
            - Trajet exemple docs (5212m, 7 maneuvers, bearings avec Carrefour Vogt 181°) :
                force_virages ≈ 100°/km → sinuosité ≈ 2.0
            - Trajet ligne droite (autoroute) : force_virages ≈ 10°/km → sinuosité ≈ 1.1
            
        Gestion manques Cameroun :
            Si >50% segments "unknown" bearings, log warning et utiliser Méthode 2 ou 1.
        """
        # TODO : Équipe implémente logique complète avec parsing JSON Mapbox
        # TODO : Gérer cas "unknown" fréquents (fallbacks successifs)
        # TODO : Stocker résultats dans self.sinuosite_indice, nb_virages, force_virages avant save()
        pass


class ApiKey(models.Model):
    """
    Modèle pour gestion des clés API anonymes (pas d'authentification utilisateur).
    
    L'API fonctionne avec clés API générées par admin dans interface Django Admin.
    Pas de système utilisateurs/JWT : API anonyme mais sécurisée par clés pour éviter abus.
    Admin génère clés à volonté pour camarades/projets externes.
    
    Champs :
        key (UUIDField) : Clé unique générée automatiquement (UUID4)
        name (str) : Nom descriptif (ex. "Clé projet camarade Jean")
        is_active (bool) : Statut activation (désactiver sans supprimer pour historique)
        created_at (datetime) : Date génération
        
    Workflow utilisation :
        1. Admin génère clé via Django Admin (bouton custom ou formulaire)
        2. Clé stockée en BD, affichée à admin (copier-coller)
        3. Utilisateur externe envoie requêtes avec header : Authorization: ApiKey <uuid>
        4. Middleware ApiKeyMiddleware valide clé (vérifie existence + is_active=True)
        5. Si invalide : HTTP 401 Unauthorized ; si valide : passe à view
        
    Validation middleware :
        - Extraire clé depuis headers['Authorization'] (format "ApiKey <key>")
        - Query ApiKey.objects.filter(key=extracted_key, is_active=True)
        - Si n'existe pas : reject
        - Endpoints exemptés : /admin/, /api/docs/ (optionnel)
        
    Exemples headers :
        Authorization: ApiKey 550e8400-e29b-41d4-a716-446655440000
    """
    key = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name="Clé API",
        help_text="UUID unique généré automatiquement. Utilisé dans headers Authorization."
    )
    name = models.CharField(
        max_length=255,
        verbose_name="Nom descriptif",
        help_text="Description de la clé (ex. 'Projet camarade Jean', 'Test dev')"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Si désactivée, requêtes avec cette clé sont rejetées (401)."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date de création"
    )
    last_used = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Dernière utilisation",
        help_text="Timestamp dernière requête valide avec cette clé. Mise à jour par middleware."
    )
    usage_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Nombre d'utilisations",
        help_text="Compteur incrémenté à chaque requête valide. Permet de tracker quel projet utilise le plus l'API."
    )
    
    class Meta:
        verbose_name = "Clé API"
        verbose_name_plural = "Clés API"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-usage_count']),  # Pour stats des clés les plus utilisées
        ]
    
    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.name} ({status}) - {str(self.key)[:8]}..."
    
    def update_last_used(self):
        """
        Met à jour timestamp last_used et incrémente usage_count lors d'une requête valide.
        Appelé par middleware après validation.
        
        Note: Utilise F() expression pour éviter race conditions sur compteur.
        """
        from django.db.models import F
        from django.utils import timezone
        self.last_used = timezone.now()
        self.usage_count = F('usage_count') + 1
        self.save(update_fields=['last_used', 'usage_count'])
        self.refresh_from_db()  # Refresh pour obtenir la nouvelle valeur après F()
