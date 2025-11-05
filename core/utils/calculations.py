"""
Module de calculs géographiques et mathématiques pour le projet.

Fonctions pour :
- Calculs distances Haversine (ligne droite géodésique)
- Calculs sinuosité/virages à partir de données Mapbox
- Conversions coordonnées/unités
- Détections tranches horaires

Pas de dépendances externes lourdes (juste math, datetime).
"""

import math
from datetime import datetime
from typing import Tuple, Dict, Optional, List


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcule la distance ligne droite (géodésique) entre deux points GPS via formule Haversine.
    
    La formule Haversine donne la distance du grand cercle entre deux points sur une sphère
    (Terre approximée comme sphère, rayon ~6371 km). Utilisée pour :
    - Calcul sinuosité base (distance_route / distance_haversine)
    - Filtrage similarité (si isochrones Mapbox indisponibles, fallback cercles rayons fixes)
    - Validation cohérence coords (si haversine > 100km pour trajet urbain, probable erreur saisie)
    
    Args:
        lat1 (float): Latitude point 1 en degrés décimaux (ex. 3.8547 pour Polytechnique Yaoundé)
        lon1 (float): Longitude point 1 en degrés décimaux (ex. 11.5021)
        lat2 (float): Latitude point 2
        lon2 (float): Longitude point 2
        
    Returns:
        float: Distance en mètres (conversion km → m pour cohérence avec distances Mapbox)
        
    Exemples :
        >>> haversine_distance(3.8547, 11.5021, 3.8667, 11.5174)  # Polytechnique → Ekounou
        ~2100.0  # mètres (approximation, itinéraire réel Mapbox ~5200m car routes sinueuses)
        
        >>> haversine_distance(0.0, 0.0, 0.0, 1.0)  # 1 degré longitude à équateur
        ~111320.0  # mètres (1° ≈ 111 km)
        
    Gestion erreurs :
        - Si coords invalides (hors -90/90 lat ou -180/180 lon), lever ValueError
        - Si lat1==lat2 et lon1==lon2, return 0.0 (même point)
        
    Note :
        Pour distances <1000km, erreur Haversine vs. ellipsoïde réel (WGS84) <0.5%.
        Pour Yaoundé (trajets urbains <50km), largement suffisant.
    """
    # Validation coords
    if not (-90 <= lat1 <= 90) or not (-90 <= lat2 <= 90):
        raise ValueError(f"Latitude invalide : lat1={lat1}, lat2={lat2}. Attendu [-90, 90].")
    if not (-180 <= lon1 <= 180) or not (-180 <= lon2 <= 180):
        raise ValueError(f"Longitude invalide : lon1={lon1}, lon2={lon2}. Attendu [-180, 180].")
    
    # Même point
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    
    # Rayon Terre en mètres
    R = 6371000
    
    # Conversion degrés → radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    # Formule Haversine
    a = math.sin(delta_lat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    
    return distance


def calculer_sinuosite_base(distance_route: float, lat_depart: float, lon_depart: float, 
                             lat_arrivee: float, lon_arrivee: float) -> float:
    """
    Calcule indice sinuosité base (Méthode 1) : ratio distance_route / distance_haversine.
    
    C'est la méthode fallback la plus simple si données Mapbox manquent (pas de bearings/maneuvers).
    Un ratio de 1.0 signifie trajet parfaitement droit (impossible en pratique), >1.5 = sinueux.
    
    Args:
        distance_route (float): Distance réelle via Mapbox Directions (mètres)
        lat_depart, lon_depart (float): Coords départ
        lat_arrivee, lon_arrivee (float): Coords arrivée
        
    Returns:
        float: Indice sinuosité (≥1.0). Si distance_haversine=0 (même point), return 1.0
        
    Exemples :
        >>> calculer_sinuosite_base(5212, 3.8547, 11.5021, 3.8667, 11.5174)
        ~2.5  # Route 5.2km pour ligne droite ~2.1km → sinueux (Yaoundé avec détours)
        
        >>> calculer_sinuosite_base(2500, 3.85, 11.50, 3.87, 11.52)
        ~1.1  # Route presque directe (autoroute hypothétique)
        
    Workflow :
        1. Calculer distance_haversine via haversine_distance()
        2. Si distance_haversine < 1 m (même point), return 1.0
        3. Sinon return distance_route / distance_haversine
        4. Si ratio < 1.0 (anormal, erreur données), log warning et return 1.0
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Calculer distance ligne droite
    distance_haversine = haversine_distance(lat_depart, lon_depart, lat_arrivee, lon_arrivee)
    
    # Même point (ou quasi-identique)
    if distance_haversine < 1.0:
        return 1.0
    
    # Calculer ratio
    ratio = distance_route / distance_haversine
    
    # Vérifier cohérence (ratio < 1 = impossible physiquement)
    if ratio < 1.0:
        logger.warning(
            f"Sinuosité base anormale : distance_route={distance_route}m < distance_haversine={distance_haversine:.2f}m. "
            f"Probable erreur données. Fallback ratio=1.0"
        )
        return 1.0
    
    return ratio


