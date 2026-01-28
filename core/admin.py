from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils import timezone
from .models import (
    Point, Trajet, ApiKey, Publicite,
    OffreAbonnement, Abonnement, ServiceMarketplace, ContactInfo, MobileUser
)


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'key_display', 'is_active', 'usage_count', 'created_at', 'last_used']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'key']
    readonly_fields = ['key', 'created_at', 'last_used', 'usage_count']
    ordering = ['-usage_count', '-created_at']
    
    def key_display(self, obj):
        """Affiche seulement les 8 premiers caractères de la clé"""
        return f"{str(obj.key)[:8]}..."
    key_display.short_description = "Clé API"
    
    def get_fieldsets(self, request, obj=None):
        """
        Fieldsets différents pour création vs édition.
        Le champ 'key' (editable=False) ne peut pas être dans le formulaire de création.
        """
        if obj:  # Edition : afficher la clé en readonly
            return (
                ('Informations', {
                    'fields': ('name', 'is_active')
                }),
                ('Clé générée', {
                    'fields': ('key',),
                    'description': 'Clé API auto-générée (UUID4). Utilisez cette clé dans le header Authorization.'
                }),
                ('Statistiques d\'utilisation', {
                    'fields': ('usage_count', 'created_at', 'last_used'),
                    'classes': ('collapse',)
                }),
            )
        else:  # Création : pas de champ 'key' (sera généré automatiquement)
            return (
                ('Informations', {
                    'fields': ('name', 'is_active'),
                    'description': 'Une clé API unique sera générée automatiquement après la sauvegarde.'
                }),
            )
    
    def get_readonly_fields(self, request, obj=None):
        """
        Tous les champs calculés/auto-générés sont readonly.
        """
        if obj:  # Edition : key, stats en readonly
            return ['key', 'created_at', 'last_used', 'usage_count']
        return []  # Création : aucun champ readonly (key n'est pas dans le form)
    
    def save_model(self, request, obj, form, change):
        """
        Override pour afficher un message avec la clé générée après création.
        """
        super().save_model(request, obj, form, change)
        if not change:  # Nouvelle création
            from django.contrib import messages
            messages.success(
                request, 
                format_html(
                    '✅ Clé API créée avec succès !<br><br>'
                    '<strong>Clé complète :</strong> <code style="background: #f5f5f5; padding: 5px; font-size: 14px;">{}</code><br><br>'
                    '⚠️ <strong>Notez cette clé maintenant</strong>, elle ne sera plus affichée en entier.<br>'
                    '📋 Utilisez-la dans vos requêtes : <code>Authorization: ApiKey {}</code>',
                    obj.key,
                    obj.key
                )
            )
    
    class Meta:
        verbose_name = "Clé API"
        verbose_name_plural = "Clés API"


