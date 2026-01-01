"""
Commande Django pour peupler les services du Marketplace.

Usage:
    python manage.py populate_marketplace

Crée au moins 5 services exemple pour la section Marketplace.
Ces services représentent des partenaires externes (Hayden Go, Flip Management, etc.)
et non des publicités partenaires.
"""

from django.core.management.base import BaseCommand
from core.models import ServiceMarketplace


class Command(BaseCommand):
    help = "Peuple la base de données avec des services Marketplace exemples"

    def handle(self, *args, **options):
        services_data = [
            {
                "nom": "Hayden Go",
                "description": "Service de transport VTC premium. Réservez votre chauffeur privé pour vos déplacements professionnels et personnels à Yaoundé.",
                "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=300&fit=crop",
                "lien_redirection": "https://haydengo.cm",
                "is_active": True,
                "ordre_affichage": 1
            },
            {
                "nom": "Flip Management",
                "description": "Gestion immobilière simplifiée. Trouvez votre logement idéal ou confiez-nous la gestion de vos biens.",
                "image_url": "https://images.unsplash.com/photo-1560518883-ce09059eeffa?w=400&h=300&fit=crop",
                "lien_redirection": "https://flipmanagement.cm",
                "is_active": True,
                "ordre_affichage": 2
            },
            {
                "nom": "Jumia Food",
                "description": "Livraison de repas à domicile. Commandez vos plats préférés des meilleurs restaurants de la ville.",
                "image_url": "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=400&h=300&fit=crop",
                "lien_redirection": "https://food.jumia.cm",
                "is_active": True,
                "ordre_affichage": 3
            },
            {
                "nom": "MTN Mobile Money",
                "description": "Paiements mobiles sécurisés. Transférez de l'argent, payez vos factures et bien plus depuis votre téléphone.",
                "image_url": "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=400&h=300&fit=crop",
                "lien_redirection": "https://mtn.cm/momo",
                "is_active": True,
                "ordre_affichage": 4
            },
            {
                "nom": "Orange Money",
                "description": "La solution de paiement mobile Orange. Envoyez et recevez de l'argent facilement partout au Cameroun.",
                "image_url": "https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=400&h=300&fit=crop",
                "lien_redirection": "https://orange.cm/orange-money",
                "is_active": True,
                "ordre_affichage": 5
            },
            {
                "nom": "Express Union",
                "description": "Transfert d'argent rapide et fiable. Plus de 500 agences à travers le Cameroun pour vos transactions.",
                "image_url": "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?w=400&h=300&fit=crop",
                "lien_redirection": "https://expressunion.cm",
                "is_active": True,
                "ordre_affichage": 6
            }
        ]

        created_count = 0
        updated_count = 0

        for data in services_data:
            service, created = ServiceMarketplace.objects.update_or_create(
                nom=data["nom"],
                defaults={
                    "description": data["description"],
                    "image_url": data["image_url"],
                    "lien_redirection": data["lien_redirection"],
                    "is_active": data["is_active"],
                    "ordre_affichage": data["ordre_affichage"]
                }
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  ✅ Créé: {service.nom}"))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f"  🔄 Mis à jour: {service.nom}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Terminé! {created_count} service(s) créé(s), {updated_count} mis à jour."
        ))
