#!/bin/sh
set -e  # Arrêter le script à la moindre erreur

echo "--- Démarrage du script d'initialisation ---"

# Attendre que Postgres soit vraiment prêt (double sécurité)
echo "Attente de la base de données..."
until python -c "import socket; s = socket.socket(); s.connect(('db', 5432))" 2>/dev/null; do
  echo "Postgres n'est pas encore prêt, on attend..."
  sleep 2
done

# Appliquer les migrations
echo "--- Application des migrations ---"
python manage.py migrate --noinput

# Vérifier si on doit initialiser les données
echo "--- Vérification des données existantes ---"
# On utilise une commande python directe pour éviter les hangs du shell interactif
COUNT=$(python manage.py shell -c "from core.models import Point; print(Point.objects.count())" 2>/dev/null || echo "0")

if [ "$COUNT" = "0" ]; then
    echo "--- Base de données vide détectée. Importation des données initiales ---"
    python manage.py loaddata initial_data
else
    echo "--- Base de données déjà initialisée ($COUNT points trouvés) ---"
fi

echo "--- Lancement du serveur Django ---"
exec python manage.py runserver 0.0.0.0:8000
