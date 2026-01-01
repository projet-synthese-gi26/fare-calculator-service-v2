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
        2. Si path dans exemptions (admin, health), skip validation -> process_request return None (continue)
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
        r'^/api/doc',      # Alias documentation (pour éviter erreurs typo)
        r'^/api/schema/',  # Schema OpenAPI
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

        # Allow CORS preflight requests (OPTIONS) to pass without authentication.
        # Browsers send OPTIONS preflight requests without Authorization header.
        if request.method == 'OPTIONS':
            logger.debug(f"OPTIONS request bypassed authentication for path {path}")
            return self.get_response(request)
        
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


# Classe d'authentification DRF pour Swagger/drf-spectacular
from rest_framework.authentication import TokenAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

class ApiKeyAuthentication(TokenAuthentication):
    """
    Classe d'authentification DRF pour intégration avec drf-spectacular.
    
    Détecte le header "Authorization: ApiKey <clé>" et valide la clé.
    Utilisée par drf-spectacular pour générer la documentation Swagger.
    
    Note: La validation réelle se fait via ApiKeyMiddleware au niveau Django.
    Cette classe sert surtout à faire comprendre à Swagger comment s'authentifier.
    """
    keyword = 'ApiKey'
    
    def get_model(self):
        from .models import ApiKey
        return ApiKey
    
    def authenticate(self, request):
        """Valide la clé API depuis le header Authorization."""
        auth = get_authorization_header(request).split()
        
        if not auth or auth[0].lower() != b'apikey':
            return None  # Pas d'authentification fournie, continuer
        
        if len(auth) == 1:
            msg = 'Invalid token header. No credentials provided.'
            raise AuthenticationFailed(msg)
        elif len(auth) > 2:
            msg = 'Invalid token header. Token string should not contain spaces.'
            raise AuthenticationFailed(msg)
        
        try:
            token = auth[1].decode()
        except UnicodeError:
            msg = 'Invalid token header. Token string should not contain invalid characters.'
            raise AuthenticationFailed(msg)
        
        return self.authenticate_credentials(token)
    
    def authenticate_credentials(self, key):
        """Valide la clé et retourne un tuple (user, auth) pour DRF."""
        from .models import ApiKey
        
        try:
            api_key = ApiKey.objects.get(key=key, is_active=True)
        except ApiKey.DoesNotExist:
            raise AuthenticationFailed('Invalid token.')
        
        # Mettre à jour last_used
        from django.utils import timezone
        api_key.last_used = timezone.now()
        api_key.save(update_fields=['last_used'])
        
        # Retourner (user=None, auth=api_key) pour drf-spectacular
        return (None, api_key)