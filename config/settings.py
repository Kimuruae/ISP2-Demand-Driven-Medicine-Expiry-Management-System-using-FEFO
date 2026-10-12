import os
from pathlib import Path
from dotenv import load_dotenv

#Define BASE_DIR
BASE_DIR = Path(__file__).resolve().parent.parent

#Load the environment variables - Protected Local Database Configurations
load_dotenv(BASE_DIR / ".env")

#Security Configurations
SESSION_EXPIRE_AT_BROWSER_CLOSE = True #cookies expire when the user closes browser window
SESSION_COOKIE_AGE = 0
SESSION_SAVE_EVERY_REQUEST = True #ensures db session drops engine record reference on logout

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-before-deployment")
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

#Application Definition Matrix
INSTALLED_APPS = [
    # Core Django built-in apps (Required)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Custom Core System Architecture
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# 5. Live Database Engine Integration Config (PostgreSQL Node Mapping)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "med_fefo_db"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "ISP2#2026"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# 6. Security Credentials Hashing & Validation Policies
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 7. Local Facility Regional Alignment Settings (Nairobi / en-KE Scope)
LANGUAGE_CODE = "en-ke"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# 8. Static Files Asset Layout Matrices
STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# 9. Global Architecture Primary Key Configuration
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 10. Granular Identity Access Governance & Multi-User Routing Contracts
AUTH_USER_MODEL = "core.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "index"
LOGOUT_REDIRECT_URL = "login"