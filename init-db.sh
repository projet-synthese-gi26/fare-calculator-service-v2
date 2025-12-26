#!/bin/sh

# On attend pas forcément Postgres ici car le healthcheck du docker-compose s'en charge.

echo "--- Démarrage du script d'initialisation ---"

# Appliquer les migrations (toujours safe)
python manage.py migrate --noinput

# Vérifier si on doit initialiser les données
# On regarde s'il y a déjà des points d'intérêt dans la base
COUNT=$(python manage.py shell -c "import django; django.setup(); from core.models import Point; print(Point.objects.count())" 2>/dev/null)

if [ "$COUNT" = "0" ] || [ -z "$COUNT" ]; then
    echo "--- Base de données vide détectée. Importation des données initiales (fixtures) ---"
    python manage.py loaddata initial_data
else
    echo "--- Base de données déjà initialisée ($COUNT points trouvés). Pas d'importation. ---"
fi

echo "--- Lancement du serveur Django ---"
# En prod on pourrait utiliser gunicorn, mais on garde runserver comme dans votre config actuelle
exec python manage.py runserver 0.0.0.0:8000
