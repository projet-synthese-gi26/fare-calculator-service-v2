from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Point, Trajet, ApiKey, Publicite


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


@admin.register(Publicite)
class PubliciteAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'is_active', 'image_preview', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['title', 'description']
    ordering = ['-created_at']
    
    def image_preview(self, obj):
        if obj.image_url:
            return mark_safe(f'<img src="{obj.image_url}" width="50" height="30" style="object-fit: cover; border-radius: 4px;" />')
        return "-"
    image_preview.short_description = "Aperçu"


# Personnalisation du site admin
admin.site.site_header = "Administration Taxi Estimator Cameroun"
admin.site.site_title = "Taxi Estimator Admin"
admin.site.index_title = "Gestion de l'API et des données"
