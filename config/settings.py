from pathlib import Path
import os
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if DB_ENGINE == 'postgresql' and not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set for PostgreSQL deployment.')
    SECRET_KEY = 'local-study-project-do-not-use-in-production'
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost,[::1],testserver').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if v.strip()]
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'monitor']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[], 'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
if DB_ENGINE == 'postgresql':
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'monitor'),
        'USER': os.environ.get('POSTGRES_APP_USER', 'monitor_app'),
        'PASSWORD': os.environ.get('POSTGRES_APP_PASSWORD', ''),
        'HOST': os.environ.get('POSTGRES_HOST', 'db'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {'connect_timeout': 5},
    }}
elif DB_ENGINE == 'sqlite':
    DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('MONITOR_DB',str(BASE_DIR/'db.sqlite3')),'OPTIONS':{'timeout':30}}}
else:
    raise ImproperlyConfigured('DB_ENGINE must be sqlite or postgresql.')
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR/'staticfiles'
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
MEDIA_ROOT = Path(os.environ.get('MONITOR_MEDIA_ROOT', str(BASE_DIR/'data')))
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 25*1024*1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2*1024*1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_SECURE = os.environ.get('DJANGO_COOKIE_SECURE', '0') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SSL_REDIRECT', '0') == '1'
SECURE_REDIRECT_EXEMPT = [r'^healthz/$']
if os.environ.get('DJANGO_TRUST_PROXY_SSL', '0') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
X_FRAME_OPTIONS = 'DENY'
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
LOGGING = {'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO')},
    'loggers': {'django': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO'), 'propagate': False}}}
