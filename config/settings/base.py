"""
Configurações base do projeto Locus Equipamentos.
Nada de credenciais aqui — tudo vem de variáveis de ambiente (.env),
lidas via python-decouple. Ver .env.example na raiz do repositório.
"""

from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --------------------------------------------------------------------------
# Segurança básica
# --------------------------------------------------------------------------

SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# URL permanente usada para montar o link que o QR Code aponta (seção 14
# da especificação). Fixa via .env, não derivada do Host da requisição —
# assim o QR físico impresso aponta sempre para o mesmo lugar,
# independente de qual header chegou na requisição que o gerou.
SITE_BASE_URL = config("SITE_BASE_URL", default="http://localhost:8000")

# --------------------------------------------------------------------------
# Apps
# --------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "simple_history",
    "axes",
]

# django-simple-history usa CharField(max_length=100) por padrão para o
# motivo de alteração (`history_change_reason`). A especificação (seção
# 8) exige motivo obrigatório em reclassificação/reemissão de patrimônio
# sem impor limite de tamanho, e `apps/equipment/services.py` de fato
# concatena texto extra ao motivo do usuário (ex.: "Superseded por
# LOC-XXXX-0001. Motivo: ..."). Motivos um pouco mais longos que 100
# caracteres já derrubavam a transação inteira com um DataError do
# Postgres. TextField remove esse limite arbitrário.
SIMPLE_HISTORY_HISTORY_CHANGE_REASON_USE_TEXT_FIELD = True

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.catalog",
    "apps.equipment",
    "apps.clients",
    "apps.operations",
    "apps.attachments",
    "apps.qrcodes",
    "apps.dashboard",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # django-axes exige ser o ÚLTIMO middleware da lista (especificação,
    # seção 11: "django-axes contra força bruta").
    "axes.middleware.AxesMiddleware",
]

# AxesStandaloneBackend precisa vir ANTES do ModelBackend padrão — é o que
# de fato bloqueia a tentativa de autenticação depois do limite de
# falhas, em vez de só registrar o evento.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Limiar e janela de bloqueio por força bruta. Sem número definido na
# especificação — usamos um padrão razoável para uma equipe pequena;
# ajustável pela Locus depois sem mudança de código.
AXES_FAILURE_LIMIT = config("AXES_FAILURE_LIMIT", default=5, cast=int)
AXES_COOLOFF_TIME = timedelta(minutes=config("AXES_COOLOFF_MINUTES", default=30, cast=int))
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_RESET_ON_SUCCESS = True

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

# --------------------------------------------------------------------------
# Banco de dados — PostgreSQL sempre (nem em dev usamos SQLite: a geração
# atômica de patrimônio depende de SELECT FOR UPDATE, que o SQLite não
# implementa de forma confiável sob concorrência real).
# --------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Senhas
# --------------------------------------------------------------------------

# Argon2 primeiro na lista (especificação, seção 11: "senha Argon2") — o
# Django troca o hash de qualquer usuário automaticamente para Argon2 no
# próximo login bem-sucedido, mesmo que a senha já exista com outro
# algoritmo; os hashers legados ficam listados depois só para conseguir
# LER hashes antigos (ex.: o superusuário criado antes desta mudança),
# nunca para gerar hash novo.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Internacionalização
# --------------------------------------------------------------------------

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Arquivos estáticos e de mídia (fotos de equipamento)
# --------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# --------------------------------------------------------------------------
# Segurança de sessão/cookies (seção 11 da especificação)
# --------------------------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = config("DJANGO_SECURE_COOKIES", default=True, cast=bool)
CSRF_COOKIE_SECURE = config("DJANGO_SECURE_COOKIES", default=True, cast=bool)
X_FRAME_OPTIONS = "DENY"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "equipment:list"
LOGOUT_REDIRECT_URL = "accounts:login"