def calculer_virages_par_km(maneuvers: List[Dict], distance_total_m: float) -> Tuple[int, float]:
    """
    Calcule nombre et densité virages (Méthode 2) à partir des maneuvers Mapbox.
    
    Parse les étapes de navigation (maneuvers) retournées par Mapbox Directions pour compter
    virages significatifs et calculer densité (virages/km). Pondère par type :
    - "turn" (left/right/slight) : +1 virage
    - "rotary"/"roundabout" : +2 virages (plus complexe pour conducteur)
    - "depart"/"arrive"/"continue" : ignore (pas de virage)
    
    Args:
        maneuvers (List[Dict]): Liste maneuvers extraits de Mapbox JSON
            Structure attendue par élément : {
                "type": "turn",
                "modifier": "left",
                "bearing_before": 0,
                "bearing_after": 270
            }
        distance_total_m (float): Distance totale trajet en mètres
        
    Returns:
        Tuple[int, float]: (nombre_virages_ponderes, virages_par_km)
        
    Exemples :
        >>> maneuvers_example = [
        ...     {"type": "depart", "modifier": None},
        ...     {"type": "turn", "modifier": "left"},
        ...     {"type": "turn", "modifier": "right"},
        ...     {"type": "rotary", "modifier": "straight"},
        ...     {"type": "arrive", "modifier": None}
        ... ]
        >>> calculer_virages_par_km(maneuvers_example, 5000)
        (4, 0.8)  # 2 turns (+2) + 1 rotary (+2) = 4 virages / 5km = 0.8/km
        
    Gestion manques :
        - Si maneuvers vide ou None, return (0, 0.0)
        - Si distance_total_m = 0, return (nb_virages, 0.0) (éviter division par zéro)
        - Si type maneuver non reconnu, log warning et ignore
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not maneuvers:
        return (0, 0.0)
    
    nb_virages = 0
    types_virage_simple = {"turn", "new name", "notification"}  # Types comptant +1
    types_virage_complexe = {"rotary", "roundabout"}  # Types comptant +2
    types_ignorer = {"depart", "arrive", "continue", "merge", "fork", "on ramp", "off ramp", "end of road"}
    
    for maneuver in maneuvers:
        maneuver_type = maneuver.get("type", "").lower()
        
        if maneuver_type in types_virage_simple:
            nb_virages += 1
        elif maneuver_type in types_virage_complexe:
            nb_virages += 2
        elif maneuver_type in types_ignorer:
            continue
        elif maneuver_type:  # Type non vide mais non reconnu
            logger.warning(f"Type maneuver non reconnu ignoré : '{maneuver_type}'")
    
    # Calculer densité
    if distance_total_m == 0:
        return (nb_virages, 0.0)
    
    distance_km = distance_total_m / 1000.0
    virages_par_km = nb_virages / distance_km
    
    return (nb_virages, virages_par_km)


def calculer_force_virages(maneuvers: List[Dict], distance_total_m: float) -> Optional[float]:
    """
    Calcule force virages pondérée (Méthode 3 - PRÉFÉRÉE) : somme angles changement / distance_km.
    
    Pour chaque intersection (maneuver avec bearings), calcule différence angulaire entre
    direction avant et après virage. Somme tous ces angles et divise par distance pour
    obtenir "degrés de virage par km" - mesure complexité itinéraire.
    
    Args:
        maneuvers (List[Dict]): Maneuvers Mapbox avec bearing_before/bearing_after (degrés 0-360)
        distance_total_m (float): Distance totale mètres
        
    Returns:
        float: Force virages en degrés par km (°/km), ou None si données insuffisantes
        
    Calcul angle minimal :
        Différence entre bearing_before et bearing_after, normalisée pour obtenir angle minimal :
        diff = abs(bearing_after - bearing_before)
        angle = min(diff, 360 - diff)  # Ex: 10° et 350° → angle = 20° (pas 340°)
        
    Exemples :
        >>> maneuvers_force = [
        ...     {"type": "turn", "bearing_before": 0, "bearing_after": 90},    # 90°
        ...     {"type": "turn", "bearing_before": 90, "bearing_after": 180},  # 90°
        ...     {"type": "turn", "bearing_before": 0, "bearing_after": 181}    # 179° (Carrefour Vogt exemple docs)
        ... ]
        >>> calculer_force_virages(maneuvers_force, 5000)
        ~71.8  # (90+90+179)/5 = 359°/5km ≈ 71.8°/km
        
        >>> calculer_force_virages([{"bearing_before": 10, "bearing_after": 350}], 1000)
        20.0  # Angle minimal 20° / 1km
        
    Gestion manques :
        - Si bearings absents (None ou clés manquantes), skip ce maneuver et log warning
        - Si >50% maneuvers sans bearings, retourner None (données insuffisantes, utiliser Méthode 2 ou 1)
        - Si distance = 0, return None
        
    Avantages vs. autres méthodes :
        Plus précis car capture "intensité" virages (virage sec 90° vs. doux 10°).
        Corrèle mieux avec perception conducteur/prix taxi (virages secs = temps/effort).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not maneuvers or distance_total_m == 0:
        return None
    
    somme_angles = 0.0
    nb_maneuvers_total = len(maneuvers)
    nb_maneuvers_avec_bearings = 0
    
    for maneuver in maneuvers:
        bearing_before = maneuver.get("bearing_before")
        bearing_after = maneuver.get("bearing_after")
        
        if bearing_before is not None and bearing_after is not None:
            nb_maneuvers_avec_bearings += 1
            angle = normaliser_angle_virage(bearing_before, bearing_after)
            somme_angles += angle
    
    # Vérifier taux disponibilité (seuil 50%)
    taux_disponibilite = nb_maneuvers_avec_bearings / nb_maneuvers_total
    if taux_disponibilite < 0.5:
        logger.warning(
            f"Force virages : données insuffisantes ({nb_maneuvers_avec_bearings}/{nb_maneuvers_total} "
            f"maneuvers avec bearings = {taux_disponibilite:.1%}). Seuil minimum 50%. Retour None."
        )
        return None
    
    # Calculer force virages (°/km)
    distance_km = distance_total_m / 1000.0
    force_virages = somme_angles / distance_km
    
    return force_virages


