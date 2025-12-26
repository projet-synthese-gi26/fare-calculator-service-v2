import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fare_calculator.settings')

app = Celery('fare_calculator')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()