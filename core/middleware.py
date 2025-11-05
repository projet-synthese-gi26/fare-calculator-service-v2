"""
Middleware personnalisé pour validation des clés API.

ApiKeyMiddleware :
    - Intercepte toutes requêtes vers /api/ (sauf endpoints exemptés)
    - Vérifie présence header Authorization avec format "ApiKey <uuid>"
    - Valide clé dans BD (ApiKey.objects.filter(key=<uuid>, is_active=True))
    - Si valide : passe à view + met à jour last_used
    - Si invalide : retourne HTTP 401 Unauthorized avec message explicite

Endpoints exemptés (pas besoin clé API) :
    - /admin/ (interface Django Admin)
    - /api/health/ (health check pour monitoring)
    - /api/docs/ (documentation API Swagger/ReDoc, optionnel)
    
Configuration :
    Ajouté dans settings.py MIDDLEWARE après AuthenticationMiddleware :
    'core.middleware.ApiKeyMiddleware'
"""

from django.http import JsonResponse
from django.conf import settings
import logging
import re

logger = logging.getLogger(__name__)


class ApiKeyMiddleware:
    """
    Middleware validation clés API pour sécuriser l'API sans auth utilisateur.
    
    Workflow :
        1. Request arrive
        2. Si path dans exemptions (admin, health), skip validation → process_request return None (continue)
        3. Si path commence par /api/ :
            a. Extraire header Authorization
            b. Parser format "ApiKey <uuid>"
            c. Query BD : ApiKey.objects.get(key=<uuid>, is_active=True)
            d. Si trouvée : mettre à jour last_used, continuer (return None)
            e. Si pas trouvée ou inactive : retourner JsonResponse 401
        4. Si path ne commence pas par /api/, skip validation (autres URLs projet)
        
    Exemples headers valides :
        Authorization: ApiKey 550e8400-e29b-41d4-a716-446655440000
        
    Réponses erreur :
        401 Unauthorized :
            {"error": "API Key requise", "detail": "Header Authorization manquant ou invalide"}
            {"error": "API Key invalide", "detail": "Clé inexistante ou désactivée"}
    """
    
    # Patterns d'exemption (regex)
    EXEMPT_PATHS = [
        r'^/admin/',       # Django Admin
        r'^/api/health/$', # Health check
        r'^/api/docs/',    # Documentation API (si implémentée)
        r'^/static/',      # Fichiers statiques
        r'^/media/',       # Fichiers media
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        """
        Valide clé API pour requêtes /api/ (sauf exemptions).
        
        Args:
            request : HttpRequest Django
            
        Returns:
            JsonResponse : Erreur 401 si validation échoue
            Response normale : Si validation OK ou path exempté
        """
        path = request.path
        
        # Vérifier exemptions
        for pattern in self.EXEMPT_PATHS:
            if re.match(pattern, path):
                logger.debug(f"Path {path} exempté de validation API Key")
                return self.get_response(request)  # Skip validation
        
        # Valider uniquement si path commence par /api/
        if not path.startswith('/api/'):
            return self.get_response(request)  # Skip validation (autre partie du projet)
        
        # Extraire header Authorization
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header:
            logger.warning(f"Requête {path} sans header Authorization")
            return JsonResponse(
                {
                    'error': 'API Key requise',
                    'detail': (
                        'Header Authorization manquant. '
                        'Format attendu : "Authorization: ApiKey <votre-cle-uuid>"'
                    )
                },
                status=401
            )
        
        # Parser format "ApiKey <uuid>"
        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != 'ApiKey':
            logger.warning(f"Format Authorization invalide : {auth_header}")
            return JsonResponse(
                {
                    'error': 'API Key invalide',
                    'detail': (
                        'Format Authorization incorrect. '
                        'Format attendu : "Authorization: ApiKey <votre-cle-uuid>"'
                    )
                },
                status=401
            )
        
        api_key_str = parts[1]
        
        # Valider clé dans BD
        try:
            from .models import ApiKey
            api_key = ApiKey.objects.get(key=api_key_str, is_active=True)
            
            # Mettre à jour last_used
            api_key.update_last_used()
            
            # Attacher api_key à request pour usage dans views (optionnel, pour logs/analytics)
            request.api_key = api_key
            
            logger.info(f"API Key valide : {api_key.name} (dernière utilisation mise à jour)")
            return self.get_response(request)  # Continuer vers view
            
        except ApiKey.DoesNotExist:
            logger.warning(f"API Key invalide ou inactive : {api_key_str[:8]}...")
            return JsonResponse(
                {
                    'error': 'API Key invalide',
                    'detail': (
                        'Clé API inexistante ou désactivée. '
                        'Contactez l\'administrateur pour obtenir une clé valide.'
                    )
                },
                status=401
            )
        except Exception as e:
            logger.error(f"Erreur validation API Key : {e}")
            return JsonResponse(
                {
                    'error': 'Erreur serveur',
                    'detail': 'Impossible de valider la clé API. Réessayez plus tard.'
                },
                status=500
            )