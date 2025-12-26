# Projet : Service de Proposition et d'Estimation des Prix de Taxi au Cameroun (Focus Initial sur Yaoundé)

## Introduction Générale au Projet et aux Motivations

Le projet que je développe se concentre sur l'analyse du trafic et de la circulation au Cameroun, avec un accent particulier sur les prix des taxis. Dans un premier temps, l'attention est portée sur la ville de Yaoundé, bien que l'objectif soit d'étendre l'application à l'ensemble du pays. L'objectif principal est de créer un service qui aide les utilisateurs à estimer ou à proposer un prix raisonnable pour un trajet en taxi, en évitant les situations courantes d'arnaque ou de refus de prise en charge dues à un manque de connaissance des tarifs locaux. Cette estimation est qualifiée de "prédiction" entre guillemets, car elle repose davantage sur des données réelles collectées auprès des utilisateurs que sur des modèles prédictifs avancés, même si un aspect prédictif peut émerger avec l'accumulation de données.

Pour expliquer l'origine de ce projet, il est important de noter que je ne souhaite pas taper moi-même tous les détails. Je préfère décrire oralement l'ensemble des éléments – tenants, aboutissants, idées, appréhensions – pour que tu les captures et les organises en un document Markdown exhaustif. Ce document doit décrire le projet de A à Z sans omettre le moindre détail, même en cas de répétitions dans mes explications, car chaque nuance compte. Il inclut mes idées, mes doutes (comme sur l'utilisation du machine learning), les exemples concrets, et tout le contexte. Le résultat doit être très long, détaillé, avec des explications complètes et des exemples à tous les niveaux, pour servir de base à une autre IA qui codera le projet sans perdre aucun aspect du scénario.

Le service est conçu comme un outil technologique backend en priorité, car c'est l'aspect principal requis pour mon devoir. Je suis particulièrement à l'aise avec Python, utilisant des frameworks comme Django ou Flask pour structurer le backend. Je maîtrise également Node.js et JavaScript, ce qui pourrait être une alternative, mais Python reste mon choix préféré en raison de sa force pour les calculs mathématiques et les analyses complexes. Le projet met l'accent sur une estimation des prix de taxi qui n'est pas une prédiction stricte, mais qui incorpore un côté prédictif basé sur des données accumulées.

En termes de structure, ce n'est pas uniquement une "application" au sens traditionnel, mais un service web avec une API comme cœur, complétée par une interface frontend servant de preuve de concept. Je collabore avec d'autres camarades qui développent leurs propres projets, et mon service leur fournit des estimations de prix qu'ils peuvent intégrer. Pour mon évaluation personnelle, je dois inclure une interface qui démontre le fonctionnement du service, et je tiens à ce qu'elle soit non seulement fonctionnelle, mais vraiment magnifique, parfaite et ultra-moderne – même si elle est théoriquement "juste" pour la démo. Je m'en fous des minimas ; je vise l'excellence visuelle et utilisateur.

L'interface est pensée comme un site web responsive, optimisé pour mobile en priorité, car les utilisateurs l'utiliseront naturellement sur leur téléphone au bord de la route, avant ou après un trajet en taxi. Cependant, elle doit aussi être compatible avec les PC pour les présentations et démos. Pour cela, le frontend sera développé comme une Progressive Web App (PWA), ce qui la fera ressembler à une application native sur mobile tout en fonctionnant sur desktop. Les technologies envisagées incluent React ou Next.js pour une interactivité fluide et moderne, avec des éléments comme des cartes interactives pour la sélection de trajets.

Un détail important est que je n'ai pas encore fixé tous les inputs de l'interface – je laisse une liberté créative pour le design – mais l'objectif est d'expliquer d'abord l'utilité globale pour bien contextualiser. Le service aide concrètement en permettant aux utilisateurs d'arriver sur l'interface, de sélectionner un trajet, et d'obtenir une proposition de prix pour ce tronçon. Par exemple, un utilisateur pourrait sélectionner un trajet de un point à un autre sur une carte interactive, similaire à Google Maps, en tapant des zones ou en utilisant sa position actuelle, et l'interface affiche le prix estimé avec une UX impeccable.

## Utilité Détaillée du Service et Fonctionnement de l'Interface

Pour bien comprendre à quoi sert ce service, imaginons un utilisateur typique à Yaoundé. Il arrive sur l'interface et sélectionne un trajet – par exemple, de un point spécifique à un autre. Le service calcule et affiche une estimation du prix du taxi pour ce segment de route. Cela résout un problème courant : à Yaoundé, contrairement aux pays occidentaux comme la France où les taxis ont des tarifs standardisés avec compteurs, tout se négocie au bord de la route. Si tu es dans une zone inconnue, tu risques de proposer un prix trop élevé et de te faire arnaquer, ou trop bas et de rester bloqué sans que personne ne t'informe du tarif raisonnable. Le service fournit donc une proposition basée sur des données réelles, aidant à négocier de manière informée.

Concrètement, l'utilisateur peut sélectionner les points de départ et d'arrivée sur une carte interactive, rechercher des zones en tapant du texte (comme dans Google Maps), ou partir de sa position actuelle pour un endroit choisi. Par exemple, disons qu'il veut aller de "Polytechnique Yaoundé" à "l'École des Travaux Publics". Il sélectionne les zones, et l'interface propose un prix – disons 200 francs CFA – avec une UX fluide et attractive. L'interface est conçue pour être splendide et facile, avec des facilités comme l'auto-détection de la position pour éviter des saisies manuelles.

En plus de l'estimation, l'utilisateur peut ajouter son propre prix après le trajet, enrichissant la base de données. Au départ, le service n'aura pas beaucoup de données – seulement celles que j'ajouterai expérimentalement pour démarrer. C'est donc communautaire : les utilisateurs ajoutent des tronçons pour aider les autres. Par exemple, après un trajet de Polytechnique à l'École des Travaux Publics payé 200 CFA, l'utilisateur peut l'ajouter, même si le trajet existe déjà, pour affiner les estimations. Cela rend le système plus précis au fil du temps.

La fonctionnalité d'ajout est complexe et détaillée : elle tient compte de variables influençant le prix, comme l'heure (très importante, divisée en matin, après-midi, nuit), la météo (pluie ou soleil, avec niveaux comme 0-3), et le type de zone (urbaine, rurale, ou mixte – trois catégories). Quand un utilisateur ajoute un trajet, l'interface facilite la tâche pour ne pas l'ennuyer : sélections rapides, auto-remplissage (heure actuelle, position GPS pour départ/arrivée, météo détectée via API gratuite si possible). Par exemple, un bon samaritain ajoute un trajet de l'École Polytechnique à l'École des Travaux à 200 CFA à 11h sous pluie ; un autre ajoute le même à 300 CFA à 18h sans pluie, montrant l'influence de l'heure. Ces détails permettent au système de proposer des estimations nuancées.

Les facilités sont essentielles car les utilisateurs le font volontairement, sans paiement : pas de formulaires longs, mais des options comme "C'est depuis ma position" ou recherche simple pour points. Si la météo n'est pas renseignée, le système peut l'auto-détecter ou assigner une valeur (0 pour soleil, 1 pour pluie légère, etc.). Cela rend l'ajout super simple et encourage la participation.

## Logique d'Estimation et de Prédiction des Prix

Le cœur du système est la logique d'estimation du prix, qui fonctionne de manière hiérarchique selon la disponibilité des données. Tout commence par une vérification si le trajet et les variables (heure, météo, zone) correspondent exactement à quelque chose dans la base. Par exemple, pour un trajet de l'École Polytechnique à l'École des Travaux le matin sous pluie, si des entrées existent, le système fournit directement la moyenne des prix, accompagnée du minimum et du maximum pour donner une plage (ex. : moyenne 250 CFA, min 200, max 300). Pas de calcul compliqué – juste une recherche et une agrégation simple.

Si le trajet n'est pas exact, on passe au mode similarité. La similarité est calculée en vérifiant si les points de départ et d'arrivée sont dans des périmètres circulaires restreints (ex. : un petit rayon autour du départ connu et de l'arrivée connue), et si la distance routière est à peu près la même. Par exemple, si un utilisateur veut aller de un point A' proche de Polytechnique à un point B' proche de l'École des Travaux, avec distance similaire, le système considère cela comme similaire et applique le prix du trajet connu. Si dans un premier périmètre étroit, prix identique ; si dans un deuxième périmètre plus large (dépassement léger), ajuster via une fonction (ex. : ajouter 50 CFA pour 100m extra, mais cette fonction sera plus complexe, pas un abus de langage – à étudier pour inclure variables comme heure).

Exemples de similarité :
- Trajet exact : Polytechnique → Travaux, matin, pluie – prix moyen 200 CFA.
- Similaire étroit : Point 50m de Polytechnique → Point 50m de Travaux – même prix.
- Similaire élargi : Point 150m de Polytechnique → Point 200m de Travaux – ajuster +50 CFA pour distance extra.

Le défi est de définir ces périmètres : ils pourraient dépendre de l'heure (plus larges le soir ?), de la météo (pluie rétrécit ?), ou de la zone (rurale plus large que urbaine). C'est l'étude principale, et si du machine learning s'avère utile pour affiner via données accumulées, pas de problème – même si ce n'est pas obligatoire, et l'idéal serait de s'en passer avec des algorithmes simples.

Pour les cas inconnus total (ni exact ni similaire), le système avoue l'incertitude : estimations fausses à 60%, fiables à 50%. Il fournit trois valeurs approximatives dans un JSON, avec un message clair "Inconnu, mais voici des suppositions". L'utilisateur choisit :
- Basée sur distance : Cherche distances similaires dans base, ajuste (ex. : pour 100m nouveau, basé sur connu 100m à 200 CFA ; ajouter 50 CFA si 150m).
- Basée sur standardisé : Tarifs officiels (300 CFA jour, 350 nuit), même si non respectés – c'est le but du système de compenser cela.
- Basée sur zone : Moyenne des prix dans un périmètre zonal (ex. : moyenne 250 CFA dans zone urbaine proche).

Exemples d'inconnu :
- Nouveau trajet 100m en journée : Distance-based 200 CFA (basé sur connu) ; Standardisé 300 CFA ; Zone-based 250 CFA.
- Incertain, avec invite : "Si vous prenez ce taxi, ajoutez le prix payé pour aider les prochains."

## Appréhensions, Défis et Aspects Techniques Avancés

Parmi mes appréhensions, le machine learning n'est pas obligatoire – c'est juste une possibilité si needed pour utiliser les données users et affiner périmètres ou fonctions d'ajustement. Si on peut s'en passer avec des algorithmes simples, tant mieux, c'est l'idéal. Mais si ça arrive, pas de souci ; il faudrait réfléchir à une stratégie pour exploiter les ajouts (ex. : régression sur heure/météo). Pour les distances et cartes, pas d'outils payants – pas d'argent. On cherche alternatives gratuites comme OpenStreetMap avec Nominatim (geocoding), OpenRouteService (routing), Leaflet (cartes JS). Si besoin, auto-hébergement pour contrôle total.

Le frontend est là pour prouver le service, mais doit être splendide – exemples : Carte interactive pour sélection (taper "Polytechnique", cliquer position, voir estimation instantanée). Simplifications users : Auto-heure, GPS pour points, météo détectée.

Le document doit inclure tout cela en phrases complètes, avec exemples à tous niveaux, pour une longueur substantielle – comme ici, où je reformule tout en détail sans copier mot pour mot, mais en gardant l'essence.

## Recherches sur Alternatives Gratuites pour Cartographie

J'ai recherché des alternatives à Google Maps – voici les détails, avec exemples d'intégration.

- OpenStreetMap avec Nominatim et ORS : Geocoding gratuit, routing pour distances. Ex. : Calculer distance Polytechnique-Travaux sans payer.
- GraphHopper : Routing open-source, gratuit limité ou auto-hébergé. Ex. : Ajuster pour similarité +100m.
- Geoapify : Tier gratuit pour routing. Ex. : Recherche zones pour sélection trajet.
- OSRM : Routing rapide auto-hébergé. Ex. : Vérifier routes similaires.
- Valhalla : Multimodal, gratuit hébergé soi-même. Ex. : Influence météo sur distance.
- Leaflet/OpenLayers : Cartes frontend. Ex. : Affichage interactif pour users.

Ces outils assurent tout sans coût, avec exemples pour chaque.

## Conclusion et Perspectives Futures

Ce document reformule l'ensemble en phrases complètes, avec explications détaillées, exemples (trajets, variables, cas), et longueur étendue pour couvrir tout. Perspectives : Étendre au Cameroun, tester ML si utile. Si manque, dis.

# NOTES PERSONNELLES :
## NOTES SUR NOTRE SYSTEME :
### Les acteurs :
* l'utilisateur 
* API route / Carte
* API Meteo
### Les grandes parties du systeme :
* La gestion des entrees utilisateurs : Localisation , Carte , Lieux , Meteo , heure
* La gestion des Estimation (sorties du systeme) : Distances , Fonction Culturelle , Standards, APPRENTISSAGE.
### QUE DOIT PERMETTRE LE SYSTEME ?:
* L'UTILISATEUR DOIT POUVOIR AJOUTER AVEC PLUS OU MOINS DE PRESCISION UN TRAJET QU'IL A FAIT ET SON PRIX.
* L'UTILISATEUR SOIT POUVOIR OBTENIR UNE ESTIMATION DU PRIX DU TAXI POUR UN TRAJET QU'IL RENSEIGNE.
* L'UTILISATEUR DOIT POUVOIR RENSEIGNER SON TRAJET DEPUIS SA POSITION ACTUELLE JUSQU'A  UNE DESTINATION RECHERCHEE OU SELECTIONNEE SUR LA CARTE.
* LE SYSTEME DOIT POUVOIR DETERMINER UN CERTAIN NIVEAU DE SIMILARITE ENTRE LES TRAJETS
* LE SYSTEME DOIT POUVOIR DETERMINER L'HEURE , LA METEO ET LE TYPE DE ZONE DANS LAQUELLE L'UTILISATEUR VEUT EFFECTUER SON TRAJET OU DANS LAQUELLE IL AJOUTE SON TRAJET (CAR CES DONNEES PEUVENT INFLUENCER LE PRIX) 
* LE SYSTEME DOIT PERMETTRE DE PROPOSER UN PRIX POUR DES CARACTERISTIQUES QUE L'UTILISATEUR PEUT ENTRER LUI MEME OU QU'IL PEUT DETECTER AUTOMATIQUEMENT (HEURE , TYPE DE ZONE , METEO)
* LE SYSTEME DOIT POUVOIR UTILISER UNE FONCTION D'AJUSTEMENT DE COUT POUR LES TRAJETS "SIMILAIRES MAIS PAS TROP".
* LE SYSTEME DOIT PRENDRE EN CONSIDERATION LES PRIX STANDARDISES DU TAXI AU CAMEROUN POUR LS TRAJETS TOTALEMENT INCONNUS.
* LE SYSTEME DOIT APPRENDRE DES TRAJETS RENSEIGNES (HEURE , DISTANCE , TYPE DE ZONE (0,1,2) , METEO (0,1,2) , SI POSSIBLE NIVEAU D'EMBOUTEILLAGE ) ET SE SERVIR DE CET APPRENTISSAGE (PROBALEMENT PAR RENFORCEMENT) POUR ESTIMER DES PRIX  DES TRAJETS TOTALEMENT INCONNUS. (donc en plus de donner un prix standard (base sur l'heure) , un prix base sur la distance moyenne , on donne un prix base sur l'apprentissage automatique et l'utilisateur a donc 3 valeurs de predictions pour les trajets totalement inconnu similaires a rien) du systeme) ... (modele de regression (prix precis ) ? de classification ? (classes de prix) on verra bien)
-

