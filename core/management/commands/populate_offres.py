"""
Commande Django pour peupler les offres d'abonnement.

Usage:
    python manage.py populate_offres

Crée au moins 3 offres d'abonnement pour la page Pricing.
Ces offres permettent aux partenaires de souscrire pour afficher leurs publicités.
"""

from django.core.management.base import BaseCommand
from decimal import Decimal
from core.models import OffreAbonnement


class Command(BaseCommand):
    help = "Peuple la base de données avec des offres d'abonnement exemples"

    def handle(self, *args, **options):
        offres_data = [
            {
                "nom": "Starter",
                "duree_mois": 1,
                "prix": Decimal("15000"),
                "description": "Idéal pour tester notre plateforme. Affichage de votre publicité pendant 1 mois avec statistiques basiques.",
                "is_active": True,
                "is_popular": False,
                "ordre_affichage": 1
            },
            {
                "nom": "Business",
                "duree_mois": 3,
                "prix": Decimal("40000"),
                "description": "Notre offre la plus populaire ! 3 mois de visibilité avec statistiques détaillées et support prioritaire. Économisez 5000 FCFA.",
                "is_active": True,
                "is_popular": True,  # Mise en avant sur la page pricing
                "ordre_affichage": 2
            },
            {
                "nom": "Enterprise",
                "duree_mois": 12,
                "prix": Decimal("120000"),
                "description": "Engagement annuel avec visibilité maximale. Statistiques avancées, support VIP et 4 mois gratuits (économisez 60000 FCFA).",
                "is_active": True,
                "is_popular": False,
                "ordre_affichage": 3
            },
            {
                "nom": "Promo Lancement",
                "duree_mois": 1,
                "prix": Decimal("5000"),
                "description": "Offre spéciale de lancement ! Profitez d'un mois de publicité à prix réduit pour découvrir notre service.",
                "is_active": True,
                "is_popular": False,
                "ordre_affichage": 0  # Avant les autres
            }
        ]

        created_count = 0
        updated_count = 0

        for data in offres_data:
            offre, created = OffreAbonnement.objects.update_or_create(
                nom=data["nom"],
                defaults={
                    "duree_mois": data["duree_mois"],
                    "prix": data["prix"],
                    "description": data["description"],
                    "is_active": data["is_active"],
                    "is_popular": data["is_popular"],
                    "ordre_affichage": data["ordre_affichage"]
                }
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  ✅ Créé: {offre.nom} - {offre.duree_mois} mois - {offre.prix:,.0f} FCFA"
                ))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(
                    f"  🔄 Mis à jour: {offre.nom} - {offre.duree_mois} mois - {offre.prix:,.0f} FCFA"
                ))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Terminé! {created_count} offre(s) créée(s), {updated_count} mise(s) à jour."
        ))
