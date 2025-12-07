<div align="center">

<img src="doc/taxi-logo.png" alt="Taxi Fare Calculator" width="200"/>

# Taxi Fare Calculator API

### Service d'Estimation Intelligente des Prix de Taxi au Cameroun

[![Django](https://img.shields.io/badge/Django-5.2.1-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.0-ff1709?style=for-the-badge&logo=django&logoColor=white)](https://www.django-rest-framework.org/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Mapbox](https://img.shields.io/badge/Mapbox-API-000000?style=for-the-badge&logo=mapbox&logoColor=white)](https://www.mapbox.com/)

[**Documentation**](#documentation-complète) • [**Installation**](#installation) • [**API Docs**](API_DOC.md) • [**Guide ML**](#guide-dimplémentation-ml)

</div>

---

## Vue d'Ensemble

API REST complète pour **estimer intelligemment les prix de courses de taxi** au Cameroun (focus Yaoundé). Utilise une approche hybride combinant :

- **Matching par Similarité** : Recherche de trajets similaires avec isochrones Mapbox (2D hierarchy: périmètres × variables)
- ** Machine Learning** : Classification multiclasse (18 tranches de prix fixes) avec features géospatiales
- **Géolocalisation Avancée** : Intégration Mapbox (Directions, Matrix, Isochrone) + Nominatim + OpenMeteo
- **Données Communautaires** : Base de données enrichie par les utilisateurs réels

### Caractéristiques Principales

- ✅ **Estimation en temps réel** avec ajustements contextuels (heure, météo, congestion, sinuosité)
- ✅ **4 niveaux de fallback** : Similarité étroite -> élargie -> variables différentes -> ML
- ✅ **API RESTful** avec authentification par clé API et rate limiting
- ✅ **Admin Django** complet pour gestion données et statistiques
- ✅ **Documentation exhaustive** (API_DOC.md 73k tokens, docstrings détaillées)

---

## 🛠️ Stack Technique

| Catégorie | Technologies |
|-----------|-------------|
| **Backend** | Django 5.2.1, Django REST Framework 3.16.0 |
| **Python** | Python 3.11+ |
| **Géospatial** | Shapely 2.0.6 (isochrones), Geopy 2.4.1 |
| **APIs Externes** | Mapbox API, Nominatim OSM, OpenMeteo |
| **Async Tasks** | Celery 5.4.0, Redis 5.0.7 |
| **ML (À implémenter)** | scikit-learn, XGBoost (classification 18 classes) |
| **Base de Données** | PostgreSQL / SQLite (dev) |
| **Conteneurisation** | Docker, Docker Compose |

---

## Installation

### Prérequis

- Python 3.11+
- pip 23.0+
- Virtualenv (recommandé)
- Redis (pour Celery)
- Token Mapbox API ([gratuit 50k req/mois](https://account.mapbox.com/))

### Configuration Rapide

```bash
# 1. Cloner le repo
git clone https://github.com/projet-synthese-gi26/fare-calculator-service-v2.git
cd fare-calculator-service-v2

# 2. Créer environnement virtuel
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Installer dépendances
pip install -r requirements.txt

# 4. Configurer variables d'environnement
cp .env.example .env
# Éditer .env avec votre MAPBOX_ACCESS_TOKEN

# 5. Migrations base de données
python manage.py migrate

# 6. Créer superuser admin
python manage.py createsuperuser

# 7. Lancer serveur développement
python manage.py runserver
```

L'API est maintenant accessible à : **http://localhost:8000/api/**

---

## Démarrage Rapide

### 1. Générer une Clé API

Accédez à l'admin Django : http://localhost:8000/admin/

- **Login** avec superuser créé
- Naviguez vers **Core > Api Keys**
- Cliquez **"Ajouter API Key"**
- Notez l'UUID généré (ex: `550e8400-e29b-41d4-a716-446655440000`)


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
    "prix_moyen": 300.0,
    "prix_min": 250.0,
    "prix_max": 350.0,
    "fiabilite": 0.55,
    "message": "Trajet inconnu dans notre base. Estimation ML prioritaire avec transparence des features.",
    "estimations_supplementaires": {
        "ml_prediction": 300,
        "features_utilisees": {
            "distance_metres": 5738.7,
            "duree_secondes": 1207.8,
            "congestion": 50,
            "sinuosite": 1.30,
            "nb_virages": 7,
            "heure": "apres-midi",
            "meteo": 0,
            "type_zone": 0
        }
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
        "distance_metres": 5738.7,
        "duree_secondes": 1207.8,
        "heure": "apres-midi",
        "meteo": 0,
        "type_zone": 0,
        "congestion_mapbox": null,
        "sinuosite_indice": 1.30,
        "nb_virages_estimes": 7,
        "route_classe": "primary"
    },
    "ajustements_appliques": {
        "note": "Aucun ajustement (pas de trajets similaires en BD)"
    },
    "suggestions": [
        "Distance calculee : 5.74 km",
        "Duree estimee : 20.1 minutes",
        "Fiabilite faible : negociez prudemment",
        "Votre contribution enrichira les estimations futures !"
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
| `nb_trajets_utilises` | Integer/Null | Nombre de trajets BD utilisés (absent/0 pour inconnu) |
| `details_trajet` | Object | Informations complètes trajet (départ, arrivée, distance, durée) |
| `ajustements_appliques` | Object | Détails ajustements prix (congestion, météo, heure) |
| `estimations_supplementaires` | Object | (Inconnu) Données ML : `ml_prediction`, `features_utilisees` |
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

**Alternative GET** pour estimation (conversion query params -> POST).

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
    print(f"{trajet['point_depart']['label']} -> {trajet['point_arrivee']['label']} : {trajet['prix']} CFA")
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
- Si Mapbox échoue -> cercles Haversine
- Si Nominatim échoue -> labels génériques

---

## Support & Ressources

**Contact** : donfackarthur750@gmail.com 
**Documentation Mapbox** : https://docs.mapbox.com/api/  
**Documentation OpenMeteo** : https://open-meteo.com/en/docs  
**Documentation Nominatim** : https://nominatim.org/release-docs/latest/  

---

##  Guide d'Implémentation ML pour l'Équipe

Cette section documente les **3 fonctions principales à implémenter** dans `core/views.py`. Ces fonctions sont actuellement des stubs (`pass` + docstrings détaillées) pour permettre à l'équipe ML de les compléter selon les algorithmes décrits dans la documentation du projet.

### ⚠️ CRITIQUE : Classes de Prix Taxis (Pas de Régression !)

**Les prix taxis au Cameroun ne sont PAS continus mais appartiennent à des TRANCHES FIXES** :

```python
# Constante définie dans settings.py
PRIX_CLASSES_CFA = [
    100, 150, 200, 250, 300, 350, 400, 450, 500, 
    600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000
]
# 18 classes au total
# Variation minimale : 50 CFA
# Prix minimum : 100 CFA
# Prix maximum : 2000 CFA
```

**Conséquences pour l'implémentation** :

1. **Fonction `check_similar_match()`** : 
   - Tous prix retournés (prix_moyen, prix_min, prix_max) doivent être arrondis aux classes valides
   - Helper `_arrondir_prix_vers_classe(prix)` créée pour mapper float -> classe proche
   - Ex: 247.8 CFA -> 250 CFA, 312.5 -> 300 CFA

2. **Fonction `predict_prix_ml()`** :
   - Modèle = **Classification Multiclasse** (18 classes), PAS régression
   - Return type : `int` (classe valide), pas `float`
   - Métriques : accuracy, f1-score, tolérance ±1 classe (PAS R²/RMSE)

3. **Fonction `fallback_inconnu()`** :
   - Toutes 4 estimations doivent retourner `int` (classes valides)
   - Même estimation distance-based ou zone-based -> arrondir avec `_arrondir_prix_vers_classe()`

### ⚠️ IMPORTANT : Architecture Correcte du Système de Similarité

**IL N'Y A PAS de distinction "exact vs similaire"** dans ce projet ! La logique réelle est :

```
1. check_similar_match()        ❌ À IMPLÉMENTER - FONCTION CENTRALE
   │
   ├─ NIVEAU 1 : Périmètre ÉTROIT (isochrone 2min / cercle 50m fallback)
   │   └─ Match trouvé -> Prix DIRECT sans ajustement (fiabilité 0.9-0.95)
   │
   ├─ NIVEAU 2 : Périmètre ÉLARGI (isochrone 5min / cercle 150m fallback)
   │   └─ Match trouvé -> Prix AJUSTÉ (+distance extra, congestion, sinuosité)
   │
   ├─ NIVEAU 3 : Fallback VARIABLES (ignorer heure/météo exactes)
   │   └─ Match trouvé avec heure/météo différentes -> Prix ajusté + note
   │
   └─ Aucun match -> Passer à fallback_inconnu()
   
2. fallback_inconnu()           ❌ À IMPLÉMENTER - ESTIMATIONS MULTIPLES
   └─ Retourne 4 estimations (distance-based, standardisé, zone-based, ML)
   
3. predict_prix_ml()           ❌ À IMPLÉMENTER - MODÈLE ML
   └─ Appelé par fallback_inconnu() pour estimation ML
   
4. train_ml_model()            ❌ À IMPLÉMENTER - ENTRAÎNEMENT (Celery task)
   └─ Entraîne modèle ML sur données BD accumulées
```

**Concept clé** : `check_similar_match()` gère TOUS les niveaux de similarité (étroit, élargi, variables différentes) en un seul flux progressif. C'est une recherche intelligente avec **périmètres isochrones Mapbox** (temporels, basés sur trafic) et **fallback cercles Haversine** si Mapbox échoue.

---

### Fonction 1 (CENTRALE) : `check_similar_match()`

**Objectif** : Rechercher trajets similaires avec 3 niveaux de périmètres progressifs (étroit->élargi->variables différentes). Fonction CENTRALE qui remplace l'idée erronée de `check_exact_match()` séparé.

**Localisation** : `core/views.py`, lignes ~400-700 (voir docstring détaillée)

**Signature** :
```python
def check_similar_match(
    depart_coords: List[float],
    arrivee_coords: List[float],
    distance_mapbox: float,
    heure: Optional[str],
    meteo: Optional[int],
    type_zone: Optional[int],
    congestion_user: Optional[int]
) -> Optional[Dict]:
```

#### Logique Hiérarchique Complète (3 Niveaux)

Cette fonction implémente **LE CŒUR DU SYSTÈME** décrit dans `doc/DETAILS SUR MAPBOX DANS LE PROJET.MD`. Elle cherche des trajets similaires en élargissant progressivement les critères :

---

#### **NIVEAU 1 : PÉRIMÈTRE ÉTROIT** (isochrone 2min / cercle 50m fallback)

**Concept** : Trouver trajets BD où les points de départ/arrivée sont accessibles en **2 minutes de trajet** (ou **50m en ligne droite** si Mapbox échoue) depuis les points demandés, ET avec heure/météo **EXACTES**.

**Étape 1.1 : Filtrage Grossier par Quartiers**

Optimisation critique pour éviter de générer des isochrones pour des milliers de trajets :

```python
from .utils import nominatim_client

# Extraire quartiers depuis coords via reverse-geocoding
info_depart = nominatim_client.reverse_geocode(lat=depart_coords[0], lon=depart_coords[1])
info_arrivee = nominatim_client.reverse_geocode(lat=arrivee_coords[0], lon=arrivee_coords[1])

quartier_depart = info_depart['address'].get('suburb') or info_depart['address'].get('neighbourhood')
quartier_arrivee = info_arrivee['address'].get('suburb') or info_arrivee['address'].get('neighbourhood')
arrondissement_depart = info_depart['address'].get('municipality')
arrondissement_arrivee = info_arrivee['address'].get('municipality')

# Filtrer BD par quartiers/arrondissements (réduit de 1000+ à ~20-50 trajets)
from django.db.models import Q

trajets_candidats = Trajet.objects.filter(
    Q(point_depart__quartier__in=[quartier_depart, arrondissement_depart]) |
    Q(point_depart__arrondissement=arrondissement_depart)
).filter(
    Q(point_arrivee__quartier__in=[quartier_arrivee, arrondissement_arrivee]) |
    Q(point_arrivee__arrondissement=arrondissement_arrivee)
).select_related('point_depart', 'point_arrivee')

# Filtrer aussi par heure/météo EXACTES pour niveau 1
if heure is not None:
    trajets_candidats = trajets_candidats.filter(heure=heure)
if meteo is not None:
    trajets_candidats = trajets_candidats.filter(meteo=meteo)

if trajets_candidats.count() < 2:
    # Pas assez de candidats, skip niveau 1, passer niveau 2
    pass
```

**Étape 1.2 : Génération Isochrones Mapbox 2 Minutes**

Générer zones accessibles en 2 minutes (périmètre ÉTROIT) :

```python
from .utils import mapbox_client

# Isochrone 2 minutes autour du départ demandé
try:
    isochrone_depart_etroit = mapbox_client.get_isochrone(
        coords=(depart_coords[0], depart_coords[1]),  # (lat, lon)
        contours_minutes=[2],
        profile='driving-traffic'
    )
    
    # Convertir GeoJSON en polygone Shapely pour tests containment
    from shapely.geometry import shape, Point as ShapelyPoint
    polygon_depart_etroit = shape(isochrone_depart_etroit['features'][0]['geometry'])
    
except Exception as e:
    # Fallback cercles Haversine si Mapbox échoue (routes manquantes Cameroun)
    logger.warning(f"Isochrone Mapbox 2min échoué pour départ {depart_coords}: {e}")
    polygon_depart_etroit = None  # Utiliser cercles Haversine ci-dessous

# Répéter pour arrivée
try:
    isochrone_arrivee_etroit = mapbox_client.get_isochrone(
        coords=(arrivee_coords[0], arrivee_coords[1]),
        contours_minutes=[2],
        profile='driving-traffic'
    )
    polygon_arrivee_etroit = shape(isochrone_arrivee_etroit['features'][0]['geometry'])
except Exception as e:
    logger.warning(f"Isochrone Mapbox 2min échoué pour arrivée {arrivee_coords}: {e}")
    polygon_arrivee_etroit = None
```

**Étape 1.3 : Vérification Containment (Isochrones OU Cercles Fallback)**

```python
from .utils import haversine_distance

trajets_niveau1 = []

for trajet in trajets_candidats:
    pt_depart_bd = (trajet.point_depart.coords_latitude, trajet.point_depart.coords_longitude)
    pt_arrivee_bd = (trajet.point_arrivee.coords_latitude, trajet.point_arrivee.coords_longitude)
    
    # Vérifier départ : Isochrone OU cercle 50m
    if polygon_depart_etroit is not None:
        # Méthode 1 : Isochrone Mapbox (préférée)
        shapely_pt_depart = ShapelyPoint(pt_depart_bd[1], pt_depart_bd[0])  # (lon, lat) pour Shapely
        depart_match = polygon_depart_etroit.contains(shapely_pt_depart)
    else:
        # Méthode 2 : Cercle Haversine 50m fallback
        dist_depart = haversine_distance(depart_coords, pt_depart_bd)  # mètres
        depart_match = (dist_depart <= settings.CIRCLE_RADIUS_ETROIT_M)  # 50m
    
    # Vérifier arrivée : Idem
    if polygon_arrivee_etroit is not None:
        shapely_pt_arrivee = ShapelyPoint(pt_arrivee_bd[1], pt_arrivee_bd[0])
        arrivee_match = polygon_arrivee_etroit.contains(shapely_pt_arrivee)
    else:
        dist_arrivee = haversine_distance(arrivee_coords, pt_arrivee_bd)
        arrivee_match = (dist_arrivee <= settings.CIRCLE_RADIUS_ETROIT_M)
    
    # Si DÉPART + ARRIVÉE dans périmètre étroit : MATCH NIVEAU 1 ✓
    if depart_match and arrivee_match:
        # Vérifier distance routière ±10% (tolérance petite pour niveau étroit)
        tolerance = 0.10  # 10%
        if trajet.distance:
            ecart_distance = abs(distance_mapbox - trajet.distance) / trajet.distance
            if ecart_distance <= tolerance:
                trajets_niveau1.append(trajet)

if trajets_niveau1:
    # MATCH ÉTROIT TROUVÉ -> Retourner prix DIRECT sans ajustement
    prix_moyen = sum(t.prix for t in trajets_niveau1) / len(trajets_niveau1)
    prix_min = min(t.prix for t in trajets_niveau1)
    prix_max = max(t.prix for t in trajets_niveau1)
    
    return {
        'statut': 'similaire_etroit',
        'prix_moyen': round(prix_moyen, 2),
        'prix_min': prix_min,
        'prix_max': prix_max,
        'fiabilite': 0.93,  # Fiabilité très haute (périmètre très proche + heure/météo exactes)
        'message': f"Estimation basée sur {len(trajets_niveau1)} trajets très similaires (périmètre 2min, heure/météo exactes).",
        'nb_trajets_utilises': len(trajets_niveau1),
        'details_trajet': {
            'depart': {
                'label': trajets_niveau1[0].point_depart.label,
                'coords': list(depart_coords),
                'quartier': trajets_niveau1[0].point_depart.quartier,
                'ville': trajets_niveau1[0].point_depart.ville
            },
            'arrivee': {
                'label': trajets_niveau1[0].point_arrivee.label,
                'coords': list(arrivee_coords),
                'quartier': trajets_niveau1[0].point_arrivee.quartier,
                'ville': trajets_niveau1[0].point_arrivee.ville
            },
            'distance_estimee': distance_mapbox,
            'heure': heure,
            'meteo': meteo,
            'type_zone': type_zone
        },
        'ajustements_appliques': {
            'distance_extra_metres': 0,  # Périmètre étroit = pas d'ajustement
            'ajustement_distance_cfa': 0.0,
            'facteur_ajustement_total': 1.0
        },
        'suggestions': [
            'Trajets très similaires trouvés (périmètre 2min)',
            'Prix direct sans ajustement (haute fiabilité)',
            f'Négociez entre {prix_min} et {prix_max} CFA selon embouteillages'
        ]
    }
```

---

#### **NIVEAU 2 : PÉRIMÈTRE ÉLARGI** (isochrone 5min / cercle 150m fallback)

Si aucun match niveau 1, recommencer avec périmètres plus larges + calcul ajustements :

```python
# Générer isochrones 5 minutes (ou cercles 150m fallback)
try:
    isochrone_depart_elargi = mapbox_client.get_isochrone(
        coords=(depart_coords[0], depart_coords[1]),
        contours_minutes=[5],
        profile='driving-traffic'
    )
    polygon_depart_elargi = shape(isochrone_depart_elargi['features'][0]['geometry'])
except Exception as e:
    polygon_depart_elargi = None  # Fallback cercles 150m

try:
    isochrone_arrivee_elargi = mapbox_client.get_isochrone(
        coords=(arrivee_coords[0], arrivee_coords[1]),
        contours_minutes=[5],
        profile='driving-traffic'
    )
    polygon_arrivee_elargi = shape(isochrone_arrivee_elargi['features'][0]['geometry'])
except Exception as e:
    polygon_arrivee_elargi = None

# Vérifier containment avec périmètre élargi
trajets_niveau2 = []

for trajet in trajets_candidats:
    pt_depart_bd = (trajet.point_depart.coords_latitude, trajet.point_depart.coords_longitude)
    pt_arrivee_bd = (trajet.point_arrivee.coords_latitude, trajet.point_arrivee.coords_longitude)
    
    # Isochrone 5min OU cercle 150m
    if polygon_depart_elargi is not None:
        shapely_pt_depart = ShapelyPoint(pt_depart_bd[1], pt_depart_bd[0])
        depart_match = polygon_depart_elargi.contains(shapely_pt_depart)
    else:
        dist_depart = haversine_distance(depart_coords, pt_depart_bd)
        depart_match = (dist_depart <= settings.CIRCLE_RADIUS_ELARGI_M)  # 150m
    
    if polygon_arrivee_elargi is not None:
        shapely_pt_arrivee = ShapelyPoint(pt_arrivee_bd[1], pt_arrivee_bd[0])
        arrivee_match = polygon_arrivee_elargi.contains(shapely_pt_arrivee)
    else:
        dist_arrivee = haversine_distance(arrivee_coords, pt_arrivee_bd)
        arrivee_match = (dist_arrivee <= settings.CIRCLE_RADIUS_ELARGI_M)
    
    if depart_match and arrivee_match:
        trajets_niveau2.append(trajet)

if trajets_niveau2:
    # MATCH ÉLARGI TROUVÉ -> Calculer ajustements prix
    
    # Calculer distances extra via Mapbox Matrix API
    coords_depart_candidats = [depart_coords] + [
        (t.point_depart.coords_latitude, t.point_depart.coords_longitude) 
        for t in trajets_niveau2
    ]
    
    try:
        matrix_depart = mapbox_client.get_matrix(
            coordinates=coords_depart_candidats,
            sources=[0],  # Nouveau départ
            destinations=list(range(1, len(coords_depart_candidats)))  # Départs BD
        )
        distances_extra_depart = matrix_depart['distances'][0]  # Liste distances en mètres
    except Exception as e:
        # Fallback Haversine si Matrix échoue
        logger.warning(f"Matrix API échec départ: {e}")
        distances_extra_depart = [
            haversine_distance(depart_coords, (t.point_depart.coords_latitude, t.point_depart.coords_longitude))
            for t in trajets_niveau2
        ]
    
    # Idem pour arrivée
    coords_arrivee_candidats = [arrivee_coords] + [
        (t.point_arrivee.coords_latitude, t.point_arrivee.coords_longitude)
        for t in trajets_niveau2
    ]
    
    try:
        matrix_arrivee = mapbox_client.get_matrix(
            coordinates=coords_arrivee_candidats,
            sources=[0],
            destinations=list(range(1, len(coords_arrivee_candidats)))
        )
        distances_extra_arrivee = matrix_arrivee['distances'][0]
    except Exception as e:
        logger.warning(f"Matrix API échec arrivée: {e}")
        distances_extra_arrivee = [
            haversine_distance(arrivee_coords, (t.point_arrivee.coords_latitude, t.point_arrivee.coords_longitude))
            for t in trajets_niveau2
        ]
    
    # Calculer ajustements pour chaque trajet
    trajets_avec_ajustements = []
    
    for i, trajet in enumerate(trajets_niveau2):
        distance_extra_total = distances_extra_depart[i] + distances_extra_arrivee[i]  # mètres
        distance_extra_km = distance_extra_total / 1000
        
        # Ajustement 1 : Distance extra
        ajust_distance_cfa = distance_extra_km * settings.ADJUSTMENT_PRIX_PAR_KM  # Ex : 50 CFA/km
        
        # Ajustement 2 : Congestion différente (si user fournit congestion_user)
        ajust_congestion_pourcent = 0
        if congestion_user and trajet.congestion_moyen:
            delta_congestion = (congestion_user * 10) - trajet.congestion_moyen  # user 1-10 -> 0-100
            if delta_congestion > 20:  # Si >20 points de congestion extra
                ajust_congestion_pourcent = settings.ADJUSTMENT_CONGESTION_POURCENT  # +10%
        
        # Ajustement 3 : Sinuosité (si trajet BD tortueux)
        ajust_sinuosite_cfa = 0
        if trajet.sinuosite_indice and trajet.sinuosite_indice > 1.5:
            ajust_sinuosite_cfa = settings.ADJUSTMENT_SINUOSITE_CFA  # +20 CFA si sinueux
        
        # Calcul prix ajusté
        prix_base = trajet.prix
        prix_ajuste = (prix_base + ajust_distance_cfa + ajust_sinuosite_cfa) * (1 + ajust_congestion_pourcent / 100)
        
        trajets_avec_ajustements.append({
            'trajet': trajet,
            'prix_ajuste': prix_ajuste,
            'ajustements': {
                'distance_extra_metres': int(distance_extra_total),
                'ajustement_distance_cfa': round(ajust_distance_cfa, 2),
                'ajustement_congestion_pourcent': ajust_congestion_pourcent,
                'ajustement_sinuosite_cfa': ajust_sinuosite_cfa,
                'facteur_ajustement_total': round(prix_ajuste / prix_base, 2)
            }
        })
    
    # Trier par ajustement croissant (plus proches d'abord)
    trajets_avec_ajustements.sort(key=lambda x: x['ajustements']['facteur_ajustement_total'])
    
    # Moyennes prix ajustés
    prix_moyen = sum(t['prix_ajuste'] for t in trajets_avec_ajustements) / len(trajets_avec_ajustements)
    prix_min = min(t['prix_ajuste'] for t in trajets_avec_ajustements)
    prix_max = max(t['prix_ajuste'] for t in trajets_avec_ajustements)
    
    # Ajustements moyens pour réponse
    ajustements_moyens = {
        'distance_extra_metres': int(sum(t['ajustements']['distance_extra_metres'] for t in trajets_avec_ajustements) / len(trajets_avec_ajustements)),
        'ajustement_distance_cfa': round(sum(t['ajustements']['ajustement_distance_cfa'] for t in trajets_avec_ajustements) / len(trajets_avec_ajustements), 2),
        'ajustement_congestion_pourcent': int(sum(t['ajustements']['ajustement_congestion_pourcent'] for t in trajets_avec_ajustements) / len(trajets_avec_ajustements)),
        'facteur_ajustement_total': round(prix_moyen / sum(t['trajet'].prix for t in trajets_avec_ajustements) * len(trajets_avec_ajustements), 2)
    }
    
    return {
        'statut': 'similaire_elargi',
        'prix_moyen': round(prix_moyen, 2),
        'prix_min': round(prix_min, 2),
        'prix_max': round(prix_max, 2),
        'fiabilite': 0.78,  # Fiabilité moyenne (périmètre élargi + ajustements)
        'message': f"Estimation ajustée depuis {len(trajets_avec_ajustements)} trajets similaires (+{ajustements_moyens['ajustement_distance_cfa']:.0f} CFA pour {ajustements_moyens['distance_extra_metres']}m extra).",
        'nb_trajets_utilises': len(trajets_avec_ajustements),
        'details_trajet': {
            'depart': {
                'label': f"Proche {trajets_avec_ajustements[0]['trajet'].point_depart.label}",
                'coords': list(depart_coords),
                'quartier': trajets_avec_ajustements[0]['trajet'].point_depart.quartier,
                'ville': trajets_avec_ajustements[0]['trajet'].point_depart.ville
            },
            'arrivee': {
                'label': f"Proche {trajets_avec_ajustements[0]['trajet'].point_arrivee.label}",
                'coords': list(arrivee_coords),
                'quartier': trajets_avec_ajustements[0]['trajet'].point_arrivee.quartier,
                'ville': trajets_avec_ajustements[0]['trajet'].point_arrivee.ville
            },
            'distance_estimee': distance_mapbox,
            'heure': heure,
            'meteo': meteo,
            'type_zone': type_zone
        },
        'ajustements_appliques': ajustements_moyens,
        'suggestions': [
            'Trajets similaires trouvés dans périmètre élargi (5min)',
            'Prix ajusté pour distance extra et conditions différentes',
            'Ajoutez votre prix après trajet pour affiner estimations'
        ]
    }
```

---

#### **NIVEAU 3 : FALLBACK VARIABLES** (ignorer heure/météo exactes)

Si toujours aucun match, recommencer niveaux 1+2 MAIS en **ignorant filtres heure/météo** :

```python
# Recommencer filtrage sans heure/météo
trajets_candidats_variables_diff = Trajet.objects.filter(
    Q(point_depart__quartier__in=[quartier_depart, arrondissement_depart]) |
    Q(point_depart__arrondissement=arrondissement_depart)
).filter(
    Q(point_arrivee__quartier__in=[quartier_arrivee, arrondissement_arrivee]) |
    Q(point_arrivee__arrondissement=arrondissement_arrivee)
).select_related('point_depart', 'point_arrivee')
# NE PAS filtrer par heure/météo ici

# Recommencer vérifications isochrones/cercles (niveaux 1 et 2)
# ... (même code que ci-dessus)

# Si match trouvé :
if trajets_variables_diff:
    # Calculer ajustements standards heure/météo
    trajet_ref = trajets_variables_diff[0]
    prix_base = trajet_ref.prix
    
    ajust_heure_cfa = 0
    note_heure = None
    if heure and trajet_ref.heure and heure != trajet_ref.heure:
        # Jour -> Nuit : +50 CFA
        if heure in ['matin', 'apres-midi', 'soir'] and trajet_ref.heure == 'nuit':
            ajust_heure_cfa = -settings.ADJUSTMENT_HEURE_JOUR_NUIT_CFA  # -50 CFA (BD est nuit, demandé jour)
            note_heure = f"Prix basé sur trajets de nuit (−50 CFA vs {heure} demandé)"
        elif heure == 'nuit' and trajet_ref.heure in ['matin', 'apres-midi', 'soir']:
            ajust_heure_cfa = settings.ADJUSTMENT_HEURE_JOUR_NUIT_CFA  # +50 CFA
            note_heure = f"Prix basé sur trajets de jour (+50 CFA vs nuit demandée)"
    
    ajust_meteo_cfa = 0
    note_meteo = None
    if meteo is not None and trajet_ref.meteo is not None and meteo != trajet_ref.meteo:
        # Soleil -> Pluie : +10%
        if meteo > trajet_ref.meteo:  # Demandé plus pluvieux que BD
            ajust_meteo_cfa = prix_base * (settings.ADJUSTMENT_METEO_SOLEIL_PLUIE_POURCENT / 100)  # +10%
            note_meteo = f"Ajustement +10% (BD soleil, demandé pluie)"
        else:
            ajust_meteo_cfa = -prix_base * 0.05  # -5% si inverse
            note_meteo = f"Ajustement −5% (BD pluie, demandé soleil)"
    
    prix_ajuste = prix_base + ajust_heure_cfa + ajust_meteo_cfa
    
    return {
        'statut': 'similaire_variables_diff',
        'prix_moyen': round(prix_ajuste, 2),
        'fiabilite': 0.68,  # Fiabilité plus faible (variables différentes)
        'message': f"Estimation basée sur {len(trajets_variables_diff)} trajets similaires à heure/météo différentes.",
        'ajustements_appliques': {
            'ajustement_heure_cfa': ajust_heure_cfa,
            'ajustement_meteo_cfa': round(ajust_meteo_cfa, 2),
            'note_variables': f"{note_heure or ''} {note_meteo or ''}".strip()
        },
        'suggestions': [
            '⚠️ Prix basé sur trajets à heure/météo différentes',
            'Ajustements standards appliqués (+50 CFA nuit, +10% pluie)',
            'Fiabilité réduite, négociez prudemment'
        ]
    }

# Si aucun match niveau 3 non plus -> Return None (passage à fallback_inconnu)
return None
```

**Étape 2 : Filtrage BD avec polygones**

Convertir les isochrones en polygones et filtrer la BD :

```python
from shapely.geometry import shape, Point as ShapelyPoint
from django.contrib.gis.geos import GEOSGeometry

# Convertir GeoJSON Mapbox en polygones Shapely
polygon_depart = shape(isochrone_depart['features'][0]['geometry'])
polygon_arrivee = shape(isochrone_arrivee['features'][0]['geometry'])

# Query trajets avec points DANS les isochrones
from core.models import Trajet
from django.db.models import Q

trajets_candidats = Trajet.objects.filter(
    Q(point_depart__coords_latitude__range=(polygon_depart.bounds[1], polygon_depart.bounds[3])) &
    Q(point_depart__coords_longitude__range=(polygon_depart.bounds[0], polygon_depart.bounds[2])) &
    Q(point_arrivee__coords_latitude__range=(polygon_arrivee.bounds[1], polygon_arrivee.bounds[3])) &
    Q(point_arrivee__coords_longitude__range=(polygon_arrivee.bounds[0], polygon_arrivee.bounds[2]))
)

# Filtrer contexte similaire (heure ± flexibility)
if heure:
    heures_acceptees = ['matin', 'apres-midi', 'soir'] if heure != 'nuit' else ['nuit']
    trajets_candidats = trajets_candidats.filter(heure__in=heures_acceptees)

if meteo is not None:
    meteo_min = max(0, meteo - 1)
    meteo_max = min(3, meteo + 1)
    trajets_candidats = trajets_candidats.filter(meteo__gte=meteo_min, meteo__lte=meteo_max)

# Vérifier si points VRAIMENT dans polygones (test précis)
trajets_similaires = []
for trajet in trajets_candidats:
    pt_depart = ShapelyPoint(trajet.point_depart.coords_longitude, trajet.point_depart.coords_latitude)
    pt_arrivee = ShapelyPoint(trajet.point_arrivee.coords_longitude, trajet.point_arrivee.coords_latitude)
    
    if polygon_depart.contains(pt_depart) and polygon_arrivee.contains(pt_arrivee):
        trajets_similaires.append(trajet)
```

**Étape 3 : Calcul distances réelles (Matrix API)**

Utiliser `mapbox_client.get_matrix()` pour calculer distances exactes :

```python
# Coords départ demandé + coords départs BD
sources_depart = [depart_coords] + [(t.point_depart.coords_latitude, t.point_depart.coords_longitude) for t in trajets_similaires]
# Coords arrivée demandée + coords arrivées BD
sources_arrivee = [arrivee_coords] + [(t.point_arrivee.coords_latitude, t.point_arrivee.coords_longitude) for t in trajets_similaires]

# Matrix API : distances entre point demandé et points BD
matrix_depart = mapbox_client.get_matrix(
    coordinates=sources_depart,
    sources=[0],  # Seulement le point demandé
    destinations=list(range(1, len(sources_depart)))  # Tous les points BD
)

matrix_arrivee = mapbox_client.get_matrix(
    coordinates=sources_arrivee,
    sources=[0],
    destinations=list(range(1, len(sources_arrivee)))
)

# Calculer distance_extra pour chaque trajet
for i, trajet in enumerate(trajets_similaires):
    dist_depart_extra = matrix_depart['distances'][0][i]  # mètres
    dist_arrivee_extra = matrix_arrivee['distances'][0][i]
    trajet._distance_extra = dist_depart_extra + dist_arrivee_extra  # Total distance extra
```

**Étape 4 : Ajustements prix**

Calculer les ajustements selon distance extra et congestion :

```python
from django.conf import settings

# Prix moyens trajets similaires
prix_base = sum(t.prix for t in trajets_similaires) / len(trajets_similaires)

# Ajustement distance (settings.ADJUSTMENT_PRIX_PAR_KM = 50.0 CFA/km par défaut)
distance_extra_km = sum(t._distance_extra for t in trajets_similaires) / len(trajets_similaires) / 1000
ajustement_distance_cfa = distance_extra_km * settings.ADJUSTMENT_PRIX_PAR_KM

# Ajustement congestion (si user fournit congestion_user différente de BD)
if congestion_user:
    congestion_bd_moyenne = sum(t.congestion_moyen or 50 for t in trajets_similaires) / len(trajets_similaires)
    delta_congestion = congestion_user * 10 - congestion_bd_moyenne  # user scale 1-10, BD scale 0-100
    ajustement_congestion_pourcent = int(delta_congestion * settings.ADJUSTMENT_CONGESTION_POURCENT / 100)
else:
    ajustement_congestion_pourcent = 0

# Calcul prix final ajusté
facteur_ajustement = 1.0 + (ajustement_congestion_pourcent / 100)
prix_ajuste = (prix_base + ajustement_distance_cfa) * facteur_ajustement

prix_min = min(t.prix for t in trajets_similaires)
prix_max = max(t.prix for t in trajets_similaires)

return {
    'statut': 'similaire',
    'prix_moyen': round(prix_ajuste, 2),
    'prix_min': prix_min,
    'prix_max': prix_max,
    'fiabilite': 0.75,  # Fiabilité moyenne pour match similaire
    'message': f"Estimation ajustée depuis {len(trajets_similaires)} trajets similaires (+{ajustement_distance_cfa:.0f} CFA pour distance extra de {distance_extra_km*1000:.0f}m).",
    'nb_trajets_utilises': len(trajets_similaires),
    'details_trajet': {
        'depart': {
            'label': 'Proche ' + trajets_similaires[0].point_depart.label,
            'coords': list(depart_coords),
            'quartier': trajets_similaires[0].point_depart.quartier,
            'ville': trajets_similaires[0].point_depart.ville
        },
        'arrivee': {
            'label': 'Proche ' + trajets_similaires[0].point_arrivee.label,
            'coords': list(arrivee_coords),
            'quartier': trajets_similaires[0].point_arrivee.quartier,
            'ville': trajets_similaires[0].point_arrivee.ville
        },
        'distance_estimee': distance_mapbox,
        'heure': heure,
        'meteo': meteo,
        'type_zone': type_zone
    },
    'ajustements_appliques': {
        'distance_extra_metres': int(distance_extra_km * 1000),
        'ajustement_distance_cfa': round(ajustement_distance_cfa, 2),
        'ajustement_congestion_pourcent': ajustement_congestion_pourcent,
        'facteur_ajustement_total': round(facteur_ajustement, 2),
        # ... ajouter meteo_opposee et heure_opposee (voir check_exact_match)
    },
    'suggestions': [
        'Trajets similaires trouvés dans le quartier',
        'Prix ajusté pour distance légèrement différente',
        'Ajoutez votre prix réel après le trajet pour améliorer les estimations'
    ]
}
```

#### Constants settings à utiliser

```python
from django.conf import settings

settings.MAPBOX_ISOCHRONE_MINUTES  # 10 (défaut)
settings.ADJUSTMENT_PRIX_PAR_KM  # 50.0 CFA/km
settings.ADJUSTMENT_CONGESTION_POURCENT  # 10 (10% par tranche 10 pts congestion)
settings.SIMILARITY_HEURE_FLEXIBILITY  # True (accepter matin/apres-midi/soir si heure=matin)
settings.SIMILARITY_METEO_TOLERANCE  # 1 (accepter meteo ±1)
```

#### Tests recommandés

```python
# Test 1 : Trajet similaire à 500m du départ (même quartier)
depart_coords = (3.8547, 11.5021)  # Polytechnique
arrivee_coords = (3.8667, 11.5174)  # Ekounou

# Ajouter trajet BD à 500m : (3.8550, 11.5025) -> (3.8670, 11.5180)
# check_similar_match() devrait trouver ce trajet et ajuster prix

# Test 2 : Aucun trajet similaire dans rayon 10 min
depart_coords = (3.5000, 11.0000)  # Zone rurale inconnue
# check_similar_match() devrait retourner None
```

---

### Fonction 2 : `fallback_inconnu()`

**Objectif** : Générer plusieurs estimations de prix quand aucun trajet exact/similaire n'existe en BD.

**Localisation** : `core/views.py`, lignes ~260-285

**Signature actuelle** :
```python
def fallback_inconnu(depart_coords, arrivee_coords, distance_mapbox, heure, meteo, type_zone, quartier_depart):
    """
    Génère des estimations pour trajet totalement inconnu (aucun historique).
    
    Méthodes multiples :
    1. DISTANCE_BASED : Prix = distance_mapbox * prix_au_km_moyen_BD
    2. ZONE_BASED : Moyenne prix trajets dans même arrondissement/ville
    3. STANDARDISE : Tarif officiel Cameroun (300 CFA jour, 350 CFA nuit)
    4. ML_PREDICTION : Appeler predict_prix_ml() avec features (voir ci-dessous)
    
    Retourner moyenne pondérée des 4 méthodes.
    
    Args:
        depart_coords (tuple): (lat, lon) départ
        arrivee_coords (tuple): (lat, lon) arrivée
        distance_mapbox (float): Distance routière (mètres)
        heure (str|None): Tranche horaire
        meteo (int|None): Code météo 0-3
        type_zone (int|None): Type zone 0-2
        quartier_depart (str|None): Quartier départ (extrait via Nominatim)
    
    Returns:
        dict: Structure INCONNU avec estimations multiples
        {
            'statut': 'inconnu',
            'prix_moyen': float,  # Moyenne pondérée
            'prix_min': None,
            'prix_max': None,
            'fiabilite': 0.50,
            'message': str,
            'nb_trajets_utilises': 0,
            'estimations_supplementaires': {
                'distance_based': float,
                'standardise': float,
                'zone_based': float,
                'ml_prediction': float
            },
            'details_estimations': {
                'distance_based': str,  # Description méthode
                'standardise': str,
                'zone_based': str,
                'ml_prediction': str
            },
            ...
        }
    """
    pass
```

#### Algorithme recommandé

**Méthode 1 : DISTANCE_BASED**

Calculer prix selon distance routière :

```python
from core.models import Trajet
from django.db.models import Avg

# Calculer prix/km moyen sur toute la BD
stats = Trajet.objects.filter(distance__gt=0).aggregate(
    avg_prix_par_km=Avg('prix') / Avg('distance') * 1000  # CFA/km
)
prix_au_km_moyen = stats['avg_prix_par_km'] or settings.PRIX_PAR_KM_DEFAULT  # 50 CFA/km par défaut

distance_km = distance_mapbox / 1000
prix_distance_based = distance_km * prix_au_km_moyen

description_distance = f"Basé sur distance routière ({distance_km:.1f} km) et prix/km moyen BD ({prix_au_km_moyen:.0f} CFA/km)"
```

**Méthode 2 : ZONE_BASED**

Moyenne prix trajets dans même zone géographique :

```python
# Si quartier connu, filtrer par quartier
if quartier_depart:
    trajets_zone = Trajet.objects.filter(
        Q(point_depart__quartier=quartier_depart) | Q(point_arrivee__quartier=quartier_depart)
    )
    zone_label = f"quartier {quartier_depart}"
else:
    # Sinon, filtrer par ville (reverse-geocode arrivee_coords)
    ville = _get_quartier_from_coords(arrivee_coords).get('ville', 'Yaoundé')
    trajets_zone = Trajet.objects.filter(
        Q(point_depart__ville=ville) | Q(point_arrivee__ville=ville)
    )
    zone_label = f"ville {ville}"

if trajets_zone.exists():
    prix_zone_based = trajets_zone.aggregate(Avg('prix'))['prix__avg']
    description_zone = f"Moyenne prix trajets dans {zone_label} ({trajets_zone.count()} trajets)"
else:
    prix_zone_based = settings.PRIX_STANDARD_JOUR_CFA  # Fallback standardisé
    description_zone = f"Aucun trajet trouvé dans {zone_label}, utilise tarif standard"
```

**Méthode 3 : STANDARDISE**

Tarif officiel Cameroun :

```python
from django.conf import settings

# Tarif selon heure (jour vs nuit)
if heure in ['matin', 'apres-midi', 'soir'] or heure is None:
    prix_standardise = settings.PRIX_STANDARD_JOUR_CFA  # 300
    description_standard = f"Tarif officiel Cameroun jour ({prix_standardise} CFA)"
else:
    prix_standardise = settings.PRIX_STANDARD_NUIT_CFA  # 350
    description_standard = f"Tarif officiel Cameroun nuit ({prix_standardise} CFA)"
```

**Méthode 4 : ML_PREDICTION**

Appeler `predict_prix_ml()` (voir fonction 3) :

```python
prix_ml_prediction = predict_prix_ml(
    distance=distance_mapbox,
    heure=heure,
    meteo=meteo,
    type_zone=type_zone,
    congestion_moyen=50.0,  # Valeur par défaut si inconnue
    sinuosite=1.0,  # Route droite par défaut
    nb_virages=0
)

description_ml = f"Prédiction modèle Machine Learning (R²={settings.ML_MODEL_R2_SCORE or 0.78})"
```

**Moyenne pondérée finale**

```python
# Pondération recommandée (ajustable selon tests)
poids = {
    'distance_based': 0.3,
    'zone_based': 0.25,
    'standardise': 0.15,
    'ml_prediction': 0.3
}

prix_moyen = (
    prix_distance_based * poids['distance_based'] +
    prix_zone_based * poids['zone_based'] +
    prix_standardise * poids['standardise'] +
    prix_ml_prediction * poids['ml_prediction']
)

return {
    'statut': 'inconnu',
    'prix_moyen': round(prix_moyen, 2),
    'prix_min': None,
    'prix_max': None,
    'fiabilite': 0.50,
    'message': 'Trajet inconnu. Estimation basée sur plusieurs méthodes approximatives.',
    'nb_trajets_utilises': 0,
    'estimations_supplementaires': {
        'distance_based': round(prix_distance_based, 2),
        'standardise': prix_standardise,
        'zone_based': round(prix_zone_based, 2),
        'ml_prediction': round(prix_ml_prediction, 2)
    },
    'details_estimations': {
        'distance_based': description_distance,
        'standardise': description_standard,
        'zone_based': description_zone,
        'ml_prediction': description_ml
    },
    'details_trajet': {
        'depart': {
            'label': 'Point inconnu',
            'coords': list(depart_coords),
            'quartier': quartier_depart,
            'ville': _get_quartier_from_coords(depart_coords).get('ville')
        },
        'arrivee': {
            'label': 'Destination inconnue',
            'coords': list(arrivee_coords),
            'quartier': None,
            'ville': _get_quartier_from_coords(arrivee_coords).get('ville')
        },
        'distance_estimee': distance_mapbox,
        'heure': heure,
        'meteo': meteo,
        'type_zone': type_zone
    },
    'suggestions': [
        '⚠️ Fiabilité faible : aucun trajet similaire en base de données',
        'Négociez prudemment et ajoutez votre prix après le trajet',
        'Plus de trajets ajoutés = estimations plus précises pour tous'
    ]
}
```

#### Constants settings à utiliser

```python
settings.PRIX_PAR_KM_DEFAULT  # 50.0 CFA/km
settings.PRIX_STANDARD_JOUR_CFA  # 300
settings.PRIX_STANDARD_NUIT_CFA  # 350
settings.ML_MODEL_R2_SCORE  # 0.78 (à update après training)
```

---

### Fonction 3 : `predict_prix_ml()`

**Objectif** : Prédiction via modèle ML de **CLASSIFICATION MULTICLASSE** (pas régression !).

**IMPORTANT** : Les prix des taxis au Cameroun ne sont PAS continues mais appartiennent à des **tranches fixes** :

```python
PRIX_CLASSES_CFA = [
    100, 150, 200, 250, 300, 350, 400, 450, 500, 
    600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000
]
# 18 classes au total
# Variation minimale : 50 CFA
```

**Localisation** : `core/views.py`, lignes ~285-310

**Signature actuelle** :
```python
def predict_prix_ml(distance, heure, meteo, type_zone, congestion_moyen, sinuosite, nb_virages):
    """
    Prédiction prix via modèle ML de CLASSIFICATION MULTICLASSE.
    
    ⚠️ IMPORTANT : Ce N'EST PAS une régression ! 
    Les prix taxis Cameroun appartiennent à des tranches fixes (100, 150, 200, 250, ..., 2000 CFA).
    Le modèle doit prédire la CLASSE (tranche de prix) la plus probable.
    
    Features recommandées :
    - distance (float, mètres)
    - heure_encoded (int, 0-3 : matin=0, apres-midi=1, soir=2, nuit=3)
    - meteo (int, 0-3)
    - type_zone (int, 0-2)
    - congestion_moyen (float, 0-100)
    - sinuosite_indice (float, ≥1.0)
    - nb_virages (int)
    - feature_interaction : distance * congestion_moyen (pour capturer non-linéarité)
    
    Modèle recommandé :
    - RandomForestClassifier (sklearn) avec 18 classes
    - XGBoost Classifier
    - OU réseau neuronal avec softmax output (18 neurones)
    
    Target encoding :
    - Mapper chaque prix BD (ex: 275 CFA) à la classe la plus proche (250 ou 300)
    - Classes = [100, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000]
    
    Args:
        distance (float): Distance routière (mètres)
        heure (str|None): Tranche horaire
        meteo (int|None): Code météo 0-3
        type_zone (int|None): Type zone 0-2
        congestion_moyen (float): Congestion Mapbox 0-100
        sinuosite (float): Indice sinuosité ≥1.0
        nb_virages (int): Nombre virages
    
    Returns:
        int: Prix prédit (une des 18 classes) en CFA
        
    Exemple :
        >>> predict_prix_ml(5200, 'matin', 1, 0, 45.0, 1.2, 8)
        250  # Classe prédite (pas 247.8 ou autre float !)
    """
    pass
```

#### Algorithme recommandé (Classification Multiclasse)

**Étape 0 : Définir les classes de prix**

```python
# Classes fixes des prix taxis Cameroun (18 classes)
PRIX_CLASSES_CFA = [
    100, 150, 200, 250, 300, 350, 400, 450, 500, 
    600, 700, 800, 900, 1000, 1200, 1500, 1700, 2000
]

def mapper_prix_vers_classe(prix_reel):
    """
    Mapper un prix réel BD (ex: 275 CFA) vers la classe la plus proche.
    
    Args:
        prix_reel (float): Prix exact payé par user
        
    Returns:
        int: Classe de prix la plus proche
        
    Exemple:
        >>> mapper_prix_vers_classe(275)
        300  # Plus proche de 300 que de 250
        >>> mapper_prix_vers_classe(225)
        250  # Plus proche de 250 que de 200
    """
    import numpy as np
    idx = np.argmin([abs(prix_reel - classe) for classe in PRIX_CLASSES_CFA])
    return PRIX_CLASSES_CFA[idx]
```

**Étape 1 : Encodage features**

```python
import numpy as np

# Encodage heure
heure_map = {'matin': 0, 'apres-midi': 1, 'soir': 2, 'nuit': 3}
heure_encoded = heure_map.get(heure, 0) if heure else 0

# Imputation valeurs manquantes
meteo = meteo if meteo is not None else 0
type_zone = type_zone if type_zone is not None else 0
congestion_moyen = congestion_moyen or 50.0
sinuosite = sinuosite or 1.0
nb_virages = nb_virages or 0

# Feature engineering
distance_km = distance / 1000
feature_interaction = distance_km * congestion_moyen  # Non-linéarité

features = np.array([[
    distance_km,
    heure_encoded,
    meteo,
    type_zone,
    congestion_moyen,
    sinuosite,
    nb_virages,
    feature_interaction
]])
```

**Étape 2 : Chargement modèle CLASSIFIER (pas Regressor !)**

```python
import joblib
from django.conf import settings
import os

model_path = os.path.join(settings.BASE_DIR, 'core', 'ml_models', 'prix_classifier.pkl')
scaler_path = os.path.join(settings.BASE_DIR, 'core', 'ml_models', 'scaler.pkl')
classes_path = os.path.join(settings.BASE_DIR, 'core', 'ml_models', 'prix_classes.json')

# Charger modèle + scaler (pré-entraînés via train_ml_model)
try:
    model = joblib.load(model_path)  # RandomForestClassifier ou XGBoost
    scaler = joblib.load(scaler_path)
    
    # Charger liste classes (ordre important pour predict)
    import json
    with open(classes_path, 'r') as f:
        prix_classes = json.load(f)  # [100, 150, 200, ..., 2000]
        
except FileNotFoundError:
    # Fallback si modèle pas encore entraîné
    logger.warning("Modèle ML non entraîné. Retour prix standard.")
    return settings.PRIX_STANDARD_JOUR_CFA  # 300 CFA par défaut
```

**Étape 3 : Prédiction de la CLASSE**

```python
# Normalisation features
features_scaled = scaler.transform(features)

# Prédiction de la classe (index 0-17)
classe_idx = model.predict(features_scaled)[0]

# Mapper index -> prix réel
prix_predit = prix_classes[classe_idx]

# Optionnel : Récupérer probabilités pour toutes les classes
probas = model.predict_proba(features_scaled)[0]
top_3_indices = np.argsort(probas)[-3:][::-1]
top_3_classes = [(prix_classes[i], probas[i]) for i in top_3_indices]

logger.info(f"Prédiction ML : {prix_predit} CFA (confiance {probas[classe_idx]:.2f})")
logger.debug(f"Top 3 classes : {top_3_classes}")

return int(prix_predit)  # Return int, pas float !
```

#### Constants settings à utiliser

```python
settings.ML_MODEL_PATH  # 'core/ml_models/prix_classifier.pkl' (RandomForestClassifier)
settings.ML_SCALER_PATH  # 'core/ml_models/scaler.pkl'
settings.ML_CLASSES_PATH  # 'core/ml_models/prix_classes.json'
settings.PRIX_CLASSES_CFA  # [100, 150, 200, ..., 2000]  (18 classes)
```

#### Structure modèle attendue

Le modèle doit être entraîné via `train_ml_model()` (voir fonction 4) et sauvegarder :

```python
# Exemple structure fichiers ML
core/
  ml_models/
    prix_classifier.pkl  # RandomForestClassifier ou XGBoostClassifier (18 classes)
    scaler.pkl  # StandardScaler
    prix_classes.json  # [100, 150, 200, 250, ..., 2000]
    feature_names.json  # ['distance_km', 'heure_encoded', ...]
    metrics.json  # {"accuracy": 0.82, "f1_score": 0.79, "tolerance_1_classe": 0.91}
```

#### Métriques de performance (Classification)

Pour évaluer le modèle classifier (pas R²/RMSE car pas régression !) :

```python
from sklearn.metrics import accuracy_score, f1_score, classification_report, confusion_matrix

# Métriques classification
accuracy = accuracy_score(y_test_classes, y_pred_classes)
f1_macro = f1_score(y_test_classes, y_pred_classes, average='macro')
f1_weighted = f1_score(y_test_classes, y_pred_classes, average='weighted')

# Tolérance ±1 classe (ex: prédit 300 au lieu de 250 = acceptable)
tolerance_1 = np.mean(np.abs(y_test_classes - y_pred_classes) <= 1)

print(f"Accuracy : {accuracy:.3f}")
print(f"F1-score (macro) : {f1_macro:.3f}")
print(f"F1-score (weighted) : {f1_weighted:.3f}")
print(f"Tolérance ±1 classe : {tolerance_1:.3f}")

# Rapport détaillé par classe
print(classification_report(y_test_classes, y_pred_classes, target_names=[str(p) for p in PRIX_CLASSES_CFA]))
```

---

### Fonction 4 : `train_ml_model()` (Celery task)

**Objectif** : Entraîner le modèle ML sur la base de données complète (tâche asynchrone).

**Localisation** : `core/tasks.py`, lignes ~25-50

**Signature actuelle** :
```python
from celery import shared_task

@shared_task
def train_ml_model():
    """
    Tâche Celery pour entraîner le modèle ML.
    
    Pipeline :
    1. Charger tous les trajets BD (Point + Trajet) avec features
    2. Feature engineering : encodage heure, imputation NaN, interaction terms
    3. Split train/test (80/20)
    4. Entraînement RandomForest/XGBoost
    5. Évaluation : R², RMSE, MAE
    6. Sauvegarde modèle + scaler + metrics
    7. Logging résultats
    
    Déclenché via :
    - Commande Django : `python manage.py train_model`
    - Celery Beat : Schedule quotidien (minuit) pour ré-entraînement
    - API endpoint : POST /api/train/ (admin uniquement)
    
    Returns:
        dict: Metrics du modèle entraîné
    """
    pass
```

#### Algorithme recommandé

**Étape 1 : Chargement données**

```python
from core.models import Trajet
import pandas as pd
import numpy as np

# Query tous trajets avec features complètes
trajets = Trajet.objects.select_related('point_depart', 'point_arrivee').filter(
    distance__isnull=False,
    prix__gt=0
)

if trajets.count() < 50:
    # Pas assez de données pour entraîner
    return {'error': 'Pas assez de trajets (minimum 50 requis)', 'count': trajets.count()}

# Conversion en DataFrame
data = []
for trajet in trajets:
    data.append({
        'distance_km': trajet.distance / 1000 if trajet.distance else 0,
        'heure': trajet.heure or 'matin',
        'meteo': trajet.meteo if trajet.meteo is not None else 0,
        'type_zone': trajet.type_zone if trajet.type_zone is not None else 0,
        'congestion_moyen': trajet.congestion_moyen or 50.0,
        'sinuosite_indice': trajet.sinuosite_indice or 1.0,
        'nb_virages': trajet.nb_virages or 0,
        'prix': trajet.prix
    })

df = pd.DataFrame(data)
```

**Étape 2 : Feature engineering**

```python
# Encodage heure
heure_map = {'matin': 0, 'apres-midi': 1, 'soir': 2, 'nuit': 3}
df['heure_encoded'] = df['heure'].map(heure_map).fillna(0).astype(int)

# Feature interaction
df['distance_congestion'] = df['distance_km'] * df['congestion_moyen']

# Features finales
feature_cols = [
    'distance_km', 'heure_encoded', 'meteo', 'type_zone',
    'congestion_moyen', 'sinuosite_indice', 'nb_virages',
    'distance_congestion'
]
X = df[feature_cols].values
y = df['prix'].values
```

**Étape 3 : Split train/test**

```python
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)
```

**Étape 4 : Normalisation + Entraînement**

```python
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
# OU from xgboost import XGBRegressor

# Normalisation
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Entraînement modèle
model = RandomForestRegressor(
    n_estimators=100,
    max_depth=10,
    min_samples_split=5,
    random_state=42,
    n_jobs=-1
)
model.fit(X_train_scaled, y_train)
```

**Étape 5 : Évaluation**

```python
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

y_pred = model.predict(X_test_scaled)

metrics = {
    'r2_score': r2_score(y_test, y_pred),
    'rmse': np.sqrt(mean_squared_error(y_test, y_pred)),
    'mae': mean_absolute_error(y_test, y_pred),
    'n_train': len(X_train),
    'n_test': len(X_test)
}
```

**Étape 6 : Sauvegarde**

```python
import joblib
import json
from django.conf import settings
import os

# Créer dossier ml_models si inexistant
model_dir = os.path.join(settings.BASE_DIR, 'core', 'ml_models')
os.makedirs(model_dir, exist_ok=True)

# Sauvegarder modèle + scaler
joblib.dump(model, os.path.join(model_dir, 'prix_model.pkl'))
joblib.dump(scaler, os.path.join(model_dir, 'scaler.pkl'))

# Sauvegarder feature names
with open(os.path.join(model_dir, 'feature_names.json'), 'w') as f:
    json.dump(feature_cols, f)

# Sauvegarder metrics
with open(os.path.join(model_dir, 'metrics.json'), 'w') as f:
    json.dump(metrics, f, indent=2)
```

**Étape 7 : Logging**

```python
import logging

logger = logging.getLogger(__name__)
logger.info(f"Modèle ML entraîné avec succès : R²={metrics['r2_score']:.3f}, RMSE={metrics['rmse']:.2f} CFA")

return metrics
```

#### Déclenchement automatique

**Option 1 : Commande Django**

```python
# core/management/commands/train_model.py
from django.core.management.base import BaseCommand
from core.tasks import train_ml_model

class Command(BaseCommand):
    help = "Entraîne le modèle ML de prédiction de prix"
    
    def handle(self, *args, **options):
        self.stdout.write("Entraînement du modèle ML...")
        metrics = train_ml_model()
        self.stdout.write(self.style.SUCCESS(f"✅ Modèle entraîné : R²={metrics['r2_score']:.3f}"))
```

```bash
python manage.py train_model
```

**Option 2 : Celery Beat (ré-entraînement quotidien)**

```python
# fare_calculator/celery.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    'train-model-daily': {
        'task': 'core.tasks.train_ml_model',
        'schedule': crontab(hour=0, minute=0),  # Minuit chaque jour
    }
}
```

**Option 3 : API endpoint (admin uniquement)**

```python
# core/views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from core.tasks import train_ml_model

@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_training(request):
    """Endpoint pour déclencher entraînement ML (admins uniquement)"""
    task = train_ml_model.delay()  # Async via Celery
    return Response({
        'message': 'Entraînement ML démarré',
        'task_id': task.id
    })
```

#### Constants settings à utiliser

```python
settings.ML_MIN_TRAJETS_TRAINING  # 50 (minimum trajets requis)
settings.ML_TEST_SIZE  # 0.2 (20% test)
settings.ML_MODEL_TYPE  # 'RandomForest' ou 'XGBoost'
```

---

## Dépendances ML à installer

Ajouter dans `requirements.txt` :

```txt
scikit-learn==1.5.2
xgboost==2.1.3  # Optionnel, si vous préférez XGBoost à RandomForest
joblib==1.4.2
pandas==2.2.3
numpy==2.1.3
shapely==2.0.6  # Pour isochrones (check_similar_match)
```

Installation :

```bash
pip install scikit-learn xgboost joblib pandas numpy shapely
```

---

## Tests et validation

### Tests unitaires recommandés

```python
# core/tests.py
from django.test import TestCase
from core.views import predict_prix_ml, check_similar_match, fallback_inconnu
from core.tasks import train_ml_model
from core.models import Trajet, Point

class MLFunctionsTestCase(TestCase):
    def setUp(self):
        # Créer 100 trajets de test
        for i in range(100):
            depart = Point.objects.create(
                coords_latitude=3.85 + i*0.001,
                coords_longitude=11.50 + i*0.001,
                label=f"Point {i}",
                quartier="Test"
            )
            arrivee = Point.objects.create(
                coords_latitude=3.86 + i*0.001,
                coords_longitude=11.51 + i*0.001,
                label=f"Point {i+100}"
            )
            Trajet.objects.create(
                point_depart=depart,
                point_arrivee=arrivee,
                distance=5000 + i*100,
                prix=250 + i*2,
                heure='matin',
                meteo=0
            )
    
    def test_train_ml_model(self):
        """Test entraînement modèle ML"""
        metrics = train_ml_model()
        self.assertIn('r2_score', metrics)
        self.assertGreater(metrics['r2_score'], 0.5)  # R² > 0.5 minimum
    
    def test_predict_prix_ml(self):
        """Test prédiction ML"""
        # Entraîner d'abord
        train_ml_model()
        
        prix = predict_prix_ml(
            distance=5000,
            heure='matin',
            meteo=0,
            type_zone=0,
            congestion_moyen=50.0,
            sinuosite=1.5,
            nb_virages=5
        )
        self.assertGreater(prix, 0)
        self.assertLess(prix, 2000)  # Prix réaliste
    
    def test_check_similar_match(self):
        """Test recherche trajets similaires"""
        result = check_similar_match(
            depart_coords=(3.855, 11.505),
            arrivee_coords=(3.865, 11.515),
            heure='matin',
            meteo=0,
            type_zone=0,
            congestion_user=None,
            distance_mapbox=5500
        )
        # Devrait trouver trajets similaires dans setUp()
        if result:
            self.assertEqual(result['statut'], 'similaire')
            self.assertIn('ajustements_appliques', result)
    
    def test_fallback_inconnu(self):
        """Test fallback trajet inconnu"""
        result = fallback_inconnu(
            depart_coords=(3.5, 11.0),  # Zone inconnue
            arrivee_coords=(3.6, 11.1),
            distance_mapbox=12000,
            heure='matin',
            meteo=1,
            type_zone=0,
            quartier_depart=None
        )
        self.assertEqual(result['statut'], 'inconnu')
        self.assertIn('estimations_supplementaires', result)
        self.assertEqual(len(result['estimations_supplementaires']), 4)
```

Lancer les tests :

```bash
python manage.py test core.tests.MLFunctionsTestCase
```

---

## Monitoring et amélioration continue

### Métriques à tracker

1. **Taux de match** :
   - % trajets avec match EXACT
   - % trajets avec match SIMILAIRE
   - % trajets INCONNU (cible : <20%)

2. **Qualité prédictions ML** :
   - R² score (cible : >0.75)
   - RMSE (cible : <50 CFA)
   - MAE (cible : <35 CFA)

3. **Feedback utilisateurs** :
   - Écart prix réel vs estimé (après ajout trajet)
   - Nb trajets ajoutés par quartier (détecter zones sous-couvertes)

### Amélioration modèle

**Ré-entraînement automatique** :
- Schedule Celery Beat : chaque nuit à minuit
- Trigger manuel : `python manage.py train_model`
- Condition : Si +50 nouveaux trajets depuis dernier training

**Feature engineering avancé** :
- Distance à CBD (Central Business District)
- Prix historiques quartier départ/arrivée
- Features temporelles : jour semaine, vacances scolaires
- Weather API plus granulaire : température, humidité, vent

**Modèles alternatifs** :
- XGBoost (meilleure performance que RandomForest généralement)
- LightGBM (plus rapide, même performance)
- Réseau neuronal simple (TensorFlow/Keras) pour non-linéarités complexes

---

## Récapitulatif des tâches ML

| Fonction | Priorité | Complexité | Temps estimé | Dépendances |
|----------|----------|------------|--------------|-------------|
| `check_similar_match()` | 🔴 Haute | ⭐⭐⭐ Moyenne | 4-6h | Mapbox Isochrone/Matrix, Shapely |
| `fallback_inconnu()` | 🔴 Haute | ⭐⭐ Facile | 2-3h | `predict_prix_ml()` |
| `predict_prix_ml()` | 🟡 Moyenne | ⭐⭐⭐ Moyenne | 3-4h | Modèle entraîné |
| `train_ml_model()` | 🟡 Moyenne | ⭐⭐⭐⭐ Difficile | 5-8h | Scikit-learn, Pandas |

**Ordre recommandé d'implémentation** :
1. `train_ml_model()` d'abord (pour avoir un modèle dispo)
2. `predict_prix_ml()` ensuite (test prédictions)
3. `fallback_inconnu()` (utilise `predict_prix_ml()`)
4. `check_similar_match()` en dernier (plus complexe, Isochrone/Matrix)

**Temps total estimé** : 15-20h pour équipe ML expérimentée

---

## Variables d'environnement ML

Ajouter dans `.env` :

```bash
# ML Model Configuration
ML_MODEL_TYPE=RandomForest  # Options: RandomForest, XGBoost
ML_MIN_TRAJETS_TRAINING=50
ML_TEST_SIZE=0.2
ML_PRIX_MIN_CFA=50
ML_PRIX_MAX_CFA=2000
ML_MODEL_R2_SCORE=0.78  # À update après training
```

---

**Dernière mise à jour** : 5 novembre 2025  
**Version API** : 2.0.0  
**Section ML** : Ajoutée le 5 novembre 2025
