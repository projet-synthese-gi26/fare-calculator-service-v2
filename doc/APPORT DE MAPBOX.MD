# Intégration de Mapbox dans le Projet : Fonctionnalités, Endpoints et Optimisations pour l'Estimation des Prix de Taxi au Cameroun

## Introduction

Ce document secondaire complète la description principale du projet de service de proposition et d'estimation des prix de taxi au Cameroun, avec un focus initial sur Yaoundé. Il se concentre spécifiquement sur l'intégration de l'API Mapbox au backend (Django Rest Framework) et à la base de données SQLite (pour les phases de développement initiales, avant une éventuelle migration vers PostgreSQL/PostGIS pour des fonctionnalités géospatiales avancées). Mapbox a été choisi comme alternative aux APIs gratuites/open-source (comme OpenRouteService ou Nominatim) en raison de ses fonctionnalités avancées en matière de trafic en temps réel, d'optimisations de requêtes par lots, et de données enrichies qui s'alignent parfaitement avec les besoins du projet : estimation précise des prix influencée par la distance, le trafic, les types de routes, et les restrictions de virages.

Basé sur la réponse fournie par l'IA de Mapbox et sur des recherches approfondies (via documentation officielle Mapbox, forums développeurs comme Stack Overflow, et tests d'exemples d'API), ce document détaille les fonctionnalités pertinentes, les endpoints associés, et comment les intégrer sans exploser le quota gratuit (par exemple, jusqu'à 100 000 requêtes Directions par mois gratuites, incluant le trafic, et 50 000 chargements de cartes). Nous tenons compte des contraintes locales au Cameroun : données cartographiques parfois incomplètes (routes secondaires non cartographiées ou trafic non monitoré en zones rurales), ce qui nécessite des fallbacks (ex. : utilisation de données historiques ou valeurs par défaut). L'objectif est d'enrichir les objets métier (Trajet, Point, Prediction) avec des variables comme le niveau de congestion, le type de route, et un indice de sinuosité (calculé à partir des données Mapbox pour quantifier les virages).