@admin.register(Point)
class PointAdmin(admin.ModelAdmin):
    list_display = ['label', 'quartier', 'ville', 'coords_display', 'created_at']
    list_filter = ['ville', 'quartier', 'arrondissement']
    search_fields = ['label', 'quartier', 'ville']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Localisation', {
            'fields': ('label', 'coords_latitude', 'coords_longitude')
        }),
        ('Métadonnées administratives', {
            'fields': ('quartier', 'ville', 'arrondissement', 'departement')
        }),
        ('Informations', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def coords_display(self, obj):
        """Affiche les coordonnées formatées"""
        return f"{obj.coords_latitude:.4f}, {obj.coords_longitude:.4f}"
    coords_display.short_description = "Coordonnées"


@admin.register(Trajet)
class TrajetAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'depart_display', 'arrivee_display', 'prix', 'distance_display', 
        'heure', 'meteo_display', 'congestion_moyen', 'sinuosite_indice', 'date_ajout'
    ]
    list_filter = ['heure', 'meteo', 'type_zone', 'route_classe_dominante', 'date_ajout']
    search_fields = [
        'point_depart__label', 'point_depart__quartier', 
        'point_arrivee__label', 'point_arrivee__quartier'
    ]
    readonly_fields = [
        'distance', 'duree_estimee', 'congestion_moyen', 'sinuosite_indice',
        'route_classe_dominante', 'nb_virages', 'force_virages', 'date_ajout', 'updated_at'
    ]
    ordering = ['-date_ajout']
    
    fieldsets = (
        ('Trajet', {
            'fields': ('point_depart', 'point_arrivee', 'prix')
        }),
        ('Contexte', {
            'fields': ('heure', 'meteo', 'type_zone', 'congestion_user')
        }),
        ('Données Mapbox (calculées automatiquement)', {
            'fields': (
                'distance', 'duree_estimee', 'congestion_moyen', 
                'sinuosite_indice', 'nb_virages', 'force_virages', 
                'route_classe_dominante'
            ),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('date_ajout', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def depart_display(self, obj):
        """Affiche le point de départ avec quartier"""
        quartier = f" ({obj.point_depart.quartier})" if obj.point_depart.quartier else ""
        return f"{obj.point_depart.label}{quartier}"
    depart_display.short_description = "Départ"
    
    def arrivee_display(self, obj):
        """Affiche le point d'arrivée avec quartier"""
        quartier = f" ({obj.point_arrivee.quartier})" if obj.point_arrivee.quartier else ""
        return f"{obj.point_arrivee.label}{quartier}"
    arrivee_display.short_description = "Arrivée"
    
    def distance_display(self, obj):
        """Affiche la distance en km"""
        if obj.distance:
            return f"{obj.distance / 1000:.2f} km"
        return "-"
    distance_display.short_description = "Distance"
    
    def meteo_display(self, obj):
        """Affiche le label météo"""
        if obj.meteo is not None:
            labels = {0: "☀️ Soleil", 1: "🌧️ Pluie légère", 2: "🌧️ Pluie forte", 3: "⛈️ Orage"}
            return labels.get(obj.meteo, str(obj.meteo))
        return "-"
    meteo_display.short_description = "Météo"


class AbonnementInline(admin.TabularInline):
    """
    Inline pour gérer les abonnements directement depuis la page Publicité.
    Permet à l'admin d'ajouter/modifier des abonnements sans quitter la page.
    """
    model = Abonnement
    extra = 1  # Affiche 1 formulaire vide pour ajouter
    fields = ['offre', 'statut', 'date_debut', 'date_fin', 'jours_restants_display']
    readonly_fields = ['jours_restants_display']
    
    def jours_restants_display(self, obj):
        """Affiche les jours restants avec sécurité."""
        try:
            if not obj or not obj.pk:
                return "-"
            jours = obj.jours_restants() if hasattr(obj, 'jours_restants') else 0
            if jours <= 0:
                return mark_safe('<span style="color: red;">Expiré</span>')
            elif jours <= 7:
                return mark_safe(f'<span style="color: orange;">{jours} jours</span>')
            return f"{jours} jours"
        except Exception:
            return "-"
    jours_restants_display.short_description = "Jours restants"


@admin.register(Publicite)
class PubliciteAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'nom_entreprise_safe', 'statut', 'is_active', 
        'est_affichable_display', 'abonnement_actif', 'image_preview', 'created_at'
    ]
    list_filter = ['statut', 'category', 'is_active', 'created_at']
    search_fields = ['nom_entreprise', 'title', 'description', 'contact_email']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [AbonnementInline]  # Ajoute l'inline pour les abonnements
    
    fieldsets = (
        ('Informations Partenaire', {
            'fields': ('nom_entreprise', 'contact_email', 'contact_telephone')
        }),
        ('Contenu Publicitaire', {
            'fields': ('title', 'title_en', 'description', 'description_en', 
                      'image_url', 'app_link', 'category', 'color')
        }),
        ('Statut', {
            'fields': ('statut', 'is_active'),
            'description': 'Le statut doit être "Active" et is_active=True + abonnement valide pour être affichée.'
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def nom_entreprise_safe(self, obj):
        """Affiche le nom d'entreprise avec valeur par défaut."""
        return obj.nom_entreprise or "(Non défini)"
    nom_entreprise_safe.short_description = "Entreprise"
    nom_entreprise_safe.admin_order_field = 'nom_entreprise'
    
    def image_preview(self, obj):
        """Affiche l'aperçu de l'image avec sécurité."""
        try:
            if obj and obj.image_url:
                return mark_safe(f'<img src="{obj.image_url}" width="50" height="30" style="object-fit: cover; border-radius: 4px;" />')
        except Exception:
            pass
        return "-"
    image_preview.short_description = "Aperçu"
    
    def est_affichable_display(self, obj):
        """Vérifie si la pub est réellement affichable avec sécurité."""
        try:
            if obj and hasattr(obj, 'est_affichable') and obj.est_affichable():
                return mark_safe('<span style="color: green;">✅ Oui</span>')
        except Exception:
            pass
        return mark_safe('<span style="color: red;">❌ Non</span>')
    est_affichable_display.short_description = "Affichable?"
    
    def abonnement_actif(self, obj):
        """Affiche l'abonnement actif s'il existe avec sécurité."""
        try:
            if not obj or not obj.pk:
                return mark_safe('<span style="color: gray;">-</span>')
            abo = obj.abonnements.filter(statut=Abonnement.STATUT_ACTIF).latest('date_debut')
            jours = abo.jours_restants() if hasattr(abo, 'jours_restants') else 0
            offre_nom = abo.offre.nom if abo.offre else "?"
            if jours > 0:
                return mark_safe(f'<span style="color: green;">{offre_nom} ({jours}j)</span>')
            else:
                return mark_safe(f'<span style="color: orange;">{offre_nom} (expiré)</span>')
        except Abonnement.DoesNotExist:
            return mark_safe('<span style="color: gray;">Aucun</span>')
        except Exception:
            return mark_safe('<span style="color: gray;">-</span>')
    abonnement_actif.short_description = "Abonnement"
    
    actions = ['approuver_publicites', 'rejeter_publicites']
    
    @admin.action(description="✅ Approuver les publicités sélectionnées (+ activer abonnement)")
    def approuver_publicites(self, request, queryset):
        from django.utils import timezone
        from dateutil.relativedelta import relativedelta
        
        count = 0
        for pub in queryset:
            # Mettre à jour la publicité
            pub.statut = Publicite.STATUT_APPROUVEE
            pub.is_active = True
            pub.save()
            
            # Activer l'abonnement associé
            abo = pub.abonnements.filter(statut='en_attente').first()
            if abo:
                abo.statut = 'actif'
                abo.date_debut = timezone.now()
                if abo.offre and abo.offre.duree_mois:
                    abo.date_fin = timezone.now() + relativedelta(months=abo.offre.duree_mois)
                abo.save()
            
            count += 1
        
        self.message_user(request, f"{count} publicité(s) approuvée(s) et abonnement(s) activé(s).")
    
    @admin.action(description="❌ Rejeter les publicités sélectionnées")
    def rejeter_publicites(self, request, queryset):
        count = queryset.update(statut=Publicite.STATUT_REJETEE, is_active=False)
        self.message_user(request, f"{count} publicité(s) rejetée(s).")


@admin.register(OffreAbonnement)
class OffreAbonnementAdmin(admin.ModelAdmin):
    list_display = ['nom', 'duree_mois', 'prix_display', 'is_popular', 'is_active', 'ordre_affichage']
    list_filter = ['is_active', 'is_popular', 'duree_mois']
    search_fields = ['nom', 'description']
    ordering = ['ordre_affichage', 'prix']
    list_editable = ['ordre_affichage', 'is_active', 'is_popular']
    
    fieldsets = (
        ('Informations', {
            'fields': ('nom', 'duree_mois', 'prix', 'description')
        }),
        ('Affichage', {
            'fields': ('is_active', 'is_popular', 'ordre_affichage'),
            'description': 'L\'offre "populaire" sera mise en avant sur la page pricing.'
        }),
    )
    
    def prix_display(self, obj):
        """Affiche le prix formaté avec sécurité."""
        try:
            if obj and obj.prix is not None:
                return f"{obj.prix:,.0f} FCFA"
        except Exception:
            pass
        return "-"
    prix_display.short_description = "Prix"


@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    list_display = [
        'publicite_safe', 'offre_safe', 'statut', 'date_debut', 'date_fin', 
        'jours_restants_display', 'est_expire_display'
    ]
    list_filter = ['statut', 'offre', 'date_debut']
    search_fields = ['publicite__nom_entreprise', 'publicite__title', 'publicite__contact_email']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Liaison', {
            'fields': ('publicite', 'offre')
        }),
        ('Durée', {
            'fields': ('date_debut', 'date_fin', 'statut'),
            'description': 'La date de fin est calculée automatiquement si vous définissez la date de début.'
        }),
        ('Paiement', {
            'fields': ('montant_paye', 'reference_paiement'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def publicite_safe(self, obj):
        """Affiche la publicité avec sécurité."""
        try:
            if obj and obj.publicite:
                return obj.publicite.title or "(Sans titre)"
        except Exception:
            pass
        return "-"
    publicite_safe.short_description = "Publicité"
    publicite_safe.admin_order_field = 'publicite__title'
    
    def offre_safe(self, obj):
        """Affiche l'offre avec sécurité."""
        try:
            if obj and obj.offre:
                return obj.offre.nom
        except Exception:
            pass
        return "-"
    offre_safe.short_description = "Offre"
    offre_safe.admin_order_field = 'offre__nom'
    
    def jours_restants_display(self, obj):
        """Affiche les jours restants avec sécurité."""
        try:
            if not obj or not obj.pk:
                return "-"
            jours = obj.jours_restants() if hasattr(obj, 'jours_restants') else 0
            if jours <= 0:
                return mark_safe('<span style="color: red;">Expiré</span>')
            elif jours <= 7:
                return mark_safe(f'<span style="color: orange;">{jours} jours</span>')
            return f"{jours} jours"
        except Exception:
            return "-"
    jours_restants_display.short_description = "Jours restants"
    
    def est_expire_display(self, obj):
        """Affiche si expiré avec sécurité."""
        try:
            if not obj or not obj.pk:
                return "-"
            if hasattr(obj, 'est_expire') and obj.est_expire():
                return mark_safe('<span style="color: red;">❌ Expiré</span>')
            return mark_safe('<span style="color: green;">✅ Actif</span>')
        except Exception:
            return "-"
    est_expire_display.short_description = "Statut réel"
    
    actions = ['mettre_a_jour_expirations', 'activer_abonnements', 'prolonger_1_mois']
    
    @admin.action(description="🔄 Mettre à jour les expirations")
    def mettre_a_jour_expirations(self, request, queryset):
        Abonnement.objects.mettre_a_jour_expirations()
        self.message_user(request, "Expirations mises à jour.")
    
    @admin.action(description="✅ Activer les abonnements sélectionnés")
    def activer_abonnements(self, request, queryset):
        from django.utils import timezone
        from dateutil.relativedelta import relativedelta
        
        count = 0
        for abo in queryset:
            abo.statut = 'actif'
            abo.date_debut = timezone.now()
            if abo.offre and abo.offre.duree_mois:
                abo.date_fin = timezone.now() + relativedelta(months=abo.offre.duree_mois)
            abo.save()
            
            # Activer aussi la publicité associée
            if abo.publicite:
                abo.publicite.statut = 'active'
                abo.publicite.is_active = True
                abo.publicite.save()
            
            count += 1
        
        self.message_user(request, f"{count} abonnement(s) activé(s).")
    
    @admin.action(description="➕ Prolonger d'un mois")
    def prolonger_1_mois(self, request, queryset):
        from django.utils import timezone
        from dateutil.relativedelta import relativedelta
        
        count = 0
        for abo in queryset:
            if abo.date_fin:
                # Prolonger depuis la date de fin actuelle
                abo.date_fin = abo.date_fin + relativedelta(months=1)
            else:
                # Si pas de date de fin, commencer maintenant
                abo.date_fin = timezone.now() + relativedelta(months=1)
            abo.statut = 'actif'
            abo.save()
            count += 1
        
        self.message_user(request, f"{count} abonnement(s) prolongé(s) d'un mois.")


@admin.register(ServiceMarketplace)
class ServiceMarketplaceAdmin(admin.ModelAdmin):
    list_display = ['nom', 'is_active', 'image_preview', 'ordre_affichage', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['nom', 'description']
    ordering = ['ordre_affichage', '-created_at']
    list_editable = ['is_active', 'ordre_affichage']
    
    fieldsets = (
        ('Informations', {
            'fields': ('nom', 'nom_en', 'description', 'description_en', 'image_url', 'lien_redirection')
        }),
        ('Apparence', {
            'fields': ('icone', 'couleur'),
            'classes': ('collapse',)
        }),
        ('Affichage', {
            'fields': ('is_active', 'is_featured', 'ordre_affichage')
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']
    
    def image_preview(self, obj):
        if obj.image_url:
            return mark_safe(f'<img src="{obj.image_url}" width="60" height="40" style="object-fit: cover; border-radius: 4px;" />')
        return "-"
    image_preview.short_description = "Aperçu"


@admin.register(ContactInfo)
class ContactInfoAdmin(admin.ModelAdmin):
    list_display = ['email', 'telephone', 'whatsapp', 'has_socials', 'updated_at']
    readonly_fields = ['updated_at']
    
    fieldsets = (
        ('Contact Direct', {
            'fields': ('email', 'telephone', 'whatsapp')
        }),
        ('Adresse & Horaires', {
            'fields': ('adresse', 'horaires'),
            'classes': ('collapse',)
        }),
        ('Réseaux Sociaux', {
            'fields': ('facebook_url', 'twitter_url', 'instagram_url'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('updated_at',),
            'classes': ('collapse',)
        }),
    )
    
    def has_socials(self, obj):
        """Indique si des réseaux sociaux sont configurés."""
        socials = [obj.facebook_url, obj.twitter_url, obj.instagram_url]
        count = sum(1 for s in socials if s)
        if count > 0:
            return mark_safe(f'<span style="color: green;">{count} configuré(s)</span>')
        return mark_safe('<span style="color: gray;">Aucun</span>')
    has_socials.short_description = "Réseaux sociaux"
    
    def has_add_permission(self, request):
        """Empêche la création de plusieurs ContactInfo (singleton)."""
        if ContactInfo.objects.exists():
            return False
        return super().has_add_permission(request)
    
    def has_delete_permission(self, request, obj=None):
        """Empêche la suppression du ContactInfo."""
        return False


@admin.register(MobileUser)
class MobileUserAdmin(admin.ModelAdmin):
    """
    Administration des utilisateurs mobiles (Firebase Phone Auth).
    
    Ces utilisateurs s'authentifient via leur numéro de téléphone sur l'app mobile.
    Ce système est séparé de l'auth admin Django et des ApiKeys.
    """
    list_display = ['primary_contact', 'auth_method', 'is_active', 'created_at', 'last_login']
    list_filter = ['auth_method', 'is_active', 'created_at', 'last_login']
    search_fields = ['email', 'phone_number', 'display_name', 'firebase_uid']
    readonly_fields = ['firebase_uid', 'phone_number', 'email', 'photo_url', 'auth_method', 'created_at', 'last_login']
    ordering = ['-last_login', '-created_at']
    
    fieldsets = (
        ('Identité Firebase', {
            'fields': ('firebase_uid', 'auth_method'),
            'description': 'Ces champs sont gérés par Firebase et ne peuvent pas être modifiés.'
        }),
        ('Profil utilisateur', {
            'fields': ('display_name', 'email', 'phone_number', 'photo_url', 'is_active'),
        }),
        ('Statistiques', {
            'fields': ('created_at', 'last_login'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """
        Empêche la création manuelle d'utilisateurs.
        Les MobileUsers sont créés automatiquement via Firebase Auth.
        """
        return False

    def primary_contact(self, obj):
        """Affiche l'email si disponible, sinon le nom ou le téléphone."""
        return obj.email or obj.display_name or obj.phone_number or obj.firebase_uid
    primary_contact.short_description = "Identifiant"
    
    actions = ['desactiver_utilisateurs', 'reactiver_utilisateurs']
    
    @admin.action(description="Désactiver les utilisateurs sélectionnés")
    def desactiver_utilisateurs(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} utilisateur(s) désactivé(s).")
    
    @admin.action(description="Réactiver les utilisateurs sélectionnés")
    def reactiver_utilisateurs(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} utilisateur(s) réactivé(s).")


# Personnalisation du site admin
admin.site.site_header = "Administration Taxi Estimator Cameroun"
admin.site.site_title = "Taxi Estimator Admin"
admin.site.index_title = "Gestion de l'API et des données"
