# campusalert/website/settings.py

import os
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent


env = environ.Env(
    DEBUG=(bool, False),
    LOG_LEVEL=(str, 'INFO'),
    JWT_ACCESS_TOKEN_LIFETIME_MINUTES=(int, 60),
    JWT_REFRESH_TOKEN_LIFETIME_DAYS=(int, 7),
    # OLD: COVENANT_EMAIL_DOMAIN=(str, 'covenantuniversity.edu.ng'),
    # NEW: Two domains — staff and students use different email formats
    COVENANT_STUDENT_EMAIL_DOMAIN=(str, 'stu.cu.edu.ng'),
    COVENANT_STAFF_EMAIL_DOMAIN=(str, 'covenantuniversity.edu.ng'),
)
environ.Env.read_env(BASE_DIR / '.env')



SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# ─── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'axes',
    'django_filters',

    # Project apps
    'core.apps.CoreConfig',
    'accounts.apps.AccountsConfig',
    'alerts.apps.AlertsConfig',
    'ml.apps.MlConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # django-axes must be after AuthenticationMiddleware
    'axes.middleware.AxesMiddleware',
]

ROOT_URLCONF = 'website.urls'
WSGI_APPLICATION = 'website.wsgi.application'
ASGI_APPLICATION = 'website.asgi.application'

AUTH_USER_MODEL = 'accounts.User'

# ─── Templates ────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    'default': env.db('DATABASE_URL'),
}
DATABASES['default']['OPTIONS'] = {'connect_timeout': 10}

# ─── Redis & Cache ────────────────────────────────────────────────────────────
REDIS_URL = env('REDIS_URL', default='redis://localhost:6379/0')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
        'TIMEOUT': 300,
    }
}

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# ─── Celery ───────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft limit

# ─── Authentication ───────────────────────────────────────────────────────────
AUTHENTICATION_BACKENDS = [
    # django-axes MUST be first — it intercepts failed logins to enforce
    # brute-force lockout before any real authentication happens.
    'axes.backends.AxesStandaloneBackend',

    # Our custom email-based backend — checks email + password.
    # This runs second (after axes approves the attempt).
    'accounts.backends.EmailAuthBackend',

    # Django's default backend — kept as fallback for:
    # - Admin site login (admin users may use username)
    # - Management commands that call authenticate()
    # - Any code that passes 'username' explicitly
    'django.contrib.auth.backends.ModelBackend',
]




AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── Django REST Framework ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/minute',
        'user': '100/minute',
    },
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
}

# ─── JWT ──────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env('JWT_ACCESS_TOKEN_LIFETIME_MINUTES')),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env('JWT_REFRESH_TOKEN_LIFETIME_DAYS')),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Flutter mobile app communicates from a native context; CORS is still needed
# for web-based admin interfaces and during development.
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Restrict in production
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
CORS_ALLOW_CREDENTIALS = True


# ─── Covenant University Domains ──────────────────────────────────────────────
# Staff  emails:   firstname.lastname@covenantuniversity.edu.ng
# Student emails:  firstname.lastname@stu.cu.edu.ng
#
# Both domains are valid for login. The domain also determines the role
# assigned during registration (staff vs student auto-detection).
COVENANT_STAFF_EMAIL_DOMAIN = env('COVENANT_STAFF_EMAIL_DOMAIN')
COVENANT_STUDENT_EMAIL_DOMAIN = env('COVENANT_STUDENT_EMAIL_DOMAIN')

# Convenience list — used in serializer validation
COVENANT_ALLOWED_EMAIL_DOMAINS = [
    COVENANT_STAFF_EMAIL_DOMAIN,    # covenantuniversity.edu.ng
    COVENANT_STUDENT_EMAIL_DOMAIN,  # stu.cu.edu.ng
]

# ─── django-axes (Brute Force Protection) ─────────────────────────────────────
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
# OLD: AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']
# NEW: Lock by email instead of username since we switched to email login
AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']  # axes uses 'username' field internally
AXES_RESET_ON_SUCCESS = True
AXES_HANDLER = 'axes.handlers.cache.AxesCacheHandler'
AXES_CACHE = 'default'


# ─── Firebase / FCM ───────────────────────────────────────────────────────────
FCM_PROJECT_ID = env('FCM_PROJECT_ID', default='')
FCM_SERVICE_ACCOUNT_JSON_PATH = env('FCM_SERVICE_ACCOUNT_JSON_PATH', default='')


# ─── ML Model Paths ───────────────────────────────────────────────────────────
ML_MODEL_PATH = BASE_DIR / 'ml' / 'model.pkl'
ML_VECTORIZER_PATH = BASE_DIR / 'ml' / 'vectorizer.pkl'

# ─── Internationalisation ─────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

# ─── Static & Media ───────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static'
STATICFILES_DIRS = [
    BASE_DIR / 'website/static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = env('LOG_LEVEL')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {process:d} {thread:d} — {message}',
            'style': '{',
        },
        'simple': {
            'format': '[{asctime}] {levelname} {name} — {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'campusalert': {
            'handlers': ['console', 'file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}




