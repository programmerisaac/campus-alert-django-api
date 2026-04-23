# campusalert/website/celery.py

"""
Celery application for CampusAlert.

Workers are started with:
    celery -A website worker -l info -c 4

Beat scheduler (for periodic tasks, if needed):
    celery -A website beat -l info
"""

import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'website.settings')

app = Celery('campusalert')

# Use Django settings prefixed with CELERY_ for all Celery config
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all INSTALLED_APPS
app.autodiscover_tasks()
