"""
Script pour exporter les données de la BD locale vers un fichier JSON.
Gère correctement l'encodage UTF-8 pour Windows.

Usage:
    python export_data.py
"""

import os
import sys
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fare_calculator.settings')

import django
django.setup()

from django.core import serializers
from core.models import (
    Point, Trajet, ApiKey, Publicite,
    OffreAbonnement, Abonnement, ServiceMarketplace, ContactInfo
)
from django.contrib.auth.models import User


def export_data():
    """Exporte toutes les données vers un fichier JSON avec encodage UTF-8."""
    
    data = []
    
    # Exporter les utilisateurs
    print("Exportation des utilisateurs...")
    users = User.objects.all()
    data.extend(json.loads(serializers.serialize('json', users)))
    
    # Exporter les Points
    print("Exportation des points...")
    points = Point.objects.all()
    data.extend(json.loads(serializers.serialize('json', points)))
    
    # Exporter les Trajets
    print("Exportation des trajets...")
    trajets = Trajet.objects.all()
    data.extend(json.loads(serializers.serialize('json', trajets)))
    
    # Exporter les ApiKeys
    print("Exportation des clés API...")
    apikeys = ApiKey.objects.all()
    data.extend(json.loads(serializers.serialize('json', apikeys)))
    
    # Exporter les Publicités
    print("Exportation des publicités...")
    publicites = Publicite.objects.all()
    data.extend(json.loads(serializers.serialize('json', publicites)))
    
    # Exporter les Offres d'abonnement
    print("Exportation des offres d'abonnement...")
    offres = OffreAbonnement.objects.all()
    data.extend(json.loads(serializers.serialize('json', offres)))
    
    # Exporter les Abonnements
    print("Exportation des abonnements...")
    abonnements = Abonnement.objects.all()
    data.extend(json.loads(serializers.serialize('json', abonnements)))
    
    # Exporter les Services Marketplace
    print("Exportation des services marketplace...")
    services = ServiceMarketplace.objects.all()
    data.extend(json.loads(serializers.serialize('json', services)))
    
    # Exporter les ContactInfo
    print("Exportation des informations de contact...")
    contacts = ContactInfo.objects.all()
    data.extend(json.loads(serializers.serialize('json', contacts)))
    
    # Écrire le fichier avec encodage UTF-8 explicite
    output_path = os.path.join('core', 'fixtures', 'initial_data.json')
    
    print(f"\nÉcriture dans {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Export terminé! {len(data)} objets exportés.")
    print(f"   - Utilisateurs: {users.count()}")
    print(f"   - Points: {points.count()}")
    print(f"   - Trajets: {trajets.count()}")
    print(f"   - Clés API: {apikeys.count()}")
    print(f"   - Publicités: {publicites.count()}")
    print(f"   - Offres d'abonnement: {offres.count()}")
    print(f"   - Abonnements: {abonnements.count()}")
    print(f"   - Services Marketplace: {services.count()}")
    print(f"   - Contacts: {contacts.count()}")


if __name__ == '__main__':
    export_data()