# Note importante !! 
Au cameroun , le taxi se prends en réalité par points d'intérêts et non simplement par points aléatoires , cet a dire que ici au cameroun , quand on prends un taxi c’est pour une destination connue qui est en fait un checkpoint de la ville , ce n’est pas d’un point A à un point B aléatoire. par exemple les trajet c’est vraiment d’un lieu “connu par les cartes et les habitants a un autre” , par exemple : “Carrefour Ekounou - Carrefour Awae” , ou encore “AUberge bleue - Château Ngoa Ekele” , ce sont en fait des lieux bien connu tout comme on peut le prendre d’un quartier A , vers un quartier B  mais dans ce cas le quarrir de destination a un carrefour auquel on laisse le client.

par exemple , quand je suis à polytech et que je veux rentrer chez moi (ma maison est à EKOUNOU) je ne prends pas le taxi commun en disant “laisse moi chez moi” mais je dis “Ekounou” et il me laisse au carrefour  EKOUNOU et je fais moi même le chemin de Ekounou jusqu’a chez moi en fait! : Le taxi fonctionne par points d'intérêts. c’est un peu comme le bus commun sauf que les arrêts de bus sont les différents points d'intérets de la vile (il y an as des centaines ).

c’est pourquoi  j’ai du laisser tomber l’idee de depart qui etait de faire une fonctionnalité de selection de trajet ou l’utilisateur selectionne sur la carte interractive directement son point de départ et son point d'arrivée (ou juste son point d'arrivée si son départ est sa position actuelle) et puis on lui propose un prix NON !! il ne faut pas faire comme ca car en fait rien ne dit que le point d'arrivée qu’il va choisir est un point d'intérêt ! 
c’est puruqoi on a plutot opte pour des champs de recherches style google map avec completion fluide , il entre dans un champ le nom du point d'arrivée (et vu que les carte ne connaissent que les points d'intérêts c’est parfait) quand il entre un point et le sélectionne dans la suggestion , un marqueur apparaît sur la carte comme dans google map et puis ca dessine l'itinéraire depuis son point de départ jusqu'au point en question ! il peut effectivement modifier , en recherchant un autre point , soit dans le champ du point d'arrivée ou dans le champ optionnel du point de départ , et puis il valide et obtiens son estimation du prix du taxi !!!

