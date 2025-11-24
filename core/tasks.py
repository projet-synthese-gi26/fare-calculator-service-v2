"""
Tâches Celery asynchrones pour le projet d'estimation prix taxi.

Tâches principales :
- daily_train_ml_model : Entraînement quotidien du modèle ML sur tous trajets BD
- update_popular_isochrones : Pré-génération isochrones POI populaires (cache)
- cleanup_old_cache : Nettoyage cache expiré (Redis)
- send_stats_report : Envoi rapport stats hebdomadaire admin (optionnel)

Configuration beat schedule (dans settings.py ou ici) :
    from celery.schedules import crontab
    
    app.conf.beat_schedule = {
        'train-ml-daily': {
            'task': 'core.tasks.daily_train_ml_model',
            'schedule': crontab(hour=2, minute=0),  # Tous les jours à 2h du matin
        },
        'update-isochrones-weekly': {
            'task': 'core.tasks.update_popular_isochrones',
            'schedule': crontab(day_of_week=1, hour=3, minute=0),  # Lundis à 3h
        },
    }
"""

from celery import shared_task
from django.utils import timezone
from django.db.models import Avg, Count
import logging
from datetime import timedelta
from typing import Optional, Dict

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def daily_train_ml_model(self) -> Dict[str, any]:
    """
    Entraîne quotidiennement le modèle ML de prédiction prix sur tous trajets BD.
    
    **TÂCHE CŒUR ML - ÉQUIPE IMPLÉMENTE LOGIQUE COMPLÈTE**
    
    Workflow :
        1. Query tous trajets BD avec features complètes (Trajet.objects.all())
        2. Filtrer trajets valides (prix > 0, distance > 0, pas de nulls critiques)
        3. Préparer DataFrame pandas :
            - Features : distance, heure_encoded, meteo, type_zone, congestion_moyen, 
                        sinuosite_indice, nb_virages, jour_semaine
            - Target : prix
        4. Gérer valeurs manquantes :
            - Congestion null -> remplacer par médiane ou 50 (urbaine default)
            - Sinuosité null -> remplacer par 1.5 (moyenne)
            - Autres nulls -> imputer via SimpleImputer (median strategy)
        5. Encoder variables catégoriques :
            - heure : mapping {'matin': 0, 'apres-midi': 1, 'soir': 2, 'nuit': 3}
            - jour_semaine : extraire de date_ajout (datetime.weekday())
        6. Normaliser features (StandardScaler) :
            - Sauvegarder scaler pour usage prediction
        7. Split train/test (80/20 ou 70/30, random_state=42 pour reproducibilité)
        8. Entraîner modèle :
            - Modèle suggéré : RandomForestRegressor(n_estimators=100, max_depth=20, random_state=42)
            - Alternatives : GradientBoostingRegressor, XGBRegressor (si XGBoost installé)
        9. Évaluer sur test set :
            - Métriques : MAE (Mean Absolute Error), RMSE, R² (coefficient détermination)
            - Logger métriques : logger.info(f"MAE: {mae}, RMSE: {rmse}, R²: {r2}")
        10. Si R² > seuil (ex. 0.6), sauvegarder modèle + scaler via joblib :
            - joblib.dump(model, 'ml_models/prix_model.pkl')
            - joblib.dump(scaler, 'ml_models/prix_scaler.pkl')
            - Sauvegarder metadata : date entraînement, nb trajets, métriques (JSON)
        11. Si R² < seuil, logger warning "Pas assez de données, modèle non sauvegardé"
        12. Nettoyer ancien modèle si existe (archiver avec timestamp)
        13. Return dict avec résultats (pour logs Celery)
        
    Args:
        self : Task Celery (bind=True pour retry)
        
    Returns:
        Dict : {
            'status': 'success' ou 'failed',
            'nb_trajets': int,
            'metrics': {'mae': float, 'rmse': float, 'r2': float},
            'model_saved': bool,
            'timestamp': str ISO
        }
        
    Exemples usage :
        # Appel manuel (admin shell ou Celery beat automatique)
        >>> from core.tasks import daily_train_ml_model
        >>> result = daily_train_ml_model.delay()  # Asynchrone
        >>> result.get()  # Attendre résultat
        {
            'status': 'success',
            'nb_trajets': 150,
            'metrics': {'mae': 25.3, 'rmse': 35.7, 'r2': 0.78},
            'model_saved': True,
            'timestamp': '2023-11-05T02:00:00Z'
        }
        
    Gestion erreurs :
        - Si <50 trajets en BD, skip entraînement (pas assez données)
        - Si exception durant entraînement (ex. features corrompues), retry max 3 fois
        - Si échec final, logger.error et return {'status': 'failed', 'error': str(e)}
        
    Note performance :
        - Avec 100 trajets : entraînement ~5-10s
        - Avec 1000 trajets : ~30-60s
        - Avec 10000+ : considérer optimisations (batch, feature selection)
        - Task exécutée à 2h du matin pour éviter charge serveur heures pointe
        
    Configuration beat (dans settings.py CELERY_BEAT_SCHEDULE) :
        'train-ml-daily': {
            'task': 'core.tasks.daily_train_ml_model',
            'schedule': crontab(hour=2, minute=0),
        }
    """
    # TODO : ÉQUIPE IMPLÉMENTE ENTRAÎNEMENT ML COMPLET
    # TODO : Imports : pandas, scikit-learn (RandomForestRegressor, StandardScaler, train_test_split, metrics), joblib
    # TODO : Query Trajet.objects.all().values(...) -> DataFrame
    # TODO : Preprocessing : encoder heure, imputer nulls, normaliser
    # TODO : Train/test split, entraînement, évaluation
    # TODO : Sauvegarder modèle si R² > 0.6
    # TODO : Return dict résultats
    
    logger.info("Début entraînement quotidien modèle ML...")
    
    try:
        # Placeholder : Query nombre trajets pour exemple
        from core.models import Trajet
        nb_trajets = Trajet.objects.count()
        
        if nb_trajets < 50:
            logger.warning(f"Pas assez de trajets ({nb_trajets}) pour entraîner modèle ML. Minimum 50.")
            return {
                'status': 'skipped',
                'reason': 'insufficient_data',
                'nb_trajets': nb_trajets,
                'timestamp': timezone.now().isoformat()
            }
        
        # TODO : Implémenter logique complète ici
        
        logger.info(f"Entraînement ML simulé avec {nb_trajets} trajets (TODO équipe : implémenter)")
        return {
            'status': 'success',
            'nb_trajets': nb_trajets,
            'metrics': {'mae': 0.0, 'rmse': 0.0, 'r2': 0.0},  # Placeholder
            'model_saved': False,
            'note': 'TODO équipe : logique ML à implémenter',
            'timestamp': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Erreur entraînement ML : {e}")
        # Retry si échec (max 3 fois)
        raise self.retry(exc=e, countdown=60)  # Retry après 1 min


@shared_task
def update_popular_isochrones() -> Dict[str, any]:
    """
    Pré-génère et cache isochrones pour POI populaires Yaoundé.
    
    Objectif : Optimiser check_similar_match en précalculant isochrones des points les plus fréquents.
    Au lieu de calculer isochrone à chaque requête estimation, on les stocke en cache (Redis ou BD).
    
    Workflow :
        1. Identifier POI populaires :
            - Query Points utilisés dans plus de X trajets (ex. X=10)
            - Point.objects.annotate(nb_trajets=Count('trajets_depart') + Count('trajets_arrivee')).filter(nb_trajets__gte=10)
        2. Pour chaque POI populaire :
            a. Appeler Mapbox Isochrone API (contours 2min et 5min)
            b. Stocker GeoJSON polygones en cache Redis (clé : f'isochrone:{point.id}:2min')
            c. TTL cache : 7 jours (isochrones changent peu)
        3. Logger nombre POI traités, échecs Mapbox éventuels
        4. Return stats {'nb_poi': int, 'nb_success': int, 'nb_failed': int}
        
    Args:
        Aucun
        
    Returns:
        Dict : Stats mise à jour isochrones
        
    Exemples :
        # Exécution manuelle ou via beat (hebdomadaire)
        >>> from core.tasks import update_popular_isochrones
        >>> update_popular_isochrones.delay()
        
    Configuration beat :
        'update-isochrones-weekly': {
            'task': 'core.tasks.update_popular_isochrones',
            'schedule': crontab(day_of_week=1, hour=3, minute=0),  # Lundis 3h
        }
    """
    # TODO : Équipe implémente pré-génération isochrones
    # TODO : Query POI populaires, appeler Mapbox Isochrone, cacher Redis
    
    logger.info("Mise à jour isochrones POI populaires (TODO équipe : implémenter)...")
    
    return {
        'status': 'success',
        'nb_poi': 0,
        'nb_success': 0,
        'nb_failed': 0,
        'note': 'TODO équipe : logique isochrones à implémenter',
        'timestamp': timezone.now().isoformat()
    }


@shared_task
def cleanup_old_cache() -> Dict[str, any]:
    """
    Nettoie cache Redis expiré manuellement (si nécessaire).
    
    Redis gère automatiquement expiration via TTL, mais cette tâche peut forcer nettoyage
    de clés orphelines ou optimiser mémoire.
    
    Workflow :
        1. Connecter à Redis via Django cache
        2. Scanner clés avec patterns (ex. 'mapbox:*', 'nominatim:*')
        3. Supprimer clés > 7 jours sans accès
        4. Logger stats nettoyage
        
    Returns:
        Dict : {'keys_deleted': int}
    """
    # TODO : Équipe implémente si nécessaire (optionnel)
    logger.info("Nettoyage cache (TODO optionnel)")
    return {'keys_deleted': 0, 'note': 'Optionnel, Redis auto-gère TTL'}


@shared_task
def send_stats_report() -> Dict[str, any]:
    """
    Envoie rapport stats hebdomadaire à admin (optionnel).
    
    Contenu rapport :
        - Nombre trajets ajoutés semaine dernière
        - Prix moyen, répartition par heure/météo/zone
        - Nombre requêtes estimation, taux success
        - Métriques ML (si modèle entraîné)
        
    Envoi : Email admin ou webhook (ex. Slack)
    
    Returns:
        Dict : {'status': 'sent' ou 'failed'}
    """
    # TODO : Équipe implémente si besoin (optionnel, hors scope initial)
    logger.info("Envoi rapport stats (TODO optionnel)")
    return {'status': 'skipped', 'note': 'Optionnel, hors scope initial'}
