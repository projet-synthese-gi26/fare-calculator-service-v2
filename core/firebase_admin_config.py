"""
Configuration Firebase Admin SDK pour la vérification des tokens côté backend.

Ce module initialise Firebase Admin SDK une seule fois au démarrage.
Il fournit des fonctions pour vérifier les ID Tokens Firebase et extraire
les informations utilisateur (UID, numéro de téléphone).

Configuration :
    Option 1 (Recommandée pour production) : Variable d'environnement GOOGLE_APPLICATION_CREDENTIALS
        - Télécharger le fichier JSON de clé de service depuis Firebase Console
        - Définir GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
        
    Option 2 (Développement) : Définir les variables dans .env
        - FIREBASE_PROJECT_ID=your-project-id
        - FIREBASE_PRIVATE_KEY=your-private-key
        - FIREBASE_CLIENT_EMAIL=your-client-email

IMPORTANT : Ne jamais commiter les clés de service dans Git !
"""

import os
import logging
from typing import Optional, Dict, Any
import firebase_admin
from firebase_admin import credentials, auth
from django.conf import settings

logger = logging.getLogger(__name__)

# Flag pour éviter la réinitialisation
_firebase_initialized = False


def initialize_firebase() -> bool:
    """
    Initialise Firebase Admin SDK si pas déjà fait.
    
    Returns:
        bool: True si initialisé avec succès, False sinon.
    """
    global _firebase_initialized
    
    # Vérifier si déjà initialisé via le flag
    if _firebase_initialized:
        return True
    
    # Vérifier si l'app par défaut existe déjà (cas multi-thread/multi-process)
    try:
        firebase_admin.get_app()
        logger.debug("Firebase Admin SDK déjà initialisé (app existante)")
        _firebase_initialized = True
        return True
    except ValueError:
        # L'app n'existe pas encore, on continue l'initialisation
        pass
    
    try:
        # Option 1 : Fichier de credentials via variable d'environnement
        # (Google Cloud gère automatiquement GOOGLE_APPLICATION_CREDENTIALS)
        if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialisé via GOOGLE_APPLICATION_CREDENTIALS")
            _firebase_initialized = True
            return True
        
        # Option 2 : Credentials depuis settings/env
        project_id = getattr(settings, 'FIREBASE_PROJECT_ID', None) or os.environ.get('FIREBASE_PROJECT_ID')
        private_key = getattr(settings, 'FIREBASE_PRIVATE_KEY', None) or os.environ.get('FIREBASE_PRIVATE_KEY')
        client_email = getattr(settings, 'FIREBASE_CLIENT_EMAIL', None) or os.environ.get('FIREBASE_CLIENT_EMAIL')
        
        if project_id and private_key and client_email:
            # Remplacer \\n par \n si nécessaire (quand la clé est dans une variable d'env)
            if '\\n' in private_key:
                private_key = private_key.replace('\\n', '\n')
            
            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": project_id,
                "private_key": private_key,
                "client_email": client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            })
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialisé via variables d'environnement")
            _firebase_initialized = True
            return True
        
        # Option 3 : Mode développement sans credentials (certaines fonctions limitées)
        # Dans ce cas, on peut initialiser sans credentials pour le projet ID depuis env
        if project_id:
            firebase_admin.initialize_app(options={'projectId': project_id})
            logger.warning(
                "Firebase Admin SDK initialisé en mode limité (projectId seulement). "
                "La vérification des tokens peut ne pas fonctionner."
            )
            _firebase_initialized = True
            return True
        
        logger.error(
            "Impossible d'initialiser Firebase Admin SDK. "
            "Définissez GOOGLE_APPLICATION_CREDENTIALS ou FIREBASE_PROJECT_ID/PRIVATE_KEY/CLIENT_EMAIL"
        )
        return False
        
    except Exception as e:
        logger.exception(f"Erreur lors de l'initialisation Firebase Admin SDK: {e}")
        return False


def verify_firebase_token(id_token: str) -> Optional[Dict[str, Any]]:
    """
    Vérifie un ID Token Firebase et retourne les informations utilisateur.
    
    Args:
        id_token: Le token JWT Firebase à vérifier
        
    Returns:
        Dict contenant les claims du token si valide:
            {
                'uid': 'abc123...',
                'phone_number': '+237699999999',
                'firebase': {...},
                ...
            }
        None si le token est invalide ou expiré.
        
    Raises:
        ValueError: Si Firebase n'est pas initialisé
    """
    if not initialize_firebase():
        logger.error("Firebase Admin SDK non initialisé, impossible de vérifier le token")
        raise ValueError("Firebase Admin SDK non initialisé")
    
    try:
        # Vérifier le token avec Firebase Admin SDK
        decoded_token = auth.verify_id_token(id_token)
        
        logger.info(f"Token Firebase vérifié avec succès pour UID: {decoded_token.get('uid')}")
        return decoded_token
        
    except auth.ExpiredIdTokenError:
        logger.warning("Token Firebase expiré")
        return None
        
    except auth.RevokedIdTokenError:
        logger.warning("Token Firebase révoqué")
        return None
        
    except auth.InvalidIdTokenError as e:
        logger.warning(f"Token Firebase invalide: {e}")
        return None
        
    except Exception as e:
        logger.exception(f"Erreur lors de la vérification du token Firebase: {e}")
        return None


def get_firebase_user(uid: str) -> Optional[auth.UserRecord]:
    """
    Récupère les informations complètes d'un utilisateur Firebase par son UID.
    
    Args:
        uid: L'UID Firebase de l'utilisateur
        
    Returns:
        UserRecord Firebase si trouvé, None sinon.
    """
    if not initialize_firebase():
        raise ValueError("Firebase Admin SDK non initialisé")
    
    try:
        user = auth.get_user(uid)
        return user
    except auth.UserNotFoundError:
        logger.warning(f"Utilisateur Firebase non trouvé: {uid}")
        return None
    except Exception as e:
        logger.exception(f"Erreur lors de la récupération de l'utilisateur Firebase: {e}")
        return None
