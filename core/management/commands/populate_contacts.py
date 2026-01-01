"""
Commande Django pour peupler les informations de contact.

Usage:
    python manage.py populate_contacts

Crée ou met à jour les informations de contact du footer (singleton).
Ces informations apparaissent dans le footer de l'application.
"""

from django.core.management.base import BaseCommand
from core.models import ContactInfo


class Command(BaseCommand):
    help = "Peuple la base de données avec les informations de contact"

    def handle(self, *args, **options):
        contact_data = {
            "email": "contact@taxiestimator.cm",
            "telephone": "+237 6 XX XX XX XX",
            "whatsapp": "+237 6 XX XX XX XX",
            "facebook_url": "https://facebook.com/taxiestimator",
            "twitter_url": "https://twitter.com/taxiestimator",
            "instagram_url": "https://instagram.com/taxiestimator",
            "adresse": "Yaoundé, Cameroun",
            "horaires": "Lun-Sam 8h-18h"
        }

        # Utiliser get_instance() pour respecter le pattern singleton
        contact = ContactInfo.get_instance()
        
        # Vérifier si c'est une nouvelle création ou une mise à jour
        is_new = not contact.email
        
        # Mettre à jour les champs
        for field, value in contact_data.items():
            if hasattr(contact, field):
                setattr(contact, field, value)
        
        contact.save()

        if is_new:
            self.stdout.write(self.style.SUCCESS("  ✅ Informations de contact créées:"))
        else:
            self.stdout.write(self.style.WARNING("  🔄 Informations de contact mises à jour:"))
        
        self.stdout.write(f"     📧 Email: {contact.email}")
        self.stdout.write(f"     📞 Téléphone: {contact.telephone}")
        self.stdout.write(f"     💬 WhatsApp: {contact.whatsapp}")
        
        socials = []
        if contact.facebook_url:
            socials.append("Facebook")
        if contact.twitter_url:
            socials.append("Twitter")
        if contact.instagram_url:
            socials.append("Instagram")
        
        if socials:
            self.stdout.write(f"     🌐 Réseaux sociaux: {', '.join(socials)}")
        
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Terminé! Informations de contact configurées."))
