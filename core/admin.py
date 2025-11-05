from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Point, Trajet, ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'key_display', 'is_active', 'usage_count', 'created_at', 'last_used']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'key']
    readonly_fields = ['key', 'created_at', 'last_used', 'usage_count']
    ordering = ['-usage_count', '-created_at']
    
    fieldsets = (
        ('Informations', {
            'fields': ('name', 'key', 'is_active')
        }),
        ('Statistiques', {
            'fields': ('usage_count', 'created_at', 'last_used')
        }),
    )
    
    def key_display(self, obj):
        """Affiche seulement les 8 premiers caractères de la clé"""
        return f"{str(obj.key)[:8]}..."
    key_display.short_description = "Clé API"
    
    def get_readonly_fields(self, request, obj=None):
        """La clé est readonly après création"""
        if obj:  # Edition
            return self.readonly_fields
        return ['created_at', 'last_used', 'usage_count']  # Création : on peut voir la clé complète
    
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


# Personnalisation du site admin
admin.site.site_header = "Administration Taxi Estimator Cameroun"
admin.site.site_title = "Taxi Estimator Admin"
admin.site.index_title = "Gestion de l'API et des données"
