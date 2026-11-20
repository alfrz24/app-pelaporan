"""
Django settings for config project.
Sistem Pelaporan Bulanan - Sudin Kominfotik Kota Administrasi Jakarta Pusat
"""

from pathlib import Path
import socket
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# Untuk produksi, set environment variable DJANGO_SECRET_KEY (nilai bawaan hanya untuk pengembangan).
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-8-17$^0a$%l5k@o%f)ec*cq8=h_xv-*9=xt7%s_6+%z&-+%z8+'
)

# SECURITY WARNING: don't run with debug turned on in production!
# Produksi: set DJANGO_DEBUG=0 dan DJANGO_ALLOWED_HOSTS=domain1,domain2
DEBUG = os.environ.get('DJANGO_DEBUG', '0' if os.environ.get('VERCEL') else '1') == '1'

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',') if h.strip()]

# Sesi & cookie
SESSION_COOKIE_AGE = 60 * 60 * 8        # login otomatis berakhir setelah 8 jam
SESSION_COOKIE_HTTPONLY = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'laporan',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
        'DIRS': [
            BASE_DIR / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.media',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# =====================================================================
# Database
#   1. DATABASE_URL (produksi / Vercel)  -> mis. PostgreSQL Neon / Supabase
#   2. MariaDB lokal port 3307 (XAMPP)   -> bila aktif
#   3. SQLite                            -> cadangan pengembangan
# =====================================================================
IS_VERCEL = bool(os.environ.get('VERCEL'))
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL')


def check_mysql_socket(host='127.0.0.1', port=3307, timeout=0.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


if DATABASE_URL:
    import dj_database_url
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=60, ssl_require=not DEBUG)}
elif not IS_VERCEL and check_mysql_socket(os.environ.get('MYSQL_HOST', '127.0.0.1'), os.environ.get('MYSQL_PORT', 3307)):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('MYSQL_DATABASE', 'db_pelaporan_bulanan'),
            'USER': os.environ.get('MYSQL_USER', 'root'),
            'PASSWORD': os.environ.get('MYSQL_PASSWORD', '123456'),
            'HOST': os.environ.get('MYSQL_HOST', '127.0.0.1'),
            'PORT': os.environ.get('MYSQL_PORT', '3307'),
            'OPTIONS': {'charset': 'utf8mb4'},
        }
    }
else:
    # Di Vercel tanpa DATABASE_URL hanya /tmp yang bisa ditulis (data TIDAK permanen).
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': '/tmp/db.sqlite3' if IS_VERCEL else BASE_DIR / 'db.sqlite3',
        }
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

# Authentication Configuration
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# Internationalization
LANGUAGE_CODE = 'id'
TIME_ZONE = 'Asia/Jakarta'
USE_I18N = True
USE_TZ = True

# Static files (disajikan WhiteNoise, juga di Vercel)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles_build' / 'static'
WHITENOISE_USE_FINDERS = True          # tetap jalan tanpa collectstatic
WHITENOISE_AUTOREFRESH = DEBUG
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

# Media (tanda tangan kini disimpan di database; folder ini hanya untuk lokal)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Domain tepercaya untuk CSRF (wajib di Vercel / HTTPS)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]
if os.environ.get('VERCEL_URL'):
    CSRF_TRUSTED_ORIGINS.append('https://' + os.environ['VERCEL_URL'])
if os.environ.get('VERCEL_PROJECT_PRODUCTION_URL'):
    CSRF_TRUSTED_ORIGINS.append('https://' + os.environ['VERCEL_PROJECT_PRODUCTION_URL'])
CSRF_TRUSTED_ORIGINS.append('https://*.vercel.app')

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    X_FRAME_OPTIONS = 'DENY'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
}
