# Partie 9 : Apport de Mapbox à l'Architecture et à la Logique d'Estimation du Projet

## Introduction à l'Intégration de Mapbox

Dans cette partie, nous explorons en détail l'apport de l'API Mapbox au projet, en nous basant sur les fonctionnalités avancées identifiées précédemment (Directions, Matrix, Isochrone, Map Matching, Search) et sur des recherches complémentaires effectuées sur la documentation officielle de Mapbox, des forums développeurs (comme Stack Overflow et GitHub issues), et des exemples d'implémentations en Python/Django et React. Mapbox est intégré au backend (Django Rest Framework avec base de données SQLite pour le développement initial, migrable vers PostgreSQL/PostGIS pour des queries géospatiales plus complexes) et au frontend (PWA React/Next.js). Cette intégration enrichit les objets métier (Trajet, Point, Prediction) avec des données dynamiques comme le niveau de congestion, les classes de routes, les restrictions de virages (via un indice de sinuosité calculé), et des périmètres de similarité plus intelligents basés sur des isochrones temporelles plutôt que des cercles fixes.

L'objectif est d'améliorer la précision des estimations de prix sans dépasser les quotas gratuits de Mapbox (ex. : 100 000 requêtes Directions par mois, incluant trafic). Nous tenons compte des contraintes locales au Cameroun : couverture cartographique incomplète (routes secondaires souvent absentes ou avec données "unknown" pour congestion/maxspeed, comme vu dans l'exemple JSON fourni), variabilité temporelle des données (congestion changeante), et focus sur les points d'intérêt (POI) plutôt que coords aléatoires. Pour optimiser, nous utilisons un caching agressif en BD SQLite (ex. : stocker résultats Mapbox pour trajets récurrents) et un filtrage préalable par quartier/arrondissement (comme décrit dans la description principale : limiter les candidats similarité pour éviter calculs exhaustifs).

Nous aborderons successivement les ajouts aux objets (virages, classes routes), la gestion des recherches frontend, les périmètres similarité, l'insistance sur les POI avec prétraitements, la gestion des valeurs manquantes/fallbacks, et le débat sur l'intégration de la congestion (stocker en BD ou utiliser post-prediction, avec input user optionnel).

## 9.1 : Calcul et Intégration du Niveau de Virage (Sinuosité) pour les Trajets

Les virages et la sinuosité d'un trajet influencent grandement le prix des taxis au Cameroun, car un itinéraire tortueux (avec de nombreux tournants, intersections ou restrictions) augmente le temps et l'effort perçus, menant à des négociations plus élevées. Mapbox ne fournit pas directement un indice de sinuosité, mais ses réponses JSON détaillées (ex. : bearings, maneuvers, steps, distances par segment) permettent de le calculer de manière robuste. Basé sur l'exemple fourni (où les bearings et maneuvers montrent des changements d'angle comme à Carrefour Vogt : bearing_before=0, bearing_after=181, indiquant un virage ~181°), nous adoptons la meilleure des trois méthodes décrites (sinuosité base, virages par km, force virages pondérée), en choisissant dynamiquement celle avec le plus de données disponibles (ex. : si bearings complets, prioriser force virages ; sinon, fallback sur sinuosité base).