pareil pour l’API que nous allons fournir en fait , quand on va nous envoyer des coordonnes , grace a ces coordonnées du point de depart et du point d'arrivée on saura grace a ces coordonnées le sous quartier (breff la plus petite zone) ou même le point d'intérêt (le plus proche) ou se situe ces points et envoyer les estimations! bien sûr on préférées pour l’API prendre des quartier ou des sous quartiers pour etre plus large parce que les points d’interets comme des restaurants et tout c’est un peu trop precis et ce sera un peu pareil que la selection de points aléatoire sur la carte , surtout que tous les chauffeurs ne connaissent pas tous les restos de la ville , même si il y a des points d'intérêts connus de tous en fait !! mais ça va dépendre de si on a précisément ce point d’interet dans la BD dans la BD sinon on prend surtout la zone.

donc tout cela pour dire que les Coordonnes qu’on aura meme seront des coordonees de zone ou de points d'intérêt en général car ce sont ces points que l'utilisateur va rechercher et non mettre des coordonnées exactes. sauf pour son point de départ mais rien ne nous empêche de prendre le point d'intérêt que représente son point de départ en fait.

premier diagramme objet du projet (il est amene a evoluer avec tous les avantages que mapbox confere): 
```PlantUml
classDiagram
    class Point {
        +ID: int
        +Coordonnées: float[2]
        +Label: string
        +Ville: string
        +Quartier: string
    }
    
    class Trajet {
        +ID: int
        +Heure: string
        +Meteo: int
        +TypeZone: int
        +Distance: float
        +Prix: float
        +DateAjout: datetime
    }
    
    class Prediction {
        +TrajetConcerne: Trajet-like
        +Statut: string
        +PrixMoyen: float
        +PrixMin: float
        +PrixMax: float
        +EstimationsSupplementaires: float[3]
        +Message: string
        +Fiabilite: float (optionnel)
    }
    
    Trajet "1" *-- "2" Point : Composition (Départ/Arrivée)
    Prediction ..> Trajet : Utilise (non persistante)

```

