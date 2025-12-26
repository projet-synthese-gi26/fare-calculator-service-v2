# Guide de Migration SQLite vers PostgreSQL

Ce guide détaille les procédures pour migrer votre base de données :

1.  **En Local (Windows)** : Où vous avez installé PostgreSQL nativement.
2.  **En Production (Docker)** : Où PostgreSQL tourne dans un conteneur.

---

## 1. Préparation des données (Dump SQLite)

À faire **sur votre machine locale** avant toute modification.

1.  **Arrêter le serveur** (`CTRL+C`).
2.  **Exporter les données** existantes vers un fichier JSON :
    ```powershell
    python manage.py dumpdata --exclude auth.permission --exclude contenttypes > db_dump.json
    ```
    _Vérifiez que le fichier `db_dump.json` est créé et contient du texte._

---

## 2. Migration Locale (Windows Native)

Puisque vous avez déjà PostgreSQL installé (hors Docker).

### Étape 2.1 : Créer la Base de Données

Ouvrez **pgAdmin** ou un terminal **psql** (`psql -U postgres`) et exécutez :

```sql
-- Création de l'utilisateur (si pas déjà fait)
CREATE USER fox WITH PASSWORD 'password123';

-- Création de la base de données
CREATE DATABASE fare_calculator OWNER fox;

-- Donner les privilèges
ALTER USER fox CREATEDB;
```

### Étape 2.2 : Configurer les Variables d'Environnement (`.env`)

Ouvrez votre fichier `.env` (`fare_calculator-backend/.env`) et ajoutez ces lignes :

```ini
# --- Configuration PostgreSQL (si ces variables sont là, Django utilise Postgres) ---
POSTGRES_DB=fare_calculator
POSTGRES_USER=fox
POSTGRES_PASSWORD=password123
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### Étape 2.3 : Appliquer la Migration

Dans votre terminal VS Code (PowerShell) :

1.  **Créer les tables** dans la nouvelle base :

    ```powershell
    python manage.py migrate
    ```

2.  **Importer les données** sauvegardées :

    ```powershell
    python manage.py loaddata db_dump.json
    ```

3.  **Lancer le serveur** :
    ```powershell
    python manage.py runserver
    ```

---

## 3. Migration Production (Docker)

Sur le serveur de production, la configuration est gérée automatiquement via `docker-compose.yml`.

### Étape 3.1 : Déploiement

Assurez-vous que les variables d'environnement de production sont définies (dans GitLab CI/CD, Portainer, ou fichier `.env.prod`) :

```ini
POSTGRES_DB=fare_calculator
POSTGRES_USER=fox
POSTGRES_PASSWORD=secure_password_prod_XYZ
POSTGRES_HOST=db  <-- IMPORTANT : 'db' est le nom du service Docker
POSTGRES_PORT=5432
```

### Étape 3.2 : Base de Données Persistante

Le fichier `docker-compose.yml` utilise un volume (`postgres_data`) pour que les données survivent aux redémarrages.

### Étape 3.3 : Import Initial en Prod

Si vous voulez envoyer vos données locales vers la prod :

1. Copiez `db_dump.json` sur le serveur.
2. Exécutez : `docker-compose exec web python manage.py loaddata db_dump.json`

---

## Résumé des Variables d'Environnement

| Variable            | Valeur Local (Windows) | Valeur Prod (Docker) |
| :------------------ | :--------------------- | :------------------- |
| `POSTGRES_DB`       | `fare_calculator`      | `fare_calculator`    |
| `POSTGRES_USER`     | `fox`                  | `fox`                |
| `POSTGRES_PASSWORD` | `password123`          | `(Secure Password)`  |
| `POSTGRES_HOST`     | `localhost`            | `db`                 |
| `POSTGRES_PORT`     | `5432`                 | `5432`               |

Si vous supprimez ces lignes du fichier `.env`, Django reviendra automatiquement sur **SQLite**.
