import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
SECRET_KEY = os.environ.get('SECRET_KEY', 'local-development-key-set-a-real-secret-for-production')
DEBUG = os.environ.get('DEBUG', '0') == '1'
WECHAT_APP_ID = os.environ.get('WECHAT_APP_ID', 'wxf278ca432c9e7224')
WECHAT_APP_SECRET = os.environ.get('WECHAT_APP_SECRET', '')
if os.environ.get('ADC_ENV')=='production' and (len(SECRET_KEY)<40 or 'REPLACE_' in SECRET_KEY or SECRET_KEY.startswith('local-development')):
    raise RuntimeError('生产环境必须设置独立的高强度SECRET_KEY，请使用scripts/create-env.py')
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
ROOT_URLCONF = 'adc.urls'
WSGI_APPLICATION = 'adc.wsgi.application'
INSTALLED_APPS = []
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'core.http.ApiMiddleware']
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': os.environ.get('POSTGRES_DB', 'adc'),
    'USER': os.environ.get('POSTGRES_USER', 'adc'), 'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
    'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'), 'PORT': os.environ.get('POSTGRES_PORT', '55432'), 'CONN_MAX_AGE': 60}}
TIME_ZONE = 'Asia/Shanghai'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', '0') == '1'
CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',')
CONTRACTS_DIR = Path(os.environ.get('CONTRACTS_DIR', str(BASE_DIR.parent / 'contracts')))
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
LOGGING = {'version': 1, 'disable_existing_loggers': False, 'handlers': {'console': {'class': 'logging.StreamHandler'}},
           'root': {'handlers': ['console'], 'level': 'INFO'}}