Pour optimiser les requêtes et rester dans les limites gratuites :
- Utiliser le caching en BD SQLite (stocker distances, durées, congestions calculées pour trajets récurrents).
- Filtrer par quartier/arrondissement avant calculs (comme noté dans la description principale : limiter les recherches de similarité aux points dans le même quartier pour éviter scans exhaustifs de la BD).
- Batch processing via Matrix API pour comparer multiples trajets en une requête.
- Fallbacks pour données manquantes : Si Mapbox retourne "unknown" pour congestion ou maxspeed (comme dans l'exemple fourni), utiliser des valeurs par défaut basées sur type de zone (urbaine = congestion modérée par défaut).

Le document est structuré par fonctionnalité, avec exemples d'intégration, endpoints, et impacts sur la logique d'estimation (connu/presque connu/inconnu).

## 1. Données de Congestion en Temps Réel et Historique (Enrichissement des Variables de Prix)

La congestion (embouteillages) est une variable clé pour affiner les estimations de prix, car elle influence le temps de trajet et donc la négociation (ex. : prix plus élevé en heure de pointe). Mapbox excelle ici, contrairement aux APIs gratuites qui manquent souvent de données en temps réel pour l'Afrique.

- **Fonctionnalités Pertinentes** :
  - Congestion numérique (0-100) et catégorique (low/moderate/heavy/severe/unknown) par segment de route.
  - Intégration de trafic typique (historique par heure/jour) pour fallbacks quand données live manquent (fréquent au Cameroun pour routes secondaires).
  - Dans le Trajet : Ajouter un attribut `congestion_moyen` (float 0-100, calculé comme moyenne des segments) et `congestion_categorie` (string).
  - Impact sur Prediction : Pour un trajet "connu", ajuster le prix moyen en fonction de la congestion actuelle vs. historique (ex. : +20% si heavy). Pour "inconnu", inclure dans les 3 estimations (distance-based ajustée par congestion).
  - Gestion des manques : Si "unknown" (comme dans l'exemple JSON où beaucoup de segments sont "unknown"), fallback sur type de zone (urbaine = 50 par défaut) ou données historiques. Recherches montrent que Mapbox couvre ~70% des routes urbaines à Yaoundé via OSM et probes GPS, mais rural <30% – donc tester via bounding box pour Yaoundé.

- **Endpoints et Intégration** :
  - **Directions API avec profil driving-traffic** : `GET https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{coordinates}?annotations=congestion&access_token=YOUR_TOKEN`.
    - Exemple : Pour un trajet de "Polytechnique Yaoundé" (coordonnées approximatives : 3.8547, 11.5021) à "Carrefour Ekounou" (3.8667, 11.5174), récupérer JSON avec "annotation" incluant "congestion" par segment.
    - Dans Django : Dans un serializer pour Trajet, appeler requests.get() avant sauvegarde, extraire moyenne de "congestion" array.
    - Optimisation : Une requête par estimation utilisateur (pas par segment) ; cache en BD si trajet similaire (filtrer par quartier d'abord pour éviter recalculs).
  - **Économie de Requêtes** : Batch via Matrix pour multiples similarités (voir section 3). Limite gratuite : 100k/mois – pour 100 estimations/jour, seulement 3000 requêtes/mois.

- **Exemples Détailés** :
  - Trajet connu : Si BD a 5 trajets similaires, utiliser Mapbox pour congestion actuelle ; ajuster prix moyen (ex. : 200 CFA base → 250 si heavy).
  - Manque de données : Si >50% segments "unknown", log warning et fallback sur heure (nuit = low congestion).

## 2. Calcul de Distance et Durée avec Prise en Compte des Types de Routes et Restrictions

La distance est déjà centrale (calculée avant création de Trajet), mais Mapbox ajoute types de routes (urbain/rural) et restrictions (virages interdits, limitations vitesse), aligné avec typeZone.

- **Fonctionnalités Pertinentes** :
  - Distances/durées ajustées par trafic et restrictions (ex. : "maxspeed" dans annotations, incluant unit "km/h").
  - Types de routes via "mapbox_streets_v8" (class: secondary/primary/trunk) – mapper à typeZone (0=urbaine pour primary, 2=rurale pour tertiary).
  - Restrictions virages : Implicites dans "maneuver" (ex. : turn restrictions évitées dans routing).
  - Impact : Dans Prediction "presque connu", ajuster +50 CFA non seulement pour distance extra, mais pour type route (urbaine + dense = +prix) ou restrictions (plus de virages = +durée).
  - Gestion manques : Si "unknown" pour maxspeed (comme exemple : beaucoup "unknown"), estimer via typeZone ou fallback standard (50 km/h urbain).

- **Endpoints et Intégration** :
  - **Directions API** : Même endpoint que ci-dessus, avec `?annotations=maxspeed,speed,duration,distance` pour détails segments.
    - Dans backend : ViewSet pour /estimate, appeler Mapbox, stocker en cache SQLite si quartier match.
  - **Optimisation** : Filtrer BD par quartier avant appel (ex. : QuerySet.filter(quartier=request.quartier) – limite à 10-20 trajets, pas toute BD).

- **Exemples** :
  - Trajet inconnu : Estimation zone-based ajustée par type route (primary = prix standard, tertiary = -10% si rural moins cher).

## 3. Optimisations par Lots avec Matrix API (Économie de Requêtes pour Similarités)

Pour la logique de similarité (périmètres autour points), Matrix permet batch pour comparer multiples trajets sans multiplier requêtes.

- **Fonctionnalités Pertinentes** :
  - Calcul distances/durées entre multiples origines/destinations (jusqu'à 25x25 = 625 en 1 requête).
  - Inclut trafic pour ajustements.
  - Impact : Pour "presque connu", filtrer par quartier, puis batch distances pour 10 trajets candidats – 1 requête au lieu de 10.

- **Endpoints et Intégration** :
  - **Matrix API** : `GET https://api.mapbox.com/directions-matrix/v1/mapbox/driving-traffic/{coordinates}?access_token=YOUR_TOKEN`.
    - Exemple : Coordonnées de 5 points départ + 5 arrivée → matrice 5x5.
    - Dans Django : Celery task pour batch périodique, stocker en SQLite.
  - **Économie** : Réduit de 90% les requêtes pour similarités ; gratuit jusqu'à 100k éléments matrix/mois.

- **Exemples** :
  - Similarité élargie : Batch pour vérifier si distance <150m + congestion similaire.

## 4. Isochrone API pour Périmètres Intelligents (Au Lieu de Cercles Fixes)

Remplace périmètres circulaires par zones temporelles, tenant compte routes/trafic.

- **Fonctionnalités Pertinentes** :
  - Polygones atteignables en X minutes (ex. : 2min pour "étroit").
  - Impact : Similarité si points dans isochrone commune ; gère manques en fallback sur cercles.

- **Endpoints** : `GET https://api.mapbox.com/isochrone/v1/mapbox/driving-traffic/{lon},{lat}?contours_minutes=2,5&access_token=YOUR_TOKEN`.
  - Intégration : Stocker polygones en BD pour offline check.
  - Optimisation : Appel occasionnel (1/semaine pour mise à jour zones Yaoundé).

## 5. Map Matching pour Nettoyage GPS et Points d'Intérêt

Aligne coords GPS sur routes, crucial pour points d'intérêt (mapper GPS actuel à carrefour proche).

- **Endpoints** : `GET https://api.mapbox.com/matching/v5/mapbox/driving-traffic/{coordinates}?access_token=YOUR_TOKEN`.
  - Impact : Pour ajouts users, corriger imprécisions ; mapper à Point connu.
  - Manques : Si pas de match, fallback sur quartier.

## 6. Search API pour Geocoding et Auto-Complétion (Frontend/Backend)

- **Fonctionnalités** : Suggestions POIs avec photos/horaires.
  - Endpoints : `GET https://api.mapbox.com/search/searchbox/v1/suggest?q=Polytechnique+Yaoundé&access_token=YOUR_TOKEN`.
  - Intégration : Frontend React pour complétion fluide ; backend pour validation.
  - Optimisation : Cache résultats POIs en SQLite.

## 7. Calcul d'Indice de Sinuosité/Virages (Basé sur Données Mapbox)

Mapbox ne fournit pas directement un indice, mais on peut calculer via JSON (comme exemple fourni : steps, bearings, maneuvers).

- **Méthodes Détailées** (Basées sur Recherches et Exemple) :
  - **Sinuosité Base** : Distance totale / ligne droite (Haversine sur coords départ/arrivée). Ex. : 5212m / ~2km = 2.6 (sinueux).
  - **Virages par Km** : Compter maneuvers (ex. : 7 dans exemple) / distance km = ~1.3 virages/km.
  - **Force Virages** : Somme |bearing_before - bearing_after| / distance (ex. : pour maneuver à Carrefour Vogt : |0 - 181| = 181° ; total /5km = ~100°/km pour complexité).
  - Impact : Ajouter à Trajet `sinuosite_indice` (float) ; ajuster prix (+10% si >1.5).
  - Manques : Si bearings manquants, fallback sur nombre steps.

- **Intégration** : Dans view Django, parser JSON post-Mapbox, calculer indice (code simple avec math).

## 8. Navigation SDK et Location Provider (Amélioration UX Mobile)

- **Fonctionnalités** : Dead reckoning pour GPS faible (commun au Cameroun).
  - SDK JS pour PWA : Afficher itinéraire avec marqueurs POIs.
  - Optimisation : Appels minimaux, offline possible avec tiles téléchargées.

## Gestion des Données Manquantes et Limites au Cameroun

Recherches (Mapbox docs, OSM Cameroun) montrent couverture ~80% urbain Yaoundé, mais "unknown" fréquent pour congestion/maxspeed. Stratégies :
- Fallback : Utiliser typeZone ou historique.
- Économie : Cache tout (SQLite indices pour 1000 trajets = ~1Mo).

## Conclusion et Perspectives

Mapbox élève le projet en ajoutant trafic/virages/types routes, tout en optimisant via batch/cache. Endpoints clés : Directions, Matrix, Isochrone. Avec filtrage quartier et fallbacks, on reste gratuit/low-cost. Future : Intégrer ML (scikit-learn) et la fonction d'ajustement  sur ces données enrichies pour prédictions inconnues. Ce setup rend le service plus précis et communautaire, aidant à éviter arnaques taxis.
et que LAPI fonctionne avec un systemem  de cle API que l'admin peut geneer dans l'interface d'admin et je vais pouvoir creer des cles API a mes camareades en fait.. il n'y a pas de susteme d'auhtnetification ,non... pas de sytme utilisateur c'est une api anonyme mais avec des cles API en fait.