"""
Vues pour l'authentification Firebase multi-mode.

Ces vues permettent aux utilisateurs mobiles de s'authentifier via :
    - Téléphone + SMS (plan Firebase Blaze requis)
    - Téléphone + Mot de passe (gratuit, email simulé)
    - Google OAuth

Ces méthodes n'affectent pas les autres systèmes d'authentification :
    - ApiKey pour les partenaires/développeurs (middleware inchangé)
    - Django Admin username/password (inchangé)

Endpoints :
    POST /api/auth/verify-token/ : Vérifie un token Firebase et crée/retourne l'utilisateur
    GET /api/auth/me/ : Retourne les infos de l'utilisateur connecté (nécessite token)
"""

import logging
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import MobileUser
from .serializers import (
    MobileUserSerializer,
    FirebaseTokenVerifySerializer,
    FirebaseAuthResponseSerializer
)
from .firebase_admin_config import verify_firebase_token

logger = logging.getLogger(__name__)


def extract_phone_from_email(email: str) -> str | None:
    """
    Extrait le numéro de téléphone depuis un email simulé.
    
    Format attendu : 237XXXXXXXXX@farecalc.phone
    Retourne : +237XXXXXXXXX ou None si pas d'email simulé
    """
    if not email or not email.endswith('@farecalc.phone'):
        return None
    
    digits = email.replace('@farecalc.phone', '')
    if digits.startswith('237') and len(digits) == 12:
        return f'+{digits}'
    
    return None


