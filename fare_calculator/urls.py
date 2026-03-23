"""
URL configuration for fare_calculator project.

Routes principales :
    - /admin/ : Interface Django Admin pour gestion données/clés API
    - /api/ : API REST pour estimation prix taxi (authentification ApiKey requise)
    - /api/health/ : Health check (sans authentification)
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView


urlpatterns = [
    # Interface admin Django
    path('admin/', admin.site.urls),
    
    # API REST (authentification ApiKey via middleware)
    path('fare-api/', include('core.urls')),
    path('fare-api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('fare-api/docs/', SpectacularSwaggerView.as_view(url='/fare-calculator/fare-api/schema/'), name='swagger-ui'),
    path('fare-api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
