"""
URLs pour l'API core du service d'estimation de prix taxi Cameroun.

Routes exposées :
    - POST /api/estimate/ : Estimation prix pour trajet (endpoint principal)
    - POST /api/trajets/ : Ajouter trajet réel avec prix payé (contribution communautaire)
    - GET /api/trajets/ : Lister trajets (pour debug/admin)
    - GET /api/points/ : Lister POI disponibles (auto-complétion frontend)
    - GET /api/publicites/ : Liste des publicités partenaires affichables
    - POST /api/publicites/ : Soumettre une demande de publicité
    - GET /api/offres-abonnement/ : Liste des offres d'abonnement (page Pricing)
    - GET /api/abonnements/verifier/{id}/ : Vérifier abonnement d'une pub
    - GET /api/services-marketplace/ : Liste des services externes (Hayden Go, etc.)
    - GET /api/contact-info/ : Informations de contact du footer
    - GET /api/stats/ : Statistiques globales
    - GET /api/health/ : Health check (monitoring)

Authentification :
    - Toutes routes /api/* (sauf /health/) nécessitent ApiKey header
    - Gérée par middleware core.middleware.ApiKeyMiddleware
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PointViewSet,
    TrajetViewSet,
    EstimateView,
    AddTrajetView,
    HealthCheckView,
    StatsView,
    PubliciteViewSet,
    OffreAbonnementViewSet,
    AbonnementViewSet,
    ServiceMarketplaceViewSet,
    ContactInfoViewSet
)

# Router DRF pour ViewSets CRUD
router = DefaultRouter()
router.register(r'points', PointViewSet, basename='point')
router.register(r'trajets', TrajetViewSet, basename='trajet')
router.register(r'publicites', PubliciteViewSet, basename='publicite')
router.register(r'offres-abonnement', OffreAbonnementViewSet, basename='offre-abonnement')
router.register(r'abonnements', AbonnementViewSet, basename='abonnement')
router.register(r'services-marketplace', ServiceMarketplaceViewSet, basename='service-marketplace')
router.register(r'contact-info', ContactInfoViewSet, basename='contact-info')

from .async_views import AsyncEstimateView

# URLs patterns
urlpatterns = [
    # Routes CRUD via router
    path('', include(router.urls)),
    
    # Endpoint estimation prix (POST) - Sync
    path('estimate/', EstimateView.as_view(), name='estimate'),
    
    # Endpoint estimation prix (POST) - ASYNC (Désactivé pour le moment sur demande user)
    path('estimate-async/', AsyncEstimateView.as_view(), name='estimate-async'),
    
    # Endpoint ajout trajet (alias pour POST /trajets/ avec validation spécifique)
    path('add-trajet/', AddTrajetView.as_view(), name='add-trajet'),
    
    # Endpoint statistiques globales
    path('stats/', StatsView.as_view(), name='stats'),

    # Health check (pas d'auth requise)
    path('health/', HealthCheckView.as_view(), name='health'),
]
