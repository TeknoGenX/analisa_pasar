# config/celery.py
import os
from celery import Celery

# Set modul settings Django sebagai referensi environment untuk Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Inisialisasi aplikasi Celery dengan nama proyek
app = Celery('analisa_pasar')

# Baca semua konfigurasi yang berawalan 'CELERY_' dari settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

# Deteksi otomatis tasks.py di semua aplikasi yang terdaftar di INSTALLED_APPS
app.autodiscover_tasks()

import logging
from celery.signals import after_setup_logger, after_setup_task_logger

@after_setup_logger.connect
@after_setup_task_logger.connect
def setup_celery_loggers(logger, *args, **kwargs):
    # Bungkam pesan error gagal unduh / delisted dari library yfinance di terminal worker
    logging.getLogger('yfinance').setLevel(logging.CRITICAL)

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')