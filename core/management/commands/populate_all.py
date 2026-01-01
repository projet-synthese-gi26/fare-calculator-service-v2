"""
Commande Django pour exécuter toutes les commandes de peuplement.

Usage:
    python manage.py populate_all

Exécute dans l'ordre:
    1. populate_offres - Offres d'abonnement
    2. populate_marketplace - Services Marketplace
    3. populate_contacts - Informations de contact

Utile pour initialiser rapidement une nouvelle base de données.
"""

from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Exécute toutes les commandes de peuplement de la base de données"

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO("=" * 60))
        self.stdout.write(self.style.HTTP_INFO("  PEUPLEMENT COMPLET DE LA BASE DE DONNÉES"))
        self.stdout.write(self.style.HTTP_INFO("=" * 60))
        self.stdout.write("")
        
        # 1. Offres d'abonnement
        self.stdout.write(self.style.HTTP_INFO("📦 1. Peuplement des offres d'abonnement..."))
        self.stdout.write("-" * 40)
        call_command('populate_offres')
        self.stdout.write("")
        
        # 2. Services Marketplace
        self.stdout.write(self.style.HTTP_INFO("🏪 2. Peuplement des services Marketplace..."))
        self.stdout.write("-" * 40)
        call_command('populate_marketplace')
        self.stdout.write("")
        
        # 3. Informations de contact
        self.stdout.write(self.style.HTTP_INFO("📞 3. Peuplement des informations de contact..."))
        self.stdout.write("-" * 40)
        call_command('populate_contacts')
        self.stdout.write("")
        
        self.stdout.write(self.style.HTTP_INFO("=" * 60))
        self.stdout.write(self.style.SUCCESS("  ✅ PEUPLEMENT TERMINÉ AVEC SUCCÈS !"))
        self.stdout.write(self.style.HTTP_INFO("=" * 60))
        
        self.stdout.write("")
        self.stdout.write("Prochaines étapes:")
        self.stdout.write("  - Accédez à l'admin Django pour vérifier les données")
        self.stdout.write("  - Testez les endpoints API:")
        self.stdout.write("    GET /api/offres-abonnement/")
        self.stdout.write("    GET /api/services-marketplace/")
        self.stdout.write("    GET /api/contact-info/")