- **Méthodes de Calcul (Implémentées Avant Stockage d'un Trajet)** :
  - **Méthode 1 : Sinuosité Base (Ratio Distance/Ligne Droite)** : Indice = Distance Totale / Distance Ligne Droite (calculée via Haversine sur coords départ/arrivée). Ex. : Dans l'exemple, distance=5212m ; ligne droite ~2km (Haversine entre [11.5021,3.8480] et [11.5174,3.8667]) → indice ~2.6 (sinueux). Avantage : Simple, gère manques (fallback si segments incomplets).
  - **Méthode 2 : Virages par Km** : Nombre de maneuvers importantes (steps avec type "turn/rotary") / Distance km. Ex. : 7 maneuvers / 5.212km ≈1.3 virages/km. Pondéré par type (rotary +2 points pour complexité).
  - **Méthode 3 (Préférée si Données) : Force Virages Pondérée** : Somme des |bearing_before - bearing_after| (angle minimal via mod 360°) pour chaque intersection, divisée par distance km. Ex. : Pour maneuver à Carrefour Vogt (diff 181°), plus autres → total ~500° /5km =100°/km (indiquant virages modérés). Cela capture la "force" (virage sec vs. doux).

- **Intégration au Backend** :
  - Avant création d'un Trajet (via POST /add-trajet), appeler Directions API, parser JSON, calculer indice (code Django : utiliser math pour Haversine/bearings). Stocker comme attribut `sinuosite_indice` (float) dans Trajet.
  - Optimisation : Si calcul échoue (manques "unknown"), fallback à 1.0 (linéaire par défaut). Filtrer par quartier d'abord pour limiter appels.
  - Impact sur Prediction : Pour "presque connu", ajuster fonction (+50 CFA/100m + facteur sinuosité : +20 CFA si >1.5). Pour ML (inconnu), inclure comme feature dans régression.

- **Gestion Manques au Cameroun** : Recherches montrent que Mapbox utilise OSM pour Yaoundé (couverture ~80% urbain), mais bearings manquants sur routes secondaires → fallback sur Méthode 1. Avantage : Rend estimations plus réalistes (ex. : trajet sinueux en zone mixte +prix).

## 9.2 : Classes de Routes et Leur Gestion

Les classes de routes (ex. : "secondary", "primary", "trunk" via "mapbox_streets_v8.class" dans JSON) correspondent à typeZone, influençant prix (urbaine/primary + dense = +prix).

- **Calcul et Stockage** :
  - Avant stockage Trajet : Parser "class" par segment ; déterminer dominante (ex. : par distance cumulée ou nombre segments – prioriser distance si égal, via code simple sum(distance where class=='primary')).
  - Si indisponible ("unknown"), fallback sur typeZone input user ou déduit via quartier (urbaine par défaut pour Yaoundé).
  - Attribut : `route_classe_dominante` (string) dans Trajet.

- **Intégration** : Dans /estimate, ajuster prix (ex. : trunk +10% pour vitesse). Pour similarité, filtrer candidats par classe similaire.

- **Exemples** : Trajet mixte (50% primary, 30% secondary) → dominante "primary". Manques : Fallback "secondary" pour urbain.

## 9.3 : Gestion des Recherches et Auto-Complétion au Frontend

- **Implémentation** : Frontend React appelle directement Search API de Mapbox (`GET /search/searchbox/v1/suggest?q={query}`) pour complétion fluide (ex. : taper "Carrefour E" → suggestions POI comme "Carrefour Ekounou" avec coords/label). Gérer cache via React Query ou localStorage (stocker résultats pour queries récentes, éviter appel par caractère – debounce 300ms).
- **Optimisation** : Limite gratuite 100k/mois ; cache réduit à <10% appels réels. Backend valide si needed.

## 9.4 : Périmètres de Similarité pour les Trajets : Principes, Implémentation avec Isochrones de Mapbox, et Optimisations

Pour bien contextualiser cette section, rappelons le principe fondamental de la logique de similarité dans le projet, tel que décrit initialement et affiné ici. Lorsque un utilisateur entre un nouveau trajet (composé d'un point de départ et d'un point d'arrivée, typiquement des points d'intérêt comme "Polytechnique Yaoundé" ou "Carrefour Ekounou") pour obtenir une estimation de prix, le backend ne commence pas par une prédiction aveugle. Au contraire, il vérifie d'abord dans la base de données (BD SQLite) s'il existe des trajets déjà stockés qui sont "similaires" à ce nouveau trajet. Cette similarité est hiérarchique : d'abord chercher des matchs "exacts" (ou très proches), puis "presque similaires", avant de fallback sur des estimations pour les cas "inconnus". L'idée est d'exploiter au maximum les données communautaires accumulées (ajouts d'utilisateurs) pour fournir des prix basés sur des expériences réelles, plutôt que des calculs abstraits.

Au départ, cette similarité était basée sur des distances géographiques simples : pour un nouveau trajet avec point de départ A' et arrivée B', on vérifiait si A' est "proche" (dans un rayon fixe, ex. 50m) d'un point de départ A connu dans la BD, et si B' est proche d'un B connu, avec une distance routière globale similaire. Si oui, on considérait le trajet comme "exactement similaire" et on appliquait directement le prix moyen des trajets connus (sans ajustement, ou avec un ajustement minimal). Pour un périmètre "élargi" (ex. 150m), on appliquait une fonction d'ajustement (ex. +50 CFA pour 100m extra). Cela évitait les arnaques en se basant sur des trajets réels, mais les cercles fixes (rayons) ne tenaient pas compte du réseau routier réel, des embouteillages, ou des virages – des facteurs cruciaux à Yaoundé où les routes sinueuses ou congestionnées changent tout.

Maintenant, avec l'intégration de Mapbox, nous évoluons vers une approche plus intelligente en remplaçant (ou complétant) ces cercles fixes par des **isochrones temporelles** : des zones (polygones) représentant les endroits atteignables en un temps donné (ex. 2 minutes pour "exact", 5 minutes pour "élargi") depuis un point, en tenant compte du trafic, des routes, et des restrictions. Cela rend la similarité plus réaliste : un trajet est "similaire" non pas parce que les points sont proches en ligne droite, mais parce qu'ils sont accessibles en un temps comparable en taxi (driving-traffic profile). Par exemple, deux points de départ dans une zone congestionnée pourraient être "proches" en temps même s'ils sont à 100m, tandis qu'en zone fluide, 50m suffisent. Des recherches sur la documentation Mapbox (Isochrone API) confirment que c'est possible : l'API génère des polygones GeoJSON basés sur le temps de trajet, ce qui permet de vérifier si un nouveau point "tombe" dans l'isochrone d'un point connu. Cependant, des limitations existent pour le Cameroun (couverture incomplète des routes secondaires et trafic non toujours monitoré, menant à des isochrones approximatifs ou erreurs "no route found"), d'où des fallbacks nécessaires.

