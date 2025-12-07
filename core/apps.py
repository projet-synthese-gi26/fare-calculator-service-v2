from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    
    def ready(self):
        # Initialisation du prédicteur ML au démarrage
        # Import local pour éviter les problèmes de chargement circulaire
        # from .ml.predictor import TaxiFarePredictor
        from .ml.classifier_predictor import TaxiFareClassifierPredictor
        global taxi_predictor
        # taxi_predictor = TaxiFarePredictor()
        taxi_predictor = TaxiFareClassifierPredictor()
