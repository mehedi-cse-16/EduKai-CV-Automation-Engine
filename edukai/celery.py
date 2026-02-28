import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edukai.settings")

app = Celery("edukai")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks from all installed apps
app.autodiscover_tasks()