Diagramme de flux : 
```PlantUml
sequenceDiagram
    participant U as Utilisateur (anonyme)
    participant F as Frontend (PWA)
    participant B as Backend API
    participant D as BD
    participant E as APIs Externes (cartes/météo/geocoding)
    
    U->>F: Recherche point départ (GPS auto, mappé à point d'intérêt proche) et arrivée (auto-complétion points connus)
    F->>E: Geocoding/Auto-complétion (ex. Nominatim pour labels comme "Carrefour Ekounou")
    E-->>F: Suggestions (points d'intérêt)
    U->>F: Sélectionne + Valide (heure auto, météo auto, typeZone déduit si possible)
    F->>B: POST /estimate (envoie labels/coords, heure, meteo, typeZone)
    B->>E: Calcul distance + Déduction typeZone/météo (ex. OpenRouteService + OpenWeatherMap)
    E-->>B: Distance + Infos (typeZone via geocoding si feasible)
    B->>D: Query trajets exacts/similaires (filtre quartier, similarité périmètres)
    alt Connu
        D-->>B: Liste trajets → Calcul moyenne/min/max
    else Presque connu
        D-->>B: Trajets similaires → Ajustement fonction (+50 CFA/100m)
    else Inconnu
        B->>B: Fallbacks (distance-based, standardisé, zone-based via quartier/typeZone)
    end
    B-->>F: Retour Prediction (prix, statut, message)
    F-->>U: Affiche estimation + Invite à ajouter prix après trajet (anonyme)

```

architecture :
```PlantUml
graph TD
    A[Frontend: PWA React/Next.js] -->|"Requêtes HTTP (GET/POST)"| B[Backend: API (Django/Flask/FastAPI)]
    A -->|"Auto-complétion lieux (direct)"| H[APIs Externes: Nominatim pour recherche/suggestions points d'intérêt]
    B -->|"Stockage/Queries"| C[BD: PostgreSQL/PostGIS pour geo si needed]
    B -->|"Calculs distances/météo/typeZone"| D[APIs Externes Gratuites: OpenRouteService, OpenWeatherMap]
    B -->|"ML pour inconnus (régression sur features)"| I[Lib ML: scikit-learn (entraîné sur Trajets)]
    A -->|"Affichage cartes/interactions"| E[Libs JS: Leaflet/React-Leaflet pour maps interactives]
    F[Utilisateur Mobile/PC (anonyme)] --> A
    G[Autres Apps (camarades)] --> B

```
et que LAPI fonctionne avec un systemem  de cle API que l'admin peut geneer dans l'interface d'admin et je vais pouvoir creer des cles API a mes camareades en fait.. il n'y a pas de susteme d'auhtnetification ,non... pas de sytme utilisateur c'est une api anonyme mais avec des cles API en fait.