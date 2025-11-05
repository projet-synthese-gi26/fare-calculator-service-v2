"""
URLs pour l'API core du service d'estimation de prix taxi Cameroun.

Routes exposées :
    - POST /api/estimate/ : Estimation prix pour trajet (endpoint principal)
    - POST /api/trajets/ : Ajouter trajet réel avec prix payé (contribution communautaire)
    - GET /api/trajets/ : Lister trajets (pour debug/admin)
    - GET /api/points/ : Lister POI disponibles (auto-complétion frontend)
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
    HealthCheckView
)

# Router DRF pour ViewSets CRUD
router = DefaultRouter()
router.register(r'points', PointViewSet, basename='point')
router.register(r'trajets', TrajetViewSet, basename='trajet')

# URLs patterns
urlpatterns = [
    # Routes CRUD via router
    path('', include(router.urls)),
    
    # Endpoint estimation prix (POST)
    path('estimate/', EstimateView.as_view(), name='estimate'),
    
    # Endpoint ajout trajet (alias pour POST /trajets/ avec validation spécifique)
    path('add-trajet/', AddTrajetView.as_view(), name='add-trajet'),
    
    # Health check (pas d'auth requise)
    path('health/', HealthCheckView.as_view(), name='health'),
]
