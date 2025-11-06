# Documentation API - Service d'Estimation de Prix Taxi Cameroun

**Version** : 1.0  
**Base URL** : `http://localhost:8000/api/`  
**Format** : JSON  
**Authentification** : API Key (Header `Authorization`)

---

## Table des Matières

1. [Authentification](#authentification)
2. [Endpoints](#endpoints)
   - [POST /estimate/](#post-estimate)
   - [GET /estimate/](#get-estimate)
   - [POST /trajets/](#post-trajets)
   - [GET /trajets/](#get-trajets)
   - [GET /trajets/{id}/](#get-trajetsid)
   - [GET /trajets/stats/](#get-trajetsstats)
   - [GET /points/](#get-points)
   - [GET /points/{id}/](#get-pointsid)
   - [GET /health/](#get-health)
3. [Modèles de données](#modèles-de-données)
4. [Codes d'erreur](#codes-derreur)
5. [Exemples complets](#exemples-complets)
6. [Limites et quotas](#limites-et-quotas)

---

## Authentification

Toutes les routes (sauf `/api/health/`) nécessitent une **clé API** dans le header HTTP :

```http
Authorization: ApiKey <votre-uuid-cle>
```

### Exemple avec curl
```bash
curl -H "Authorization: ApiKey 550e8400-e29b-41d4-a716-446655440000" \
     http://localhost:8000/api/estimate/
```

### Exemple avec Python requests
```python
import requests

headers = {
    'Authorization': 'ApiKey 550e8400-e29b-41d4-a716-446655440000',
    'Content-Type': 'application/json'
}

response = requests.post(
    'http://localhost:8000/api/estimate/',
    headers=headers,
    json={...}
)
```

### Obtenir une clé API
- Les clés API sont générées via l'**interface Django Admin** : `/admin/`
- Seuls les administrateurs peuvent créer/désactiver des clés
- Chaque clé a un compteur `usage_count` pour tracker l'utilisation

### Erreurs d'authentification

**401 Unauthorized - Clé manquante**
```json
{
    "error": "API key requise. Header 'Authorization: ApiKey <uuid>' manquant."
}
```

**401 Unauthorized - Clé invalide**
```json
{
    "error": "API key invalide ou inactive."
}
```

---

## Endpoints

### POST /estimate/

**Endpoint principal** : Estimation du prix d'un trajet taxi.

#### Requête

**Headers**
```http
Authorization: ApiKey <uuid>
Content-Type: application/json
```

**Body JSON**

Le `depart` et l'`arrivee` peuvent être fournis sous **2 formats** :

**Format 1 : Coordonnées GPS**
```json
{
    "depart": {
        "lat": 3.8547,
        "lon": 11.5021
    },
    "arrivee": {
        "lat": 3.8667,
        "lon": 11.5174
    },
    "heure": "matin",
    "meteo": 1,
    "type_zone": 0,
    "congestion_user": 5
}
```

**Format 2 : Nom de lieu (conversion automatique)**
```json
{
    "depart": "Polytechnique Yaoundé",
    "arrivee": "Carrefour Ekounou",
    "heure": "matin"
}
```

**Format 3 : Mixte**
```json
{
    "depart": {"lat": 3.8547, "lon": 11.5021},
    "arrivee": "Carrefour Ekounou",
    "heure": null,
    "meteo": null
}
```

#### Paramètres détaillés

| Paramètre | Type | Obligatoire | Description | Valeurs autorisées |
|-----------|------|-------------|-------------|-------------------|
| `depart` | Object/String | ✅ Oui | Point de départ | Coords `{lat, lon}` OU nom lieu |
| `arrivee` | Object/String | ✅ Oui | Point d'arrivée | Coords `{lat, lon}` OU nom lieu |
| `heure` | String | ❌ Non | Tranche horaire | `"matin"`, `"apres-midi"`, `"soir"`, `"nuit"`, `null` (auto) |
| `meteo` | Integer | ❌ Non | Code météo | `0` (soleil), `1` (pluie légère), `2` (pluie forte), `3` (orage), `null` (auto) |
| `type_zone` | Integer | ❌ Non | Type de zone | `0` (urbaine), `1` (mixte), `2` (rurale), `null` (auto) |
| `congestion_user` | Integer | ❌ Non | Embouteillages ressentis | `1` (fluide) à `10` (bloqué), `null` |

**Notes importantes :**
- Si `heure` est `null`, l'API utilise l'heure actuelle (serveur timezone Africa/Douala)
- Si `meteo` est `null`, l'API interroge OpenMeteo avec les coordonnées de départ
- Si un **nom de lieu** est fourni, l'API le convertit en coordonnées via **Nominatim** (OpenStreetMap)
- Les coordonnées doivent être en **degrés décimaux** : `lat` entre -90 et 90, `lon` entre -180 et 180

#### Réponse réussie (200 OK)

La réponse varie selon le **type de match** trouvé :

**Cas 1 : Trajet EXACT trouvé en base de données**

```json
{
    "statut": "exact",
    "prix_moyen": 250.0,
    "prix_min": 200.0,
    "prix_max": 300.0,
    "fiabilite": 0.95,
    "message": "Estimation basée sur 8 trajets exacts similaires.",
    "nb_trajets_utilises": 8,
    "details_trajet": {
        "depart": {
            "label": "Polytechnique Yaoundé",
            "coords": [3.8547, 11.5021],
            "quartier": "Ngoa-Ekelle",
            "ville": "Yaoundé"
        },
        "arrivee": {
            "label": "Carrefour Ekounou",
            "coords": [3.8667, 11.5174],
            "quartier": "Ekounou",
            "ville": "Yaoundé"
        },
        "distance_estimee": 5212.5,
        "duree_estimee": 730.0,
        "heure": "matin",
        "meteo": 1,
        "type_zone": 0
    },
    "ajustements_appliques": {
        "congestion_actuelle": 45.0,
        "ajustement_congestion_pourcent": 0,
        "meteo_opposee": {
            "code": 0,
            "label": "Soleil",
            "prix_estime": 240.0,
            "message": "Estimation si météo change (soleil au lieu de pluie légère)"
        },
        "heure_opposee": {
            "tranche": "nuit",
            "prix_estime": 290.0,
            "message": "Estimation pour trajet de nuit (+17%)"
        }
    },
    "suggestions": [
        "Tarif fiable basé sur historique communautaire",
        "Négociez entre 200 et 300 CFA selon embouteillages"
    ]
}
```

**Cas 2 : Trajet SIMILAIRE (périmètre proche)**

```json
{
    "statut": "similaire",
    "prix_moyen": 270.0,
    "prix_min": 250.0,
    "prix_max": 290.0,
    "fiabilite": 0.75,
    "message": "Estimation ajustée depuis 5 trajets similaires (+20 CFA pour distance extra de 200m).",
    "nb_trajets_utilises": 5,
    "details_trajet": {
        "depart": {
            "label": "Proche École Polytechnique",
            "coords": [3.8550, 11.5025],
            "quartier": "Ngoa-Ekelle",
            "ville": "Yaoundé"
        },
        "arrivee": {
            "label": "Proche Carrefour Ekounou",
            "coords": [3.8670, 11.5180],
            "quartier": "Ekounou",
            "ville": "Yaoundé"
        },
        "distance_estimee": 5412.3,
        "duree_estimee": 780.0,
        "heure": "matin",
        "meteo": 1,
        "type_zone": 0
    },
    "ajustements_appliques": {
        "distance_extra_metres": 200,
        "ajustement_distance_cfa": 20,
        "ajustement_congestion_pourcent": 5,
        "facteur_ajustement_total": 1.08,
        "meteo_opposee": {
            "code": 2,
            "label": "Pluie forte",
            "prix_estime": 285.0
        },
        "heure_opposee": {
            "tranche": "soir",
            "prix_estime": 280.0
        }
    },
    "suggestions": [
        "Trajets similaires trouvés dans le quartier",
        "Prix ajusté pour distance légèrement différente",
        "Ajoutez votre prix réel après le trajet pour améliorer les estimations"
    ]
}
```

**Cas 3 : Trajet INCONNU (aucune donnée similaire)**

```json
{
    "statut": "inconnu",
    "prix_moyen": 280.0,
    "prix_min": null,
    "prix_max": null,
    "fiabilite": 0.50,
    "message": "Trajet inconnu. Estimation basée sur plusieurs méthodes approximatives.",
    "nb_trajets_utilises": 0,
    "estimations_supplementaires": {
        "distance_based": 260.0,
        "standardise": 300.0,
        "zone_based": 270.0,
        "ml_prediction": 285.0
    },
    "details_estimations": {
        "distance_based": "Basé sur distance routière (5.2 km) et prix/km moyen BD (50 CFA/km)",
        "standardise": "Tarif officiel Cameroun (300 CFA jour, 350 CFA nuit)",
        "zone_based": "Moyenne prix trajets dans arrondissement Yaoundé II (270 CFA)",
        "ml_prediction": "Prédiction modèle Machine Learning (R²=0.78)"
    },
    "details_trajet": {
        "depart": {
            "label": "Point inconnu",
            "coords": [3.8547, 11.5021],
            "quartier": null,
            "ville": "Yaoundé"
        },
        "arrivee": {
            "label": "Destination inconnue",
            "coords": [3.9000, 11.5500],
            "quartier": null,
            "ville": null
        },
        "distance_estimee": 5200.0,
        "duree_estimee": 800.0,
        "heure": "matin",
        "meteo": 1,
        "type_zone": 0
    },
    "ajustements_appliques": {
        "meteo_opposee": {
            "code": 0,
            "label": "Soleil",
            "prix_estime": 265.0
        },
        "heure_opposee": {
            "tranche": "nuit",
            "prix_estime": 330.0
        }
    },
    "suggestions": [
        "⚠️ Fiabilité faible : aucun trajet similaire en base de données",
        "Négociez prudemment et ajoutez votre prix après le trajet",
        "Plus de trajets ajoutés = estimations plus précises pour tous"
    ]
}
```

#### Champs de réponse détaillés

| Champ | Type | Description |
|-------|------|-------------|
| `statut` | String | Type de match : `"exact"`, `"similaire"`, `"inconnu"` |
| `prix_moyen` | Float | Prix moyen estimé en CFA |
| `prix_min` | Float/null | Prix minimum (si trajets exacts/similaires trouvés) |
| `prix_max` | Float/null | Prix maximum (si trajets exacts/similaires trouvés) |
| `fiabilite` | Float | Score fiabilité 0.0-1.0 (0.5=faible, 0.75=moyenne, 0.95=haute) |
| `message` | String | Description estimation en français |
| `nb_trajets_utilises` | Integer | Nombre de trajets BD utilisés pour estimation |
| `details_trajet` | Object | Informations complètes trajet (départ, arrivée, distance, durée) |
| `ajustements_appliques` | Object | Détails ajustements prix (congestion, météo, heure) |
| `estimations_supplementaires` | Object | (Uniquement statut "inconnu") Estimations alternatives |
| `suggestions` | Array[String] | Conseils utilisateur |

**Météo opposée & Heure opposée** :
- L'API retourne **TOUJOURS** des estimations pour la météo actuelle **ET** la météo opposée
- Exemple : Si requête avec `meteo=1` (pluie légère), la réponse inclut estimation pour `meteo=0` (soleil)
- Idem pour heure : Si `heure="matin"` (jour), la réponse inclut estimation pour `"nuit"`
- **But** : Donner flexibilité à l'utilisateur pour planifier trajets

#### Erreurs possibles

**400 Bad Request - Paramètres invalides**
```json
{
    "depart": ["Ce champ est requis."],
    "arrivee": ["Format coords invalide. Attendu {lat: X, lon: Y}."]
}
```

**400 Bad Request - Géolocalisation échouée**
```json
{
    "arrivee": ["Impossible de géolocaliser 'Carrefour XYZ'. Vérifiez l'orthographe ou fournissez les coordonnées."]
}
```

**400 Bad Request - Points identiques**
```json
{
    "non_field_errors": ["Les points de départ et d'arrivée doivent être différents."]
}
```

**500 Internal Server Error - Mapbox indisponible**
```json
{
    "error": "Impossible de calculer la distance via Mapbox (NoRoute ou erreur API)"
}
```

---

### GET /estimate/

**Alternative GET** pour estimation (conversion query params → POST).

#### Requête

**Headers**
```http
Authorization: ApiKey <uuid>
```

**Query Parameters**

```
GET /api/estimate/?depart_lat=3.8547&depart_lon=11.5021&arrivee_lat=3.8667&arrivee_lon=11.5174&heure=matin&meteo=1
```

| Paramètre | Type | Obligatoire | Description |
|-----------|------|-------------|-------------|
| `depart_lat` | Float | ✅ Oui | Latitude départ |
| `depart_lon` | Float | ✅ Oui | Longitude départ |
| `arrivee_lat` | Float | ✅ Oui | Latitude arrivée |
| `arrivee_lon` | Float | ✅ Oui | Longitude arrivée |
| `heure` | String | ❌ Non | Tranche horaire |
| `meteo` | Integer | ❌ Non | Code météo 0-3 |
| `type_zone` | Integer | ❌ Non | Type zone 0-2 |
| `congestion_user` | Integer | ❌ Non | Congestion 1-10 |

**Note** : Le GET ne supporte **QUE les coordonnées**, pas les noms de lieux (limitation URL encoding).

#### Réponse

Identique au POST `/estimate/`.

---

### POST /trajets/

**Alias** : `POST /add-trajet/`

**Endpoint contribution** : Ajouter un trajet réel avec prix payé.

#### Requête

**Headers**
```http
Authorization: ApiKey <uuid>
Content-Type: application/json
```

**Body JSON**

```json
{
    "point_depart": {
        "coords_latitude": 3.8547,
        "coords_longitude": 11.5021,
        "label": "Polytechnique Yaoundé",
        "quartier": "Ngoa-Ekelle",
        "ville": "Yaoundé"
    },
    "point_arrivee": {
        "coords_latitude": 3.8667,
        "coords_longitude": 11.5174,
        "label": "Carrefour Ekounou",
        "quartier": "Ekounou",
        "ville": "Yaoundé"
    },
    "prix": 250.0,
    "heure": "matin",
    "meteo": 1,
    "type_zone": 0,
    "congestion_user": 5
}
```

#### Paramètres détaillés

**Champs obligatoires** :

| Paramètre | Type | Description | Validation |
|-----------|------|-------------|-----------|
| `point_depart` | Object | Point départ (nested) | - |
| `point_depart.coords_latitude` | Float | Latitude départ | -90 à 90 |
| `point_depart.coords_longitude` | Float | Longitude départ | -180 à 180 |
| `point_arrivee` | Object | Point arrivée (nested) | - |
| `point_arrivee.coords_latitude` | Float | Latitude arrivée | -90 à 90 |
| `point_arrivee.coords_longitude` | Float | Longitude arrivée | -180 à 180 |
| `prix` | Float | Prix payé en CFA | > 0 |

**Champs optionnels (enrichissement auto si manquants)** :

| Paramètre | Type | Description | Fallback si null |
|-----------|------|-------------|------------------|
| `point_depart.label` | String | Nom POI départ | Reverse-geocode via Nominatim |
| `point_depart.quartier` | String | Quartier départ | Extrait via Nominatim |
| `point_depart.ville` | String | Ville départ | Extrait via Nominatim |
| `point_arrivee.*` | String | Idem pour arrivée | Idem |
| `heure` | String | Tranche horaire | Détectée via `datetime.now()` |
| `meteo` | Integer | Code météo 0-3 | Appelé OpenMeteo API |
| `type_zone` | Integer | Type zone 0-2 | Déduit via classes routes Mapbox |
| `congestion_user` | Integer | Embouteillages 1-10 | null (optionnel user) |

**Enrichissements automatiques (calculés par API)** :
- `distance` : Calculée via **Mapbox Directions API** (distance routière réelle en mètres)
- `duree_estimee` : Durée trajet avec trafic (secondes)
- `congestion_moyen` : Moyenne congestion Mapbox (0-100) ou fallback 50.0 si "unknown"
- `sinuosite_indice` : Indice sinuosité route (1.0=droite, >1.5=sinueux) calculé via 3 méthodes hiérarchiques
- `nb_virages` : Nombre de virages comptabilisés (maneuvers Mapbox)
- `force_virages` : Somme angles virages / distance (°/km)
- `route_classe_dominante` : Classe route principale (`"primary"`, `"secondary"`, etc.)

#### Réponse réussie (201 Created)

```json
{
    "id": 42,
    "point_depart": {
        "id": 10,
        "coords_latitude": 3.8547,
        "coords_longitude": 11.5021,
        "label": "Polytechnique Yaoundé",
        "quartier": "Ngoa-Ekelle",
        "ville": "Yaoundé",
        "arrondissement": "Yaoundé II",
        "departement": "Mfoundi"
    },
    "point_arrivee": {
        "id": 11,
        "coords_latitude": 3.8667,
        "coords_longitude": 11.5174,
        "label": "Carrefour Ekounou",
        "quartier": "Ekounou",
        "ville": "Yaoundé",
        "arrondissement": "Yaoundé II",
        "departement": "Mfoundi"
    },
    "distance": 5212.176,
    "prix": 250.0,
    "heure": "matin",
    "meteo": 1,
    "type_zone": 0,
    "congestion_user": 5,
    "congestion_moyen": 45.3,
    "sinuosite_indice": 2.48,
    "route_classe_dominante": "primary",
    "nb_virages": 7,
    "force_virages": 71.8,
    "duree_estimee": 730.888,
    "date_ajout": "2025-11-05T14:30:00Z",
    "updated_at": "2025-11-05T14:30:00Z"
}
```

#### Erreurs possibles

**400 Bad Request - Prix invalide**
```json
{
    "prix": ["Le prix doit être strictement positif."]
}
```

**400 Bad Request - Points identiques**
```json
{
    "non_field_errors": ["Les points de départ et d'arrivée doivent être différents."]
}
```

**500 Internal Server Error - Mapbox échec**
```json
{
    "error": "Impossible de calculer la distance via Mapbox (NoRoute ou erreur API)"
}
```

---

### GET /trajets/

**Liste tous les trajets** de la base de données (pagination automatique).

#### Requête

**Headers**
```http
Authorization: ApiKey <uuid>
```

**Query Parameters (filtres optionnels)**

```
GET /api/trajets/?heure=matin&meteo=1&quartier_depart=Ekounou&limit=20&offset=0
```

| Paramètre | Type | Description |
|-----------|------|-------------|
| `heure` | String | Filtrer par tranche horaire |
| `meteo` | Integer | Filtrer par code météo 0-3 |
| `type_zone` | Integer | Filtrer par type zone 0-2 |
| `route_classe_dominante` | String | Filtrer par classe route |
| `search` | String | Recherche textuelle (labels départ/arrivée) |
| `ordering` | String | Tri (`-date_ajout`, `prix`, `-distance`) |
| `limit` | Integer | Pagination : nombre résultats (défaut 20) |
| `offset` | Integer | Pagination : décalage (défaut 0) |

#### Réponse réussie (200 OK)

```json
{
    "count": 150,
    "next": "http://localhost:8000/api/trajets/?limit=20&offset=20",
    "previous": null,
    "results": [
        {
            "id": 42,
            "point_depart": {...},
            "point_arrivee": {...},
            "distance": 5212.176,
            "prix": 250.0,
            "heure": "matin",
            "meteo": 1,
            "congestion_moyen": 45.3,
            "sinuosite_indice": 2.48,
            "date_ajout": "2025-11-05T14:30:00Z"
        },
        ...19 autres trajets...
    ]
}
```

---

### GET /trajets/{id}/

**Détail d'un trajet** spécifique par ID.

#### Requête

```
GET /api/trajets/42/
```

**Headers**
```http
Authorization: ApiKey <uuid>
```

#### Réponse réussie (200 OK)

```json
{
    "id": 42,
    "point_depart": {
        "id": 10,
        "coords_latitude": 3.8547,
        "coords_longitude": 11.5021,
        "label": "Polytechnique Yaoundé",
        "quartier": "Ngoa-Ekelle",
        "ville": "Yaoundé",
        "arrondissement": "Yaoundé II",
        "departement": "Mfoundi"
    },
    "point_arrivee": {...},
    "distance": 5212.176,
    "prix": 250.0,
    "heure": "matin",
    "meteo": 1,
    "type_zone": 0,
    "congestion_user": 5,
    "congestion_moyen": 45.3,
    "sinuosite_indice": 2.48,
    "route_classe_dominante": "primary",
    "nb_virages": 7,
    "force_virages": 71.8,
    "duree_estimee": 730.888,
    "date_ajout": "2025-11-05T14:30:00Z",
    "updated_at": "2025-11-05T14:30:00Z"
}
```

#### Erreurs possibles

**404 Not Found**
```json
{
    "detail": "Non trouvé."
}
```

---

### GET /trajets/stats/

**Statistiques globales** des trajets de la base de données.

#### Requête

```
GET /api/trajets/stats/
```

**Headers**
```http
Authorization: ApiKey <uuid>
```

#### Réponse réussie (200 OK)

```json
{
    "total_trajets": 150,
    "prix": {
        "moyen": 275.5,
        "min": 100.0,
        "max": 600.0,
        "mediane": 250.0
    },
    "distance": {
        "moyenne": 4850.3,
        "min": 500.0,
        "max": 15000.0
    },
    "repartition_heure": {
        "matin": 50,
        "apres-midi": 45,
        "soir": 35,
        "nuit": 20
    },
    "repartition_meteo": {
        "0": 80,
        "1": 40,
        "2": 20,
        "3": 10
    },
    "repartition_zone": {
        "0": 100,
        "1": 30,
        "2": 20
    },
    "top_quartiers_depart": [
        {"quartier": "Ekounou", "count": 25},
        {"quartier": "Ngoa-Ekelle", "count": 20},
        {"quartier": "Bastos", "count": 15}
    ],
    "top_quartiers_arrivee": [
        {"quartier": "Centre-ville", "count": 30},
        {"quartier": "Ekounou", "count": 22},
        {"quartier": "Melen", "count": 18}
    ]
}
```

---

### GET /points/

**Liste tous les points** d'intérêt (POI) de la base de données.

#### Requête

**Headers**
```http
Authorization: ApiKey <uuid>
```

**Query Parameters (filtres)**

```
GET /api/points/?ville=Yaoundé&quartier=Ekounou&search=Carrefour&limit=20&offset=0
```

| Paramètre | Type | Description |
|-----------|------|-------------|
| `ville` | String | Filtrer par ville |
| `quartier` | String | Filtrer par quartier |
| `arrondissement` | String | Filtrer par arrondissement |
| `search` | String | Recherche textuelle (label, quartier, ville) |
| `ordering` | String | Tri (`-created_at`, `label`) |
| `limit` | Integer | Pagination : nombre résultats |
| `offset` | Integer | Pagination : décalage |

#### Réponse réussie (200 OK)

```json
{
    "count": 75,
    "next": "http://localhost:8000/api/points/?limit=20&offset=20",
    "previous": null,
    "results": [
        {
            "id": 10,
            "coords_latitude": 3.8547,
            "coords_longitude": 11.5021,
            "label": "Polytechnique Yaoundé",
            "quartier": "Ngoa-Ekelle",
            "ville": "Yaoundé",
            "arrondissement": "Yaoundé II",
            "departement": "Mfoundi",
            "created_at": "2025-11-05T10:00:00Z"
        },
        ...19 autres points...
    ]
}
```

---

### GET /points/{id}/

**Détail d'un point** d'intérêt spécifique.

#### Requête

```
GET /api/points/10/
```

**Headers**
```http
Authorization: ApiKey <uuid>
```

#### Réponse réussie (200 OK)

```json
{
    "id": 10,
    "coords_latitude": 3.8547,
    "coords_longitude": 11.5021,
    "label": "Polytechnique Yaoundé",
    "quartier": "Ngoa-Ekelle",
    "ville": "Yaoundé",
    "arrondissement": "Yaoundé II",
    "departement": "Mfoundi",
    "created_at": "2025-11-05T10:00:00Z",
    "updated_at": "2025-11-05T10:00:00Z"
}
```

---

### GET /health/

**Health check** de l'API (aucune authentification requise).

#### Requête

```
GET /api/health/
```

**Headers** : Aucun header requis (endpoint public).

#### Réponse réussie (200 OK)

```json
{
    "status": "healthy",
    "timestamp": "2025-11-05T14:30:00Z",
    "version": "1.0.0",
    "checks": {
        "database": "ok",
        "redis": "ok",
        "mapbox": "ok",
        "nominatim": "ok",
        "openmeteo": "ok"
    },
    "stats": {
        "total_trajets": 150,
        "total_points": 75,
        "total_api_keys": 5
    }
}
```

#### Erreurs possibles

**503 Service Unavailable**
```json
{
    "status": "unhealthy",
    "timestamp": "2025-11-05T14:30:00Z",
    "checks": {
        "database": "error",
        "redis": "ok",
        "mapbox": "timeout",
        "nominatim": "ok",
        "openmeteo": "ok"
    },
    "errors": [
        "Database connection failed",
        "Mapbox API timeout"
    ]
}
```

---

## Modèles de données

### Point (POI)

```json
{
    "id": 10,
    "coords_latitude": 3.8547,
    "coords_longitude": 11.5021,
    "label": "Polytechnique Yaoundé",
    "quartier": "Ngoa-Ekelle",
    "ville": "Yaoundé",
    "arrondissement": "Yaoundé II",
    "departement": "Mfoundi",
    "created_at": "2025-11-05T10:00:00Z",
    "updated_at": "2025-11-05T10:00:00Z"
}
```

| Champ | Type | Description |
|-------|------|-------------|
| `id` | Integer | ID unique point |
| `coords_latitude` | Float | Latitude décimale (-90 à 90) |
| `coords_longitude` | Float | Longitude décimale (-180 à 180) |
| `label` | String | Nom POI (ex. "Carrefour Ekounou") |
| `quartier` | String/null | Quartier/sous-quartier |
| `ville` | String/null | Ville (ex. "Yaoundé") |
| `arrondissement` | String/null | Commune/arrondissement |
| `departement` | String/null | Département administratif |
| `created_at` | DateTime | Date création ISO 8601 |
| `updated_at` | DateTime | Date dernière modification |

### Trajet

```json
{
    "id": 42,
    "point_depart": {...Point...},
    "point_arrivee": {...Point...},
    "distance": 5212.176,
    "prix": 250.0,
    "heure": "matin",
    "meteo": 1,
    "type_zone": 0,
    "congestion_user": 5,
    "congestion_moyen": 45.3,
    "sinuosite_indice": 2.48,
    "route_classe_dominante": "primary",
    "nb_virages": 7,
    "force_virages": 71.8,
    "duree_estimee": 730.888,
    "date_ajout": "2025-11-05T14:30:00Z",
    "updated_at": "2025-11-05T14:30:00Z"
}
```

| Champ | Type | Description |
|-------|------|-------------|
| `id` | Integer | ID unique trajet |
| `point_depart` | Object | Point départ (nested, voir Point) |
| `point_arrivee` | Object | Point arrivée (nested) |
| `distance` | Float | Distance routière en mètres (Mapbox) |
| `prix` | Float | Prix payé en CFA |
| `heure` | String/null | Tranche horaire : `"matin"`, `"apres-midi"`, `"soir"`, `"nuit"` |
| `meteo` | Integer/null | Code météo : `0` (soleil), `1` (pluie légère), `2` (pluie forte), `3` (orage) |
| `type_zone` | Integer/null | Type zone : `0` (urbaine), `1` (mixte), `2` (rurale) |
| `congestion_user` | Integer/null | Embouteillages ressentis (1-10 scale) |
| `congestion_moyen` | Float/null | Congestion moyenne Mapbox (0-100) |
| `sinuosite_indice` | Float/null | Indice sinuosité route (≥1.0) |
| `route_classe_dominante` | String/null | Classe route principale : `"motorway"`, `"primary"`, `"secondary"`, `"tertiary"`, etc. |
| `nb_virages` | Integer/null | Nombre de virages comptabilisés |
| `force_virages` | Float/null | Force virages (°/km) |
| `duree_estimee` | Float/null | Durée trajet en secondes (Mapbox avec trafic) |
| `date_ajout` | DateTime | Date création ISO 8601 |
| `updated_at` | DateTime | Date modification |

---

## ⚠️ Codes d'erreur

| Code HTTP | Signification | Exemple |
|-----------|---------------|---------|
| **200** | ✅ Succès | Estimation réussie |
| **201** | ✅ Créé | Trajet ajouté |
| **400** | ❌ Requête invalide | Paramètres manquants/invalides |
| **401** | ❌ Non authentifié | Clé API manquante ou invalide |
| **404** | ❌ Non trouvé | Trajet ID inexistant |
| **500** | ❌ Erreur serveur | Mapbox indisponible, erreur BD |
| **503** | ❌ Service indisponible | Health check échec |

---

## Exemples complets

### Exemple 1 : Estimation simple (Python)

```python
import requests

API_KEY = "550e8400-e29b-41d4-a716-446655440000"
BASE_URL = "http://localhost:8000/api"

headers = {
    'Authorization': f'ApiKey {API_KEY}',
    'Content-Type': 'application/json'
}

# Estimation avec coordonnées
data = {
    "depart": {"lat": 3.8547, "lon": 11.5021},
    "arrivee": {"lat": 3.8667, "lon": 11.5174},
    "heure": "matin",
    "meteo": 1
}

response = requests.post(f"{BASE_URL}/estimate/", headers=headers, json=data)

if response.status_code == 200:
    result = response.json()
    print(f"Statut : {result['statut']}")
    print(f"Prix moyen : {result['prix_moyen']} CFA")
    print(f"Prix min-max : {result['prix_min']}-{result['prix_max']} CFA")
    print(f"Fiabilité : {result['fiabilite']:.0%}")
    print(f"Message : {result['message']}")
else:
    print(f"Erreur {response.status_code} : {response.json()}")
```

### Exemple 2 : Estimation avec noms de lieux (JavaScript)

```javascript
const API_KEY = "550e8400-e29b-41d4-a716-446655440000";
const BASE_URL = "http://localhost:8000/api";

const headers = {
    'Authorization': `ApiKey ${API_KEY}`,
    'Content-Type': 'application/json'
};

const data = {
    depart: "Polytechnique Yaoundé",
    arrivee: "Carrefour Ekounou",
    heure: null,  // Auto-détecté
    meteo: null   // Auto-détecté via OpenMeteo
};

fetch(`${BASE_URL}/estimate/`, {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(data)
})
.then(response => response.json())
.then(result => {
    console.log(`Statut : ${result.statut}`);
    console.log(`Prix moyen : ${result.prix_moyen} CFA`);
    console.log(`Fiabilité : ${(result.fiabilite * 100).toFixed(0)}%`);
    
    // Afficher estimation météo opposée
    if (result.ajustements_appliques.meteo_opposee) {
        const meteo_opp = result.ajustements_appliques.meteo_opposee;
        console.log(`Si météo ${meteo_opp.label} : ${meteo_opp.prix_estime} CFA`);
    }
})
.catch(error => console.error('Erreur :', error));
```

### Exemple 3 : Ajouter un trajet (curl)

```bash
curl -X POST http://localhost:8000/api/trajets/ \
  -H "Authorization: ApiKey 550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{
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
    "prix": 250,
    "heure": "matin",
    "meteo": 1,
    "congestion_user": 5
  }'
```

### Exemple 4 : Filtrer trajets (Python)

```python
# Récupérer trajets du matin avec pluie légère
params = {
    'heure': 'matin',
    'meteo': 1,
    'ordering': '-date_ajout',
    'limit': 10
}

response = requests.get(
    f"{BASE_URL}/trajets/",
    headers=headers,
    params=params
)

trajets = response.json()['results']
for trajet in trajets:
    print(f"{trajet['point_depart']['label']} → {trajet['point_arrivee']['label']} : {trajet['prix']} CFA")
```

### Exemple 5 : Health check (sans auth)

```bash
curl http://localhost:8000/api/health/
```

---

## Limites et quotas

### Limites par défaut

| Limite | Valeur | Description |
|--------|--------|-------------|
| **Rate limit** | 100 req/min | Maximum requêtes par minute par clé API |
| **Pagination** | 20 résultats | Pagination par défaut (max 100) |
| **Timeout** | 30 secondes | Timeout requêtes externes (Mapbox, Nominatim) |
| **Coords max** | 25 points | Mapbox Matrix API (limitation gratuite) |

### Quotas APIs externes

**Mapbox (Gratuit)** :
- Directions : 100 000 req/mois
- Matrix : 100 000 req/mois
- Isochrone : 100 000 req/mois
- Geocoding : 100 000 req/mois

**Nominatim (Gratuit)** :
- Rate limit : 1 req/seconde (respecté via cache)

**OpenMeteo (Gratuit)** :
- Illimité (cache 15 min)

### Optimisations implémentées

✅ **Caching agressif** :
- Mapbox : 1h TTL (trafic dynamique)
- Nominatim : 24h TTL (adresses stables)
- OpenMeteo : 15 min TTL (météo)
- Isochrones : 24h TTL (topologie stable)

✅ **Batch requests** :
- Matrix API utilisée pour trajets similaires (1 req au lieu de N)

✅ **Fallbacks** :
- Si Mapbox échoue → cercles Haversine
- Si Nominatim échoue → labels génériques

---

## Support & Ressources

**Contact** : donfackarthur750@gmail.com 
**Documentation Mapbox** : https://docs.mapbox.com/api/  
**Documentation OpenMeteo** : https://open-meteo.com/en/docs  
**Documentation Nominatim** : https://nominatim.org/release-docs/latest/  