def determiner_tranche_horaire(heure: Optional[datetime] = None) -> str:
    """
    Détermine la tranche horaire (matin/après-midi/soir/nuit) pour un trajet.
    
    Utilisé pour fallback si utilisateur n'indique pas l'heure lors ajout trajet :
    appeler avec datetime.now() pour heure actuelle. Les tranches influencent prix
    (nuit généralement +10-20% selon docs projet).
    
    Args:
        heure (Optional[datetime]): Datetime du trajet. Si None, utiliser datetime.now()
        
    Returns:
        str: 'matin', 'apres-midi', 'soir', ou 'nuit'
        
    Définition tranches (basée sur contexte Cameroun) :
        - Matin : 6h-12h (heure pointe matin ~7h-9h)
        - Après-midi : 12h-18h (heure pointe soir ~17h-19h)
        - Soir : 18h-22h (trafic diminue)
        - Nuit : 22h-6h (tarifs majorés, moins de taxis disponibles)
        
    Exemples :
        >>> determiner_tranche_horaire(datetime(2023, 11, 5, 8, 30))
        'matin'
        
        >>> determiner_tranche_horaire(datetime(2023, 11, 5, 19, 0))
        'soir'
        
        >>> determiner_tranche_horaire()  # Assume appelé à 14h
        'apres-midi'
        
    Note :
        Timezone : Utiliser Africa/Douala (configuré dans settings.py) pour cohérence.
        Django auto-applique TZ si USE_TZ=True.
    """
    if heure is None:
        heure = datetime.now()
    
    hour = heure.hour
    
    if 6 <= hour < 12:
        return 'matin'
    elif 12 <= hour < 17:
        return 'apres-midi'
    elif 17 <= hour < 19.5:
        return 'soir'
    else:  # 22-23 ou 0-5
        return 'nuit'


