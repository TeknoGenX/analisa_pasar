# config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url
from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Muat variabel environment dari .env
load_dotenv(os.path.join(BASE_DIR, '.env'))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'default-unsafe-key')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if h.strip()]
if DEBUG and 'testserver' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('testserver')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Aplikasi Modular Proyek Analisa Pasar
    'data_ingestion',
    'technical_indicators',
    'trading_dashboard',
    'paper_trading',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Direktori template global jika diperlukan
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database Setup (PostgreSQL via Neon)
# Menggunakan connection pooling (conn_max_age) untuk efisiensi
#DATABASES = {
#    'default': dj_database_url.config(
#        default=os.environ.get('DATABASE_URL'),
#        conn_max_age=600,
#        conn_health_checks=True,
#    )
#}
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 60,
        },
    }
}

# Redis Caching Setup
# Digunakan untuk menyimpan hasil kalkulasi Pandas agar dashboard tidak berat
import sys
if 'test' in sys.argv:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-cache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': f"{os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379')}/1",
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'id-id'
TIME_ZONE = 'Asia/Jakarta' # Sangat penting untuk akurasi timestamp pasar
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==========================================
# CELERY & REDIS CONFIGURATION
# ==========================================
CELERY_BROKER_URL = f"{os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379')}/0"
CELERY_RESULT_BACKEND = f"{os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379')}/0"
CELERY_ACCEPT_CONTENT = ['application/json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Jadwal Penarikan Data (Cron Job via Celery Beat)
CELERY_BEAT_SCHEDULE = {
    'tarik-data-1m-tiap-2-menit': {
        'task': 'data_ingestion.tasks.fetch_market_prices',
        'schedule': crontab(minute='*/2'), # Eksekusi setiap 2 menit untuk data 1m
        'kwargs': {'timeframe': '1m'},
    },
    'tarik-data-5m-tiap-5-menit': {
        'task': 'data_ingestion.tasks.fetch_market_prices',
        'schedule': crontab(minute='*/5'), # Eksekusi setiap 5 menit untuk data 5m
        'kwargs': {'timeframe': '5m'},
    },
    'tarik-data-15m-tiap-15-menit': {
        'task': 'data_ingestion.tasks.fetch_market_prices',
        'schedule': crontab(minute='*/15'), # Eksekusi setiap 15 menit untuk data 15m
        'kwargs': {'timeframe': '15m'},
    },
    'tarik-data-30m-tiap-30-menit': {
        'task': 'data_ingestion.tasks.fetch_market_prices',
        'schedule': crontab(minute='*/30'), # Eksekusi setiap 30 menit untuk data 30m
        'kwargs': {'timeframe': '30m'},
    },
    'tarik-data-1h-tiap-jam': {
        'task': 'data_ingestion.tasks.fetch_market_prices',
        'schedule': crontab(minute=0, hour='*'), # Eksekusi setiap jam untuk data 1h
        'kwargs': {'timeframe': '1h'},
    },
    'tarik-data-1d-tiap-4-jam': {
        'task': 'data_ingestion.tasks.fetch_market_prices',
        'schedule': crontab(minute=0, hour='*/4'), # Eksekusi setiap 4 jam untuk data 1d
        'kwargs': {'timeframe': '1d'},
    },
    'tarik-data-1wk-tiap-hari': {
        'task': 'data_ingestion.tasks.fetch_market_prices',
        'schedule': crontab(minute=30, hour=0), # Eksekusi setiap hari jam 00:30 untuk data 1wk
        'kwargs': {'timeframe': '1wk'},
    },
}

# Penarikan Otomatis IQ Option Traderoom (jika kredensial dikonfigurasi di .env)
if os.environ.get('IQOPTION_SSID') or (os.environ.get('IQOPTION_EMAIL') and os.environ.get('IQOPTION_PASSWORD')):
    CELERY_BEAT_SCHEDULE['tarik-iqoption-1m-tiap-2-menit'] = {
        'task': 'data_ingestion.tasks.fetch_iqoption_prices',
        'schedule': crontab(minute='*/2'),
        'kwargs': {'timeframe': '1m'},
    }

# ==========================================
# LOGGING CONFIGURATION
# ==========================================
# Logika ini membantu melacak error Pandas atau Celery di terminal
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'data_ingestion': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'technical_indicators': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'yfinance': {
            'handlers': ['console'],
            'level': 'CRITICAL',
            'propagate': False,
        },
    },
}