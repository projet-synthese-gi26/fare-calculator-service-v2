"""
URL configuration for fare_calculator project.

Routes principales :
    - /admin/ : Interface Django Admin pour gestion données/clés API
    - /api/ : API REST pour estimation prix taxi (authentification ApiKey requise)
    - /api/health/ : Health check (sans authentification)
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Interface admin Django
    path('admin/', admin.site.urls),
    
    # API REST (authentification ApiKey via middleware)
    path('api/', include('core.urls')),
]