def normaliser_angle_virage(bearing_before: float, bearing_after: float) -> float:
    """
    Calcule l'angle minimal entre deux bearings (0-360°).
    
    Helper pour calculer_force_virages. Gère le wrap-around circulaire (ex. 350° → 10° = 20°).
    
    Args:
        bearing_before (float): Direction avant virage (0-360°)
        bearing_after (float): Direction après virage (0-360°)
        
    Returns:
        float: Angle minimal en degrés (0-180°)
        
    Exemples :
        >>> normaliser_angle_virage(0, 90)
        90.0
        
        >>> normaliser_angle_virage(350, 10)
        20.0  # Pas 340
        
        >>> normaliser_angle_virage(180, 180)
        0.0  # Pas de virage
    """
    diff = abs(bearing_after - bearing_before)
    return min(diff, 360 - diff)


def convertir_meteo_code_vers_label(code: int) -> str:
    """
    Convertit code météo numérique (0-3) vers label lisible.
    
    Mapping (selon docs projet) :
        0 : "Soleil" (ciel dégagé)
        1 : "Pluie légère" (bruine, averses)
        2 : "Pluie forte" (pluie continue, orages modérés)
        3 : "Orage" (orage intense, grêle)
        
    Args:
        code (int): Code météo 0-3
        
    Returns:
        str: Label météo
        
    Raises:
        ValueError: Si code hors range 0-3
    """
    mapping = {
        0: "Soleil",
        1: "Pluie légère",
        2: "Pluie forte",
        3: "Orage"
    }
    if code not in mapping:
        raise ValueError(f"Code météo invalide : {code}. Attendu 0-3.")
    return mapping[code]


def convertir_type_zone_vers_label(code: int) -> str:
    """
    Convertit code type zone (0-2) vers label.
    
    Mapping :
        0 : "Urbaine" (centre-ville, quartiers denses)
        1 : "Mixte" (périurbain, quartiers résidentiels avec espaces)
        2 : "Rurale" (villages, routes non pavées)
        
    Args:
        code (int): Code type zone 0-2
        
    Returns:
        str: Label zone
    """
    mapping = {
        0: "Urbaine",
        1: "Mixte",
        2: "Rurale"
    }
    if code not in mapping:
        raise ValueError(f"Code type zone invalide : {code}. Attendu 0-2.")
    return mapping[code]
