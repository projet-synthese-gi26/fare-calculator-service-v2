# Guide de Migration SQLite vers PostgreSQL

Ce guide détaille les étapes pour migrer la base de données de Fare Calculator de SQLite (développement) vers PostgreSQL (production), tout en préservant toutes les données existantes (utilisateurs, trajets, points, etc.).

## 1. Préparation des données (Dump SQLite)

Avant de changer la configuration de base de données, nous devons exporter les données actuelles de SQLite.

### Étape 1.1 : Arrêter le serveur

```bash
# Arrêter le serveur Django s'il tourne
CTRL+C
```

### Étape 1.2 : Exporter les données (Dump)

Utilisez cette commande pour créer un fichier JSON contenant toutes vos données. Nous excluons `contenttypes` et `auth.permission` car ils seront régénérés par PostgreSQL.

```bash
# Windows (PowerShell)
python manage.py dumpdata --exclude auth.permission --exclude contenttypes > db_dump.json

# Linux/Mac
python3 manage.py dumpdata --exclude auth.permission --exclude contenttypes > db_dump.json
```

Vérifiez que le fichier `db_dump.json` a bien été créé et qu'il n'est pas vide.

## 2. Configuration PostgreSQL (Docker)

Nous allons ajouter un conteneur PostgreSQL à notre stack Docker.

### Étape 2.1 : Modifier `docker-compose.yml`

Assurez-vous que votre fichier `docker-compose.yml` contient le service `db` :

```yaml
version: "3.8"

services:
  db:
    image: postgres:15
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=fare_calculator
      - POSTGRES_USER=fox
      - POSTGRES_PASSWORD=secure_password_123
    ports:
      - "5432:5432"

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  # ... autres services (web, worker, beat) ...

volumes:
  postgres_data:
```

### Étape 2.2 : Lancer PostgreSQL

```bash
docker-compose up -d db
```

Vérifiez que le conteneur tourne : `docker-compose ps`

## 3. Configuration Django (`settings.py`)

Nous devons dire à Django d'utiliser PostgreSQL au lieu de SQLite.

### Étape 3.1 : Installer le pilote PostgreSQL

Si ce n'est pas déjà fait :

```bash
pip install psycopg2-binary
```

(Ceci est déjà inclus dans `requirements.txt`)

### Étape 3.2 : Mettre à jour `settings.py`

Modifiez la section `DATABASES` :

```python
import os

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'fare_calculator'),
        'USER': os.environ.get('POSTGRES_USER', 'fox'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'secure_password_123'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),  # 'db' dans Docker
        'PORT': '5432',
    }
}
```

## 4. Migration et Import des données

Maintenant que PostgreSQL est vide, nous allons recréer le schéma et importer les données.

### Étape 4.1 : Appliquer les migrations

Cela crée les tables vides dans PostgreSQL.

```bash
python manage.py migrate
```

### Étape 4.2 : Charger les données (Load)

Nous importons les données depuis notre fichier `db_dump.json`.

```bash
python manage.py loaddata db_dump.json
```

Si tout se passe bien, vous verrez un message indiquant le nombre d'objets installés.

## 5. Vérification

Lancez le serveur et vérifiez que vos données sont là.

```bash
python manage.py runserver
```

1. Connectez-vous à l'admin Django : `http://localhost:8000/admin`
2. Vérifiez que les `Trajets` et `Utilisateurs` sont présents.
3. Testez l'API `/api/stats/`.

## 6. Nettoyage

Une fois la migration validée, vous pouvez (si vous le souhaitez) supprimer ou archiver le fichier `db.sqlite3`.

---

**Note pour le déploiement** : En production (sur serveur VPS/Docker), assurez-vous que les variables d'environnement (`POSTGRES_HOST`, `POSTGRES_PASSWORD`, etc.) sont correctement définies dans votre fichier `.env` ou votre configuration Docker.
