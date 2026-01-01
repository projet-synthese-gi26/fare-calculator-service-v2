#!/bin/sh
set -e

echo "=== Démarrage du script d'initialisation ==="

# Vérifier si PostgreSQL est configuré
if [ -n "$POSTGRES_DB" ] && [ -n "$POSTGRES_HOST" ]; then
    echo "PostgreSQL configuré: $POSTGRES_HOST:${POSTGRES_PORT:-5432}"
    
    # Attendre que Postgres soit prêt
    echo "Attente de la base de données..."
    MAX_RETRIES=30
    RETRY_COUNT=0
    until python -c "import socket; s = socket.socket(); s.connect(('$POSTGRES_HOST', ${POSTGRES_PORT:-5432}))" 2>/dev/null; do
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
            echo "ERREUR: Impossible de se connecter à PostgreSQL après $MAX_RETRIES tentatives"
            exit 1
        fi
        echo "Postgres n'est pas encore prêt, tentative $RETRY_COUNT/$MAX_RETRIES..."
        sleep 2
    done
    echo "PostgreSQL est prêt!"
else
    echo "SQLite configuré (pas de POSTGRES_DB défini)"
fi

# Collecter les fichiers statiques
echo "=== Collecte des fichiers statiques ==="
python manage.py collectstatic --noinput || true

# Appliquer les migrations
echo "=== Application des migrations ==="
python manage.py migrate --noinput

# Vérifier si on doit initialiser les données de base (Points, Trajets)
echo "=== Vérification des données existantes ==="
POINT_COUNT=$(python -c "
import django
django.setup()
from core.models import Point
print(Point.objects.count())
" 2>/dev/null || echo "0")

if [ "$POINT_COUNT" = "0" ]; then
    echo "=== Base de données vide. Importation des données initiales ==="
    python manage.py loaddata initial_data || echo "Pas de fixture initial_data"
else
    echo "=== Base déjà initialisée ($POINT_COUNT points) ==="
fi

# Toujours vérifier et peupler les nouveaux modèles si vides
echo "=== Vérification des nouveaux modèles ==="

# Offres d'abonnement
OFFRE_COUNT=$(python -c "
import django
django.setup()
from core.models import OffreAbonnement
print(OffreAbonnement.objects.count())
" 2>/dev/null || echo "0")

if [ "$OFFRE_COUNT" = "0" ]; then
    echo "  -> Peuplement des offres d'abonnement..."
    python manage.py populate_offres || echo "Erreur populate_offres"
else
    echo "  -> Offres d'abonnement: $OFFRE_COUNT existante(s)"
fi

# Services Marketplace
SERVICE_COUNT=$(python -c "
import django
django.setup()
from core.models import ServiceMarketplace
print(ServiceMarketplace.objects.count())
" 2>/dev/null || echo "0")

if [ "$SERVICE_COUNT" = "0" ]; then
    echo "  -> Peuplement des services marketplace..."
    python manage.py populate_marketplace || echo "Erreur populate_marketplace"
else
    echo "  -> Services marketplace: $SERVICE_COUNT existant(s)"
fi

# Contact Info
CONTACT_COUNT=$(python -c "
import django
django.setup()
from core.models import ContactInfo
print(ContactInfo.objects.count())
" 2>/dev/null || echo "0")

if [ "$CONTACT_COUNT" = "0" ]; then
    echo "  -> Peuplement des informations de contact..."
    python manage.py populate_contacts || echo "Erreur populate_contacts"
else
    echo "  -> Informations de contact: configurées"
fi

echo "=== Initialisation terminée ==="

echo "=== Lancement du serveur Django ==="
exec python manage.py runserver 0.0.0.0:8000
