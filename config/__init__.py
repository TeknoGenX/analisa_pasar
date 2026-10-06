# config/__init__.py
from .celery import app as celery_app

# Mengekspos celery_app agar bisa diakses oleh proyek
__all__ = ('celery_app',)