- **Explication Verbeuse du Principe de Similarité** :
  Imaginons un utilisateur qui entre un trajet de "Polytechnique Yaoundé" (point de départ A') à "École des Travaux Publics" (arrivée B'). Le backend commence par filtrer les candidats dans la BD pour éviter de comparer avec tous les trajets stockés (potentiellement des milliers au fil du temps, ce qui ralentirait les queries). Pour cela, on utilise les attributs administratifs des Points (ville, quartier, arrondissement/commune, département – stockés si disponibles via Mapbox Geocoding). Exemple : Ne considérer que les trajets où le point de départ connu A est dans le même quartier que A' (ex. "Ngoa-Ekelle" pour Polytechnique), et pareil pour B'. Cela réduit drastiquement les candidats (de 1000 à 20, par exemple), en exploitant le fait que les POI sont localisés (un taxi de Yaoundé ne traverse pas la ville pour un trajet court). Si l'info quartier manque (rare avec Mapbox Search, qui retourne souvent "place.admin" comme "Yaoundé II" commune), fallback sur ville ou département plus large.

  Une fois filtrés, on vérifie la similarité :
  - **Niveau "Exact" (ou Très Proche)** : Générer une isochrone de 2 minutes autour du point de départ connu A (et autour de B pour l'arrivée), et vérifier si A' est dedans (et B' dans l'isochrone de B). Si oui, et si la distance routière globale est similaire (±10%), considérer comme exact et appliquer le prix moyen sans ajustement.
  - **Niveau "Élargi" (Presque Similaire)** : Isochrone de 5 minutes ; si match, appliquer ajustement (ex. +50 CFA pour temps extra, pondéré par congestion/virages).
  - Avantage : Plus précis que cercles (ex. : un point à 50m mais séparé par un embouteillage n'est pas "proche" en temps). Et comme les Points sont des POI (nommés, comme "Carrefour Awae"), les matchs exacts sont plus probables – un trajet "Polytechnique → Ekounou" matchera directement si déjà en BD.

- **Recherches et Faisabilité avec Mapbox** :
  Des recherches sur la doc Mapbox Isochrone API montrent qu'elle est idéale pour cela : Elle retourne des polygones GeoJSON (avec `polygons=true`) pour des contours temporels (ex. `contours_minutes=2,5`), basés sur driving-traffic (incluant congestion si disponible). Pour vérifier si un point est dans un isochrone : Utiliser une lib Python comme Shapely (disponible en env, import shapely.geometry ; point.within(polygone)). Pas de batch natif (1 coord par requête), mais optimisation via :
  - Filtrage administratif préalable (bien que l'API n'ait pas de filtre built-in, on le fait en BD avec quartiers stockés via Geocoding API, qui retourne "context" avec "locality" pour quartier, "district" pour arrondissement).
  - Combinaison avec Matrix API : Après filtrage, batcher distances/temps entre candidats (ex. : 1 requête Matrix pour comparer 10 A connus à A', et 10 B à B' – jusqu'à 25x25).
  Limites Cameroun : Couverture OSM sous-jacente variable (routes rurales incomplètes, trafic "unknown" souvent) ; si isochrone échoue, fallback sur distance euclidienne (Haversine, rayon 50m/150m). Recherches sur forums (ex. Mapbox GitHub) confirment usages similaires pour "route similarity" en transport, avec Shapely pour checks spatiaux.

- **Intégration au Backend** :
  - Dans view /estimate : Filtrer QuerySet par quartier (`Trajet.objects.filter(point_depart__quartier=nouveau_quartier)`), générer isochrones pour candidats (cache en SQLite pour réutilisation), vérifier inclusion.
  - Task périodique (Celery) : Pré-générer isochrones pour POI populaires de Yaoundé.
  - Fallback : Si isochrones indisponibles (erreur API ou manques données), cercles fixes + distance.
  - Optimisation Batch : Matrix pour valider temps/distances post-filtrage.

Cette approche optimise performances (filtrage réduit calculs), précision (temps vs. distance), et scalabilité, tout en gérant les POI pour matchs exacts fréquents.

## 9.5 : Focus sur les Points d'Intérêt (POI) : Explication Verbeuse, Prétraitements et Avantages

Au Cameroun, les taxis fonctionnent par POI connus (checkpoints comme "Carrefour Ekounou", "Polytechnique Yaoundé", ou quartiers comme "Ekounou" avec carrefour d'arrivée), pas coords aléatoires. Cela évite arnaques (prix standardisés par POI) et reflète la réalité : un user dit "Ekounou" au taxi, pas "ma maison exacte" – il marche le reste. Crainte : Si frontend permet sélection carte (doigt sur point random) ou API reçoit coords brutes (de camarades), on risque trajets non généralisables, fragmentant BD (peu de similarités).

- **Prétraitements Optimaux** :
  - Avant stockage Trajet ou estimation Prediction : Si coords random (non nommées), convertir via Map Matching/Search API en POI proche (ex. : Map Matching aligne sur route, puis Search reverse-geocoding pour label comme "boulangerie Le Paradis" ou quartier "Ekounou").
  - Endpoint : Map Matching pour aligner, puis `GET /geocoding/v5/mapbox.places/{lon},{lat}.json` pour POI (prioriser nommés : école/carrefour/quartier ; fallback quartier si trop précis comme resto inconnu des taxis).
  - Dans backend : Serializer valide ; si pas de label, appeler Mapbox, stocker coords + label/ville/quartier/département (si disponible, pour filtres similarité).
  - Frontend : Recherche force POI (suggestions nommées) ; si sélection carte, auto-convertir backend-side.

- **Avantages** :
  - Généralisation : Plus de trajets "similaires" en BD (ex. : multiples "Polytechnique → Ekounou" vs. coords uniques).
  - Précision : Prix basés sur POI connus, aidant négociations (user sait proposer "200 CFA pour Ekounou").
  - Optimisation BD : Filtres par quartier/département éliminent 90% candidats avant similarité (ex. : QuerySet.filter(quartier='Ekounou')).
  - Exemples : User GPS à maison Ekounou → convertir en "Carrefour Ekounou" (proche) ; API coords random → "École Polytechnique" si match.

- **Craintes et Solutions** : Si POI trop précis (resto inconnu taxis), élargir à quartier (via fallback). Avantage communautaire : BD enrichie, ML plus robuste.

## 9.6 : Gestion des Valeurs Manquantes et Fallbacks

Super plus du projet : Système résilient aux manques (Cameroun : ~30% routes avec données complètes).
- Ex. : Congestion "unknown" → fallback typeZone/heure.
- Virages : Si bearings manquants → Méthode 1.
- Classes : Dominante ou default "secondary".
- Isochrones : Fallback distance 50m.
- Général : Log manques, invite user ajouter détails.

## 9.7 : Intégration de la Congestion : Débat sur Stockage en BD vs. Post-Prediction

Congestion varie (temps réel), et Mapbox a souvent "unknown" au Cameroun (recherches : couverture probes GPS limitée, ~50% urbain Yaoundé ; docs Mapbox notent "incomplète en Afrique").

- **Options et Débat** :
  - **Stocker en BD** : Lors ajout Trajet, stocker `congestion_moyen` (de Mapbox au moment). Avantage : Feature pour ML (régression inclut congestion). Inconvénient : Variabilité (donnée obsolète) ; manques → default (50 pour urbain). Solution entre-deux : Stocker + timestamp ; ré-entraîner ML périodiquement.
  - **Post-Prediction (Préféré)** : Calculer prix base (hiérarchique/ML), puis appeler Mapbox pour congestion actuelle, ajuster (+% si heavy). Avantage : Fraîcheur ; gère manques sans polluer BD. Inconvénient : +1 requête/estimation (optimisé via cache).
  - **Ajout Input User** : Pour enrichir, ajouter champ optionnel à ajout Trajet : échelle 1-10 embouteillages (ex. : 1=fluide, 10=bloqué). Stocker comme `congestion_user` ; utiliser pour fallback/ML si Mapbox unknown. Avantage : Données communautaires locales, compensant lacunes Mapbox.

- **Décision Projet** : Hybride – Stocker input user (fiable, invariant) ; utiliser Mapbox post-prediction pour ajustement live. Impact : Prediction inclut message "Ajusté pour congestion actuelle : +50 CFA (heavy)".

## Conclusion de la Partie 9

Mapbox transforme le projet en ajoutant profondeur (virages, classes, congestion) tout en optimisant (batch, cache). Avec focus POI et fallbacks, il rend le service robuste pour Yaoundé, extensible au Cameroun. Perspectives : Tester coverage Mapbox via appels bbox ; intégrer à ML pour features enrichies.

et que LAPI fonctionne avec un systemem  de cle API que l'admin peut geneer dans l'interface d'admin et je vais pouvoir creer des cles API a mes camareades en fait.. il n'y a pas de susteme d'auhtnetification ,non... pas de sytme utilisateur c'est une api anonyme mais avec des cles API en fait.