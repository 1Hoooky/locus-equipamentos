"""Configurações de produção (VPS HostGator, seção 10 da especificação)."""

from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = False

# Em produção, ALLOWED_HOSTS e CSRF_TRUSTED_ORIGINS vêm obrigatoriamente
# do .env — nunca deixamos "*" nem hosts hardcoded aqui.
if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS precisa estar definido em produção.")

SECURE_SSL_REDIRECT = config("DJANGO_SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