class FirebaseVerifyTokenView(APIView):
    """
    Vérifie un token Firebase ID et crée/retourne l'utilisateur mobile.
    
    Supporte plusieurs modes d'authentification :
        - phone_sms : Token avec phone_number (plan Blaze)
        - phone_password : Token avec email simulé (237xxx@farecalc.phone)
        - google : Token avec email Google
    
    Workflow :
        1. Reçoit POST avec { "id_token": "...", "auth_method": "..." }
        2. Vérifie le token avec Firebase Admin SDK
        3. Extrait UID et identifiant (téléphone ou email)
        4. Crée ou récupère MobileUser en base
        5. Met à jour last_login
        6. Retourne les infos utilisateur
        
    Réponses :
        200 OK : Authentification réussie + infos user
        400 Bad Request : Token manquant ou invalide
        401 Unauthorized : Token Firebase invalide/expiré
        403 Forbidden : Utilisateur désactivé
        500 Internal Server Error : Erreur serveur (Firebase non configuré, etc.)
    """
    
    @extend_schema(
        request=FirebaseTokenVerifySerializer,
        responses={
            200: OpenApiResponse(
                response=FirebaseAuthResponseSerializer,
                description="Authentification réussie"
            ),
            400: OpenApiResponse(description="Token manquant"),
            401: OpenApiResponse(description="Token invalide ou expiré"),
            403: OpenApiResponse(description="Utilisateur désactivé"),
            500: OpenApiResponse(description="Erreur serveur Firebase")
        },
        summary="Vérifier token Firebase",
        description="Vérifie un ID Token Firebase et crée/retourne l'utilisateur associé",
        tags=["Authentification Mobile"]
    )
    def post(self, request):
        serializer = FirebaseTokenVerifySerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Token manquant",
                "detail": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        id_token = serializer.validated_data['id_token']
        # auth_method peut être passé par le frontend pour indiquer le mode utilisé
        auth_method_hint = request.data.get('auth_method', None)
        
        try:
            # Vérifier le token avec Firebase Admin SDK
            decoded_token = verify_firebase_token(id_token)
            
            if decoded_token is None:
                return Response({
                    "success": False,
                    "error": "Token invalide",
                    "detail": "Le token Firebase est invalide, expiré ou révoqué"
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # Extraire les informations du token
            firebase_uid = decoded_token.get('uid')
            phone_number = decoded_token.get('phone_number')  # Phone Auth SMS
            email = decoded_token.get('email')  # Email/Password ou Google
            name = decoded_token.get('name')
            picture = decoded_token.get('picture')
            
            if not firebase_uid:
                return Response({
                    "success": False,
                    "error": "Token invalide",
                    "detail": "UID Firebase manquant dans le token"
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # Déterminer le mode d'authentification et extraire les identifiants
            auth_method = 'phone_sms'  # Par défaut
            extracted_phone = None
            
            if phone_number:
                # Mode SMS : numéro directement dans le token
                auth_method = 'phone_sms'
                extracted_phone = phone_number
            elif email:
                # Vérifier si c'est un email simulé (mode phone_password)
                simulated_phone = extract_phone_from_email(email)
                if simulated_phone:
                    auth_method = 'phone_password'
                    extracted_phone = simulated_phone
                else:
                    # Email réel (Google OAuth)
                    auth_method = 'google'
            
            # Respecter le hint du frontend si cohérent
            if auth_method_hint and auth_method_hint in ['phone_sms', 'phone_password', 'google']:
                # Ne remplacer que si c'est cohérent avec les données
                if auth_method_hint == 'google' and email and not email.endswith('@farecalc.phone'):
                    auth_method = 'google'
                elif auth_method_hint == 'phone_password' and extracted_phone:
                    auth_method = 'phone_password'
            
            # Créer ou récupérer l'utilisateur
            user, is_new_user = MobileUser.objects.get_or_create(
                firebase_uid=firebase_uid,
                defaults={
                    'phone_number': extracted_phone,
                    'email': email if auth_method == 'google' else None,
                    'display_name': name,
                    'photo_url': picture,
                    'auth_method': auth_method,
                }
            )
            
            # Vérifier si l'utilisateur est actif
            if not user.is_active:
                return Response({
                    "success": False,
                    "error": "Compte désactivé",
                    "detail": "Votre compte a été désactivé. Contactez le support."
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Mettre à jour les informations si elles ont changé
            fields_to_update = []
            
            if extracted_phone and user.phone_number != extracted_phone:
                user.phone_number = extracted_phone
                fields_to_update.append('phone_number')
            
            if auth_method == 'google' and email and user.email != email:
                user.email = email
                fields_to_update.append('email')
            
            if name and user.display_name != name:
                user.display_name = name
                fields_to_update.append('display_name')
            
            if picture and user.photo_url != picture:
                user.photo_url = picture
                fields_to_update.append('photo_url')
            
            if user.auth_method != auth_method:
                user.auth_method = auth_method
                fields_to_update.append('auth_method')
            
            if fields_to_update:
                user.save(update_fields=fields_to_update)
            
            # Mettre à jour last_login
            user.update_last_login()
            
            identifier = extracted_phone or email or firebase_uid[:8]
            logger.info(
                f"Utilisateur mobile authentifié ({auth_method}): {identifier} "
                f"(UID: {firebase_uid}, nouveau: {is_new_user})"
            )
            
            return Response({
                "success": True,
                "message": "Bienvenue !" if is_new_user else "Connexion réussie",
                "user": MobileUserSerializer(user).data,
                "is_new_user": is_new_user
            }, status=status.HTTP_200_OK)
            
        except ValueError as e:
            # Firebase non configuré
            logger.error(f"Firebase Admin SDK non configuré: {e}")
            return Response({
                "success": False,
                "error": "Configuration serveur",
                "detail": "Le serveur n'est pas correctement configuré pour l'authentification Firebase. "
                          "Contactez l'administrateur."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.exception(f"Erreur lors de la vérification du token Firebase: {e}")
            return Response({
                "success": False,
                "error": "Erreur serveur",
                "detail": str(e) if logger.isEnabledFor(logging.DEBUG) else "Une erreur est survenue"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FirebaseUserMeView(APIView):
    """
    Retourne les informations de l'utilisateur connecté.
    
    Cette vue nécessite un token Firebase valide dans le header Authorization.
    Format : Authorization: Bearer <firebase_id_token>
    
    Note : Cette route est séparée du middleware ApiKey car elle utilise
    l'authentification Firebase Bearer au lieu de ApiKey.
    """
    
    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=MobileUserSerializer,
                description="Informations utilisateur"
            ),
            401: OpenApiResponse(description="Token manquant ou invalide"),
            404: OpenApiResponse(description="Utilisateur non trouvé")
        },
        summary="Obtenir profil utilisateur",
        description="Retourne les informations de l'utilisateur mobile connecté",
        tags=["Authentification Mobile"]
    )
    def get(self, request):
        # Extraire le token Bearer
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return Response({
                "success": False,
                "error": "Token manquant",
                "detail": "Header Authorization avec Bearer token requis"
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        id_token = auth_header.replace('Bearer ', '')
        
        try:
            # Vérifier le token
            decoded_token = verify_firebase_token(id_token)
            
            if decoded_token is None:
                return Response({
                    "success": False,
                    "error": "Token invalide",
                    "detail": "Le token Firebase est invalide, expiré ou révoqué"
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            firebase_uid = decoded_token.get('uid')
            
            # Récupérer l'utilisateur
            try:
                user = MobileUser.objects.get(firebase_uid=firebase_uid)
            except MobileUser.DoesNotExist:
                return Response({
                    "success": False,
                    "error": "Utilisateur non trouvé",
                    "detail": "Aucun compte trouvé pour ce token. Connectez-vous d'abord via /api/auth/verify-token/"
                }, status=status.HTTP_404_NOT_FOUND)
            
            if not user.is_active:
                return Response({
                    "success": False,
                    "error": "Compte désactivé",
                    "detail": "Votre compte a été désactivé"
                }, status=status.HTTP_403_FORBIDDEN)
            
            return Response({
                "success": True,
                "user": MobileUserSerializer(user).data
            }, status=status.HTTP_200_OK)
            
        except ValueError as e:
            return Response({
                "success": False,
                "error": "Configuration serveur",
                "detail": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.exception(f"Erreur lors de la récupération du profil: {e}")
            return Response({
                "success": False,
                "error": "Erreur serveur",
                "detail": "Une erreur est survenue"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FirebaseUserUpdateView(APIView):
    """
    Met à jour le profil de l'utilisateur mobile connecté.
    
    Permet de modifier le display_name uniquement.
    Nécessite un token Firebase valide.
    """
    
    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"display_name": {"type": "string"}}}},
        responses={
            200: OpenApiResponse(
                response=MobileUserSerializer,
                description="Profil mis à jour"
            ),
            401: OpenApiResponse(description="Token manquant ou invalide"),
            404: OpenApiResponse(description="Utilisateur non trouvé")
        },
        summary="Mettre à jour profil",
        description="Met à jour le nom d'affichage de l'utilisateur mobile",
        tags=["Authentification Mobile"]
    )
    def patch(self, request):
        # Extraire et vérifier le token
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return Response({
                "success": False,
                "error": "Token manquant",
                "detail": "Header Authorization avec Bearer token requis"
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        id_token = auth_header.replace('Bearer ', '')
        
        try:
            decoded_token = verify_firebase_token(id_token)
            
            if decoded_token is None:
                return Response({
                    "success": False,
                    "error": "Token invalide",
                    "detail": "Le token Firebase est invalide ou expiré"
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            firebase_uid = decoded_token.get('uid')
            
            try:
                user = MobileUser.objects.get(firebase_uid=firebase_uid)
            except MobileUser.DoesNotExist:
                return Response({
                    "success": False,
                    "error": "Utilisateur non trouvé",
                    "detail": "Aucun compte trouvé pour ce token"
                }, status=status.HTTP_404_NOT_FOUND)
            
            if not user.is_active:
                return Response({
                    "success": False,
                    "error": "Compte désactivé"
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Mettre à jour display_name si fourni
            display_name = request.data.get('display_name')
            if display_name is not None:
                user.display_name = display_name
                user.save(update_fields=['display_name'])
            
            return Response({
                "success": True,
                "message": "Profil mis à jour",
                "user": MobileUserSerializer(user).data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.exception(f"Erreur lors de la mise à jour du profil: {e}")
            return Response({
                "success": False,
                "error": "Erreur serveur",
                "detail": "Une erreur est survenue"